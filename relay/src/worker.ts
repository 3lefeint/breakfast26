// The Cloudflare side: an HTTP/WebSocket front door, one MatchRoom Durable Object per join
// code (it holds a MatchCore and keeps it in storage), and a small RateLimiter Durable
// Object per client address and purpose. The locations (src/locations.ts) live in D1; the voice chat signaling
// (src/voice.ts, a VoiceRoom per match code) and its page (src/voicePage.ts) are served here as well.

import { DurableObject } from "cloudflare:workers";
import { Deps, MatchCore, MatchState, Out } from "./core";
import { CLOSE, LIMITS, PROTOCOL_VERSION, validName } from "./protocol";
import { authenticate, handleLocations, Rooms } from "./locations";
import { handleAdmin } from "./admin";
import { handleCircle } from "./circle";
import { iceServers, validateVoiceFrame, VOICE_CLOSE, VOICE_LIMITS } from "./voice";
import { VOICE_HTML, VOICE_JS } from "./voicePage";
import { TELEMETRY_LIMITS, TELEMETRY_VERSION, validateTelemetry } from "./telemetry";

export interface Env {
  MATCH: DurableObjectNamespace;
  LIMITER: DurableObjectNamespace;
  VOICE: DurableObjectNamespace;
  DB?: D1Database;
  RECORDS?: R2Bucket;            // the plain records of the circle; without it the circle routes answer 503
  SHARING?: string;              // "off" switches the circle routes off
  ADMIN_PASSWORD_HASH?: string;  // Worker secrets of the admin login (`npm run admin-password`)
  ADMIN_TOKEN_KEY?: string;
  TURN_KEY_ID?: string;          // Worker secrets of a Cloudflare TURN key; without them the voice chat gets STUN only
  TURN_KEY_API_TOKEN?: string;
}

const CREATE_LIMIT = { limit: 10, windowMs: 60_000 };
const JOIN_LIMIT = { limit: 30, windowMs: 60_000 };
const TELEMETRY_IP_LIMIT = { limit: 240, windowMs: 3_600_000 };
const TELEMETRY_INSTALL_LIMIT = { limit: 120, windowMs: 3_600_000 };
const VOICE_TICKET_LIMIT = { limit: 30, windowMs: 60_000 };
const VOICE_JOIN_LIMIT = { limit: 60, windowMs: 60_000 };

const deps: Deps = {
  now: () => Date.now(),
  randomHex: (bytes) => [...crypto.getRandomValues(new Uint8Array(bytes))].map((b) => b.toString(16).padStart(2, "0")).join(""),
  uuid: () => crypto.randomUUID(),
};

function randomCode(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(LIMITS.CODE_LENGTH));
  return [...bytes].map((b) => LIMITS.CODE_ALPHABET[b % LIMITS.CODE_ALPHABET.length]).join("");
}

/** The match rooms as the locations routes see them. */
function rooms(env: Env): Rooms {
  const room = (code: string) => env.MATCH.get(env.MATCH.idFromName(code));
  return {
    async status(code) {
      const res = await room(code).fetch("https://room/status");
      return res.status === 200 ? await res.json() : null;
    },
    async ticket(code) {
      const res = await room(code).fetch("https://room/ticket", { method: "POST" });
      return res.status === 200 ? ((await res.json()) as { ticket: string }).ticket : null;
    },
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function limited(env: Env, request: Request, purpose: string, cfg: { limit: number; windowMs: number }, key?: string): Promise<boolean> {
  const who = key ?? request.headers.get("cf-connecting-ip") ?? "local";
  const stub = env.LIMITER.get(env.LIMITER.idFromName(`${purpose}:${who}`));
  const res = await stub.fetch(`https://limiter/hit?limit=${cfg.limit}&window=${cfg.windowMs}`);
  return res.status === 429;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return new Response(`breakfast relay, protocol ${PROTOCOL_VERSION}\n`);
    }

    if (request.method === "POST" && url.pathname === "/api/matches") {
      const raw = await request.text();
      let body: { protocol_version?: unknown; site?: unknown } = {};
      try { body = JSON.parse(raw); } catch { /* handled below */ }
      if (body.protocol_version !== PROTOCOL_VERSION) {
        return json({ error: `protocol version ${String(body.protocol_version)} is not supported, please upgrade Breakfast` }, 426);
      }
      if (await limited(env, request, "create", CREATE_LIMIT)) return json({ error: "too many requests" }, 429);
      // A registered location signs the request; its linked locations can then list and join the match.
      let hostLocation: string | null = null;
      if (request.headers.get("x-location")) {
        if (!env.DB) return json({ error: "locations are not set up here" }, 503);
        const who = await authenticate(request, env, raw, Date.now());
        if (who instanceof Response) return who;
        hostLocation = who.id;
      }
      for (let attempt = 0; attempt < 8; attempt++) {
        const code = randomCode();
        const room = env.MATCH.get(env.MATCH.idFromName(code));
        const res = await room.fetch(`https://room/reserve?code=${code}`, { method: "POST" });
        if (res.status !== 200) continue;
        if (hostLocation && env.DB) {
          const now = Date.now();
          const site = typeof body.site === "string" && validName(body.site) ? body.site.trim() : null;
          await env.DB.prepare("DELETE FROM open_matches WHERE expires_at < ?").bind(now).run();
          await env.DB.prepare("INSERT INTO open_matches (code, location_id, site, created_at, expires_at) VALUES (?, ?, ?, ?, ?)")
            .bind(code, hostLocation, site, now, now + LIMITS.CODE_TTL_MS).run();
        }
        return json({ code, expires_in_s: LIMITS.CODE_TTL_MS / 1000 });
      }
      return json({ error: "could not reserve a code" }, 503);
    }

    if (request.method === "POST" && url.pathname === "/telemetry") return telemetry(request, env);

    if (request.method === "GET" && url.pathname === "/voice") {
      return new Response(VOICE_HTML, { headers: {
        "content-type": "text/html; charset=utf-8", "cache-control": "no-cache", "x-content-type-options": "nosniff",
        "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self' wss:; media-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        "referrer-policy": "no-referrer",
      } });
    }
    if (request.method === "GET" && url.pathname === "/voice.js") {
      return new Response(VOICE_JS, { headers: { "content-type": "text/javascript; charset=utf-8", "cache-control": "no-cache", "x-content-type-options": "nosniff" } });
    }

    const ticket = url.pathname.match(/^\/api\/matches\/([A-Z0-9]{6})\/voice-ticket$/);
    if (request.method === "POST" && ticket) {
      if (await limited(env, request, "voice-ticket", VOICE_TICKET_LIMIT)) return json({ error: "too many requests" }, 429);
      const raw = await request.text();
      if (raw.length > 1024) return json({ error: "too large" }, 413);
      const res = await env.MATCH.get(env.MATCH.idFromName(ticket[1])).fetch("https://room/voice-ticket", { method: "POST", body: raw });
      return new Response(res.status === 200 ? await res.text() : JSON.stringify({ error: "not allowed" }), { status: res.status === 200 ? 200 : 401, headers: { "content-type": "application/json" } });
    }

    const voice = url.pathname.match(/^\/voice\/([A-Z0-9]{6})$/);
    if (request.method === "GET" && voice) {
      if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") return new Response("expected a websocket", { status: 426 });
      if (await limited(env, request, "voice-join", VOICE_JOIN_LIMIT)) return json({ error: "too many requests" }, 429);
      return env.VOICE.get(env.VOICE.idFromName(voice[1])).fetch(request);
    }

    const located = await handleLocations(request, env, (purpose, cfg, key) => limited(env, request, purpose, cfg, key), rooms(env));
    if (located) return located;

    const admin = await handleAdmin(request, env, (purpose, cfg, key) => limited(env, request, purpose, cfg, key));
    if (admin) return admin;

    const circle = await handleCircle(request, env, (purpose, cfg, key) => limited(env, request, purpose, cfg, key));
    if (circle) return circle;

    const ws = url.pathname.match(/^\/ws\/([A-Z0-9]{6})$/);
    if (request.method === "GET" && ws) {
      if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") return new Response("expected a websocket", { status: 426 });
      if (await limited(env, request, "join", JOIN_LIMIT)) return json({ error: "too many requests" }, 429);
      return env.MATCH.get(env.MATCH.idFromName(ws[1])).fetch(request);
    }

    return new Response("not found", { status: 404 });
  },
};

// The usage reports: nothing is stored that failed the strict check, and the address is never stored.
async function telemetry(request: Request, env: Env): Promise<Response> {
  if (!env.DB) return json({ error: "reports are not set up here" }, 503);
  if (await limited(env, request, "telemetry", TELEMETRY_IP_LIMIT)) return json({ error: "too many requests" }, 429);
  const raw = await request.text();
  if (raw.length > TELEMETRY_LIMITS.BODY_BYTES) return json({ error: "too large" }, 413);
  let body: unknown;
  try { body = JSON.parse(raw); } catch { return json({ error: "not JSON" }, 400); }
  const version = (body as { protocol_version?: unknown } | null)?.protocol_version;
  if (version !== TELEMETRY_VERSION) return json({ error: `protocol version ${String(version)} is not supported` }, 426);
  const checked = validateTelemetry(body);
  if ("error" in checked) return json({ error: checked.error }, 400);
  const { batch } = checked;
  if (await limited(env, request, "telemetry-install", TELEMETRY_INSTALL_LIMIT, batch.installId)) return json({ error: "too many requests" }, 429);
  const insert = env.DB.prepare("INSERT INTO events (install_id, version, platform, type, ts, data) VALUES (?, ?, ?, ?, ?, ?)");
  await env.DB.batch(batch.events.map((e) => {
    const { type, ts, ...data } = e;
    return insert.bind(batch.installId, batch.version, batch.platform, type, ts, JSON.stringify(data));
  }));
  return json({ stored: batch.events.length });
}

export class MatchRoom extends DurableObject<Env> {
  private core: MatchCore | null = null;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      const state = await ctx.storage.get<MatchState>("state");
      if (state) this.core = new MatchCore(state, deps);
    });
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/reserve") {
      if (this.core) return new Response("exists", { status: 409 });
      this.core = MatchCore.reserve(url.searchParams.get("code") ?? "", deps);
      await this.save();
      return new Response("ok");
    }

    if (url.pathname === "/voice-ticket" && request.method === "POST") {
      let body: { site?: unknown; token?: unknown } = {};
      try { body = await request.json(); } catch { /* refused below */ }
      const ticket = this.core && typeof body.site === "string" && typeof body.token === "string" ? await this.core.issueVoiceTicket(body.site, body.token) : null;
      await this.save();
      return ticket ? Response.json({ ticket }) : new Response("no", { status: 401 });
    }
    if (url.pathname === "/voice-auth" && request.method === "POST") {
      let body: { site?: unknown; ticket?: unknown } = {};
      try { body = await request.json(); } catch { /* refused below */ }
      const ok = this.core && typeof body.site === "string" && typeof body.ticket === "string" && await this.core.voiceTicketOk(body.site, body.ticket);
      return new Response(ok ? "ok" : "no", { status: ok ? 200 : 401 });
    }
    if (url.pathname === "/status") {
      return this.core && this.core.phase !== "reserved" ? Response.json(this.core.status()) : new Response("none", { status: 404 });
    }
    if (url.pathname === "/ticket" && request.method === "POST") {
      const ticket = this.core ? await this.core.issueTicket() : null;
      if (!ticket) return new Response("not open", { status: 409 });
      await this.save();
      return Response.json({ ticket });
    }

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    const conn = crypto.randomUUID();
    this.ctx.acceptWebSocket(server, [conn]);
    if (!this.core) {
      server.send(JSON.stringify({ type: "error", code: CLOSE.UNKNOWN_CODE, message: "unknown code" }));
      server.close(CLOSE.UNKNOWN_CODE, "unknown code");
    } else {
      this.core.connect(conn);
      await this.save();
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    const conn = this.ctx.getTags(ws)[0];
    if (!this.core) return;
    let frame: unknown;
    try {
      frame = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message));
    } catch {
      this.send([{ to: conn, frame: { type: "error", code: CLOSE.BAD_REQUEST, message: "not JSON" }, close: CLOSE.BAD_REQUEST }]);
      return;
    }
    try {
      this.send(await this.core.frame(conn, frame));
    } catch (e) {
      console.error("relay error", e);
      this.send([{ to: conn, frame: { type: "error", code: CLOSE.BAD_REQUEST, message: "internal error" }, close: CLOSE.BAD_REQUEST }]);
    }
    await this.save();
  }

  async webSocketClose(ws: WebSocket): Promise<void> {
    await this.dropped(ws);
    try { ws.close(); } catch { /* already closed */ }
  }

  async webSocketError(ws: WebSocket): Promise<void> {
    await this.dropped(ws);
  }

  async alarm(): Promise<void> {
    if (!this.core) return;
    const s = this.core.s;
    if (this.core.isOver() && s.endedAt !== null && Date.now() >= s.endedAt + 60 * 60 * 1000) {
      for (const ws of this.ctx.getWebSockets()) try { ws.close(CLOSE.OVER, "match over"); } catch { /* ignore */ }
      await this.ctx.storage.deleteAll();
      this.core = null;
      return;
    }
    this.send(this.core.tick());
    await this.save();
  }

  private async dropped(ws: WebSocket): Promise<void> {
    if (!this.core) return;
    this.send(this.core.disconnect(this.ctx.getTags(ws)[0]));
    await this.save();
  }

  private send(outs: Out[]): void {
    for (const o of outs) {
      const ws = this.ctx.getWebSockets(o.to)[0];
      if (!ws) continue;
      try {
        if (o.frame) ws.send(JSON.stringify(o.frame));
        if (o.close !== undefined) ws.close(o.close, o.frame && typeof o.frame.message === "string" ? o.frame.message.slice(0, 120) : "closed");
      } catch { /* the socket is gone */ }
    }
  }

  private async save(): Promise<void> {
    if (!this.core) return;
    await this.ctx.storage.put("state", this.core.s);
    const wake = this.core.nextWake();
    if (wake === null) await this.ctx.storage.deleteAlarm();
    else await this.ctx.storage.setAlarm(Math.max(wake, Date.now() + 1));
  }
}

/** The signaling of the voice chat of one match: who is in the room, and the offers, answers and ICE candidates
 *  they pass to each other. Entering needs the voice ticket of a site of the match. */
interface VoicePeer { peer: string | null; site: string | null; muted: boolean; since: number }

export class VoiceRoom extends DurableObject<Env> {
  async fetch(request: Request): Promise<Response> {
    const code = new URL(request.url).pathname.split("/").pop() ?? "";
    await this.ctx.storage.put("code", code);
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({ peer: null, site: null, muted: false, since: Date.now() } satisfies VoicePeer);
    await this.ctx.storage.setAlarm(Date.now() + VOICE_LIMITS.JOIN_TIMEOUT_MS);
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    const me = ws.deserializeAttachment() as VoicePeer;
    const text = typeof message === "string" ? message : new TextDecoder().decode(message);
    if (text.length > VOICE_LIMITS.FRAME_BYTES) return this.refuse(ws, VOICE_CLOSE.BAD_REQUEST, "frame too large");
    let frame: Record<string, unknown>;
    try { frame = JSON.parse(text); } catch { return this.refuse(ws, VOICE_CLOSE.BAD_REQUEST, "not JSON"); }
    const bad = validateVoiceFrame(frame);
    if (bad) return this.refuse(ws, VOICE_CLOSE.BAD_REQUEST, bad);

    if (frame.type === "join") {
      if (me.peer) return this.refuse(ws, VOICE_CLOSE.BAD_REQUEST, "already joined");
      return this.join(ws, me, frame.site as string, frame.ticket as string);
    }
    if (!me.peer) return this.refuse(ws, VOICE_CLOSE.BAD_REQUEST, "join first");
    if (frame.type === "mute") {
      me.muted = frame.muted as boolean;
      ws.serializeAttachment(me);
      this.others(ws, { type: "mute", peer: me.peer, muted: me.muted });
      return;
    }
    const target = this.ctx.getWebSockets().find((w) => (w.deserializeAttachment() as VoicePeer).peer === frame.to);
    if (target) target.send(JSON.stringify({ type: "signal", from: me.peer, data: frame.data }));
  }

  async webSocketClose(ws: WebSocket): Promise<void> {
    this.left(ws);
    try { ws.close(); } catch { /* already closed */ }
  }

  async webSocketError(ws: WebSocket): Promise<void> {
    this.left(ws);
  }

  async alarm(): Promise<void> {
    const now = Date.now();
    for (const ws of this.ctx.getWebSockets()) {
      const p = ws.deserializeAttachment() as VoicePeer;
      if (!p.peer && now - p.since >= VOICE_LIMITS.JOIN_TIMEOUT_MS) this.refuse(ws, VOICE_CLOSE.BAD_REQUEST, "join timeout");
    }
  }

  private async join(ws: WebSocket, me: VoicePeer, site: string, ticket: string): Promise<void> {
    const code = (await this.ctx.storage.get<string>("code")) ?? "";
    const auth = await this.env.MATCH.get(this.env.MATCH.idFromName(code)).fetch("https://room/voice-auth", { method: "POST", body: JSON.stringify({ site, ticket }) });
    if (auth.status !== 200) return this.refuse(ws, VOICE_CLOSE.UNAUTHORIZED, "not allowed");
    for (const w of this.ctx.getWebSockets()) {          // the same site joining again replaces its older connection
      if (w !== ws && (w.deserializeAttachment() as VoicePeer).site === site) this.refuse(w, VOICE_CLOSE.CONFLICT, "replaced by a new connection");
    }
    const others = this.ctx.getWebSockets().filter((w) => w !== ws && (w.deserializeAttachment() as VoicePeer).peer);
    if (others.length >= VOICE_LIMITS.MAX_PEERS) return this.refuse(ws, VOICE_CLOSE.CONFLICT, "the voice chat is full");
    me.peer = [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join("");
    me.site = site;
    ws.serializeAttachment(me);
    const peers = others.map((w) => { const p = w.deserializeAttachment() as VoicePeer; return { peer: p.peer, site: p.site, muted: p.muted }; });
    ws.send(JSON.stringify({ type: "joined", peer: me.peer, peers, ice: await iceServers(this.env) }));
    this.others(ws, { type: "peer-joined", peer: me.peer, site });
  }

  private left(ws: WebSocket): void {
    const p = ws.deserializeAttachment() as VoicePeer | null;
    if (p?.peer) this.others(ws, { type: "peer-left", peer: p.peer });
  }

  private others(ws: WebSocket, frame: Record<string, unknown>): void {
    const text = JSON.stringify(frame);
    for (const w of this.ctx.getWebSockets()) {
      if (w === ws || !(w.deserializeAttachment() as VoicePeer).peer) continue;
      try { w.send(text); } catch { /* the socket is gone */ }
    }
  }

  private refuse(ws: WebSocket, code: number, message: string): void {
    try {
      ws.send(JSON.stringify({ type: "error", code, message }));
      const p = ws.deserializeAttachment() as VoicePeer | null;
      ws.serializeAttachment({ ...(p ?? {}), peer: null });   // a refused socket is no longer in the room
      if (p?.peer) this.others(ws, { type: "peer-left", peer: p.peer });
      ws.close(code, message.slice(0, 120));
    } catch { /* already closed */ }
  }
}

export class RateLimiter extends DurableObject<Env> {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get("limit"));
    const windowMs = Number(url.searchParams.get("window"));
    const now = Date.now();
    const state = (await this.ctx.storage.get<{ start: number; count: number }>("w")) ?? { start: now, count: 0 };
    if (now - state.start >= windowMs) { state.start = now; state.count = 0; }
    state.count++;
    await this.ctx.storage.put("w", state);
    await this.ctx.storage.setAlarm(state.start + windowMs + 1000);
    return new Response(null, { status: state.count > limit ? 429 : 200 });
  }

  async alarm(): Promise<void> {
    await this.ctx.storage.deleteAll();
  }
}
