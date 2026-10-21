// The Cloudflare side: an HTTP/WebSocket front door, one MatchRoom Durable Object per join
// code (it holds a MatchCore and keeps it in storage), and a small RateLimiter Durable
// Object per client address and purpose. The locations (src/locations.ts) live in D1.

import { DurableObject } from "cloudflare:workers";
import { Deps, MatchCore, MatchState, Out } from "./core";
import { CLOSE, LIMITS, PROTOCOL_VERSION, validName } from "./protocol";
import { authenticate, handleLocations, Rooms } from "./locations";
import { TELEMETRY_LIMITS, TELEMETRY_VERSION, validateTelemetry } from "./telemetry";

export interface Env {
  MATCH: DurableObjectNamespace;
  LIMITER: DurableObjectNamespace;
  DB?: D1Database;
}

const CREATE_LIMIT = { limit: 10, windowMs: 60_000 };
const JOIN_LIMIT = { limit: 30, windowMs: 60_000 };
const TELEMETRY_IP_LIMIT = { limit: 240, windowMs: 3_600_000 };
const TELEMETRY_INSTALL_LIMIT = { limit: 120, windowMs: 3_600_000 };

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

    const located = await handleLocations(request, env, (purpose, cfg, key) => limited(env, request, purpose, cfg, key), rooms(env));
    if (located) return located;

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
