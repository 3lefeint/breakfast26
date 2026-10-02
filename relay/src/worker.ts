// The Cloudflare side: an HTTP/WebSocket front door, one MatchRoom Durable Object per join
// code (it holds a MatchCore and keeps it in storage), and a small RateLimiter Durable
// Object per client address and purpose.

import { DurableObject } from "cloudflare:workers";
import { Deps, MatchCore, MatchState, Out } from "./core";
import { CLOSE, LIMITS, PROTOCOL_VERSION } from "./protocol";

export interface Env {
  MATCH: DurableObjectNamespace;
  LIMITER: DurableObjectNamespace;
}

const CREATE_LIMIT = { limit: 10, windowMs: 60_000 };
const JOIN_LIMIT = { limit: 30, windowMs: 60_000 };

const deps: Deps = {
  now: () => Date.now(),
  randomHex: (bytes) => [...crypto.getRandomValues(new Uint8Array(bytes))].map((b) => b.toString(16).padStart(2, "0")).join(""),
  uuid: () => crypto.randomUUID(),
};

function randomCode(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(LIMITS.CODE_LENGTH));
  return [...bytes].map((b) => LIMITS.CODE_ALPHABET[b % LIMITS.CODE_ALPHABET.length]).join("");
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function limited(env: Env, request: Request, purpose: string, cfg: { limit: number; windowMs: number }): Promise<boolean> {
  const ip = request.headers.get("cf-connecting-ip") ?? "local";
  const stub = env.LIMITER.get(env.LIMITER.idFromName(`${purpose}:${ip}`));
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
      let body: { protocol_version?: unknown } = {};
      try { body = await request.json(); } catch { /* handled below */ }
      if (body.protocol_version !== PROTOCOL_VERSION) {
        return json({ error: `protocol version ${String(body.protocol_version)} is not supported, please upgrade Breakfast` }, 426);
      }
      if (await limited(env, request, "create", CREATE_LIMIT)) return json({ error: "too many requests" }, 429);
      for (let attempt = 0; attempt < 8; attempt++) {
        const code = randomCode();
        const room = env.MATCH.get(env.MATCH.idFromName(code));
        const res = await room.fetch(`https://room/reserve?code=${code}`, { method: "POST" });
        if (res.status === 200) return json({ code, expires_in_s: LIMITS.CODE_TTL_MS / 1000 });
      }
      return json({ error: "could not reserve a code" }, 503);
    }

    const ws = url.pathname.match(/^\/ws\/([A-Z0-9]{6})$/);
    if (request.method === "GET" && ws) {
      if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") return new Response("expected a websocket", { status: 426 });
      if (await limited(env, request, "join", JOIN_LIMIT)) return json({ error: "too many requests" }, 429);
      return env.MATCH.get(env.MATCH.idFromName(ws[1])).fetch(request);
    }

    return new Response("not found", { status: 404 });
  },
};

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
