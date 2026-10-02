// The match state machine, free of Cloudflare APIs so it runs in plain Node tests and
// inside the Durable Object alike. It never talks to a socket: `frame`, `disconnect` and
// `tick` return the frames to send (`Out`), the adapter does the sending and the storing.

import { CLOSE, Frame, LIMITS, PROTOCOL_VERSION, Throw, validateClientFrame } from "./protocol";

export type Phase = "reserved" | "lobby" | "playing" | "paused" | "finished" | "aborted";

interface SiteState {
  name: string;
  tokenHash: string;
  players: string[];
  connection: string | null;
  left: boolean;
  droppedAt: number | null;
}

export interface TurnRecord {
  seq: number;
  player: string;
  throws: Throw[];
  next_player: string | null;
  eliminated: string[];
  winner: string | null;
  site: string;
}

export interface MatchState {
  code: string;
  phase: Phase;
  createdAt: number;
  expiresAt: number;
  endedAt: number | null;
  passwordSalt: string | null;
  passwordHash: string | null;
  host: string | null;
  sites: Record<string, SiteState>;
  pending: Record<string, number>;
  conns: Record<string, string>;
  lives: number;
  order: string[];
  active: string[];
  eliminated: string[];
  current: string | null;
  owners: Record<string, string>;
  seq: number;
  log: TurnRecord[];
  acks: Record<string, Record<string, string>>;
  matchId: string | null;
  rejoinDeadline: number | null;
  decisionSent: boolean;
  failedHellos: number;
  lockedUntil: number;
}

export interface Out {
  to: string;
  frame?: Frame;
  close?: number;
}

export interface Deps {
  now(): number;
  randomHex(bytes: number): string;
  uuid(): string;
}

const enc = new TextEncoder();
const hex = (buf: ArrayBuffer) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function pbkdf2(password: string, saltHex: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: enc.encode(saltHex), iterations: 100_000 }, key, 256);
  return hex(bits);
}

async function sha256(text: string): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", enc.encode(text)));
}

function sameText(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export class MatchCore {
  constructor(public s: MatchState, private deps: Deps) {}

  static reserve(code: string, deps: Deps): MatchCore {
    const now = deps.now();
    return new MatchCore({
      code, phase: "reserved", createdAt: now, expiresAt: now + LIMITS.CODE_TTL_MS, endedAt: null,
      passwordSalt: null, passwordHash: null, host: null, sites: {}, pending: {}, conns: {},
      lives: 0, order: [], active: [], eliminated: [], current: null, owners: {},
      seq: 0, log: [], acks: {}, matchId: null, rejoinDeadline: null, decisionSent: false,
      failedHellos: 0, lockedUntil: 0,
    }, deps);
  }

  get phase(): Phase { return this.s.phase; }
  isOver(): boolean { return this.s.phase === "finished" || this.s.phase === "aborted"; }

  // ── connections ──────────────────────────────────────────────────────────────

  connect(conn: string): void {
    this.s.pending[conn] = this.deps.now();
  }

  async frame(conn: string, raw: unknown): Promise<Out[]> {
    const bad = validateClientFrame(raw);
    if (bad) return [this.fail(conn, CLOSE.BAD_REQUEST, bad)];
    const m = raw as Frame;
    const site = this.s.conns[conn];
    if (!site) {
      if (m.type !== "hello") return [this.fail(conn, CLOSE.BAD_REQUEST, "send hello first")];
      return this.hello(conn, m);
    }
    switch (m.type) {
      case "hello": return [this.fail(conn, CLOSE.BAD_REQUEST, "already said hello")];
      case "lobby_set_players": return this.lobbySetPlayers(conn, site, m);
      case "lobby_start": return this.lobbyStart(conn, site, m);
      case "rematch": return this.rematch(conn, site);
      case "dart": return this.dart(site, m);
      case "turn": return this.turn(conn, site, m);
      case "ack": return this.ack(site, m);
      case "decision": return this.decision(conn, site, m);
      case "leave": return this.leave(conn, site);
    }
    return [];
  }

  disconnect(conn: string): Out[] {
    delete this.s.pending[conn];
    const name = this.s.conns[conn];
    if (!name) return [];
    delete this.s.conns[conn];
    const site = this.s.sites[name];
    if (!site || site.connection !== conn) return [];
    site.connection = null;
    const now = this.deps.now();
    switch (this.s.phase) {
      case "lobby":
        if (name === this.s.host) return this.abort();
        delete this.s.sites[name];
        return this.lobbyFrames();
      case "playing":
      case "paused": {
        site.droppedAt = now;
        this.s.phase = "paused";
        this.s.rejoinDeadline = Math.max(this.s.rejoinDeadline ?? 0, now + LIMITS.REJOIN_WINDOW_MS);
        return this.toAll({ type: "paused", reason: "disconnect", site: name, rejoin_until: this.s.rejoinDeadline });
      }
      default:
        return [];
    }
  }

  tick(): Out[] {
    const s = this.s;
    const now = this.deps.now();
    const out: Out[] = [];
    for (const [conn, since] of Object.entries(s.pending)) {
      if (now - since >= LIMITS.HELLO_TIMEOUT_MS) {
        delete s.pending[conn];
        out.push(this.fail(conn, CLOSE.BAD_REQUEST, "hello timeout"));
      }
    }
    if ((s.phase === "reserved" || s.phase === "lobby") && now >= s.expiresAt) {
      out.push(...this.abort());
    } else if (s.phase === "paused" && !s.decisionSent && s.rejoinDeadline !== null && now >= s.rejoinDeadline) {
      const hostSite = s.host ? s.sites[s.host] : undefined;
      if (!hostSite || hostSite.connection === null) {
        out.push(...this.abort());
      } else {
        s.decisionSent = true;
        out.push({ to: hostSite.connection, frame: { type: "decision_needed", sites: this.droppedSites() } });
      }
    }
    return out;
  }

  /** When the adapter should call `tick` next, as epoch ms, or null. */
  nextWake(): number | null {
    const s = this.s;
    const times: number[] = Object.values(s.pending).map((t) => t + LIMITS.HELLO_TIMEOUT_MS);
    if (s.phase === "reserved" || s.phase === "lobby") times.push(s.expiresAt);
    if (s.phase === "paused" && !s.decisionSent && s.rejoinDeadline !== null) times.push(s.rejoinDeadline);
    if (this.isOver() && s.endedAt !== null) times.push(s.endedAt + 60 * 60 * 1000);
    return times.length ? Math.min(...times) : null;
  }

  // ── handlers ─────────────────────────────────────────────────────────────────

  private async hello(conn: string, m: Frame): Promise<Out[]> {
    const s = this.s;
    delete s.pending[conn];
    const now = this.deps.now();
    if (m.protocol_version !== PROTOCOL_VERSION) {
      return [this.fail(conn, CLOSE.UPGRADE, `protocol version ${m.protocol_version} is not supported, please upgrade Breakfast`)];
    }
    if (this.isOver()) return [this.fail(conn, CLOSE.OVER, "this match is over")];
    if (now < s.lockedUntil) return [this.fail(conn, CLOSE.RATE_LIMITED, "too many failed attempts, try again later")];
    const site = m.site as string;

    if (m.mode === "create") {
      if (s.phase !== "reserved") return [this.fail(conn, CLOSE.CONFLICT, "this code is already in use")];
      s.passwordSalt = this.deps.randomHex(16);
      s.passwordHash = await pbkdf2(m.password as string, s.passwordSalt);
      s.host = site;
      s.phase = "lobby";
      const token = await this.addSite(conn, site);
      return [this.welcome(conn, site, token, true), ...this.lobbyFrames()];
    }

    if (s.phase === "reserved") return [this.fail(conn, CLOSE.UNKNOWN_CODE, "unknown code")];

    if (m.mode === "join") {
      if (s.phase !== "lobby") return [this.fail(conn, CLOSE.CONFLICT, "the match has already started")];
      if (!(await this.passwordOk(m.password as string))) return [this.failAuth(conn, "wrong password")];
      if (s.sites[site]) return [this.fail(conn, CLOSE.CONFLICT, "that site name is already taken")];
      if (Object.keys(s.sites).length >= LIMITS.MAX_SITES) return [this.fail(conn, CLOSE.CONFLICT, "the match is full")];
      const token = await this.addSite(conn, site);
      return [this.welcome(conn, site, token, false), ...this.lobbyFrames()];
    }

    // rejoin
    const known = s.sites[site];
    if (!known || known.left || !sameText(known.tokenHash, await sha256(m.token as string))) {
      return [this.failAuth(conn, "unknown site or wrong token")];
    }
    const out: Out[] = [];
    if (known.connection) {
      delete s.conns[known.connection];
      out.push({ to: known.connection, frame: { type: "error", code: CLOSE.CONFLICT, message: "replaced by a new connection" }, close: CLOSE.CONFLICT });
    }
    known.connection = conn;
    known.droppedAt = null;
    s.conns[conn] = site;
    out.push(this.welcome(conn, site, m.token as string, site === s.host));
    if (s.phase === "lobby") return [...out, ...this.lobbyFrames()];
    out.push({ to: conn, frame: this.startedFrame() });
    for (const t of s.log.filter((t) => t.seq > (m.last_seq as number))) out.push({ to: conn, frame: { type: "turn", ...t } });
    if (s.phase === "paused" && !Object.values(s.sites).some((x) => !x.left && x.connection === null)) {
      s.phase = "playing";
      s.rejoinDeadline = null;
      s.decisionSent = false;
      out.push(...this.toAll({ type: "resumed", site }));
    }
    return out;
  }

  private lobbySetPlayers(conn: string, site: string, m: Frame): Out[] {
    const s = this.s;
    if (s.phase !== "lobby") return [this.rejected(conn, "lobby_set_players", "the match is not in the lobby")];
    const players = m.players as string[];
    const others = new Set(Object.values(s.sites).filter((x) => x.name !== site).flatMap((x) => x.players));
    const taken = players.find((p) => others.has(p));
    if (taken) return [this.rejected(conn, "lobby_set_players", `the name ${taken} is already in the lobby`)];
    if (others.size + players.length > LIMITS.MAX_PLAYERS) return [this.rejected(conn, "lobby_set_players", `at most ${LIMITS.MAX_PLAYERS} players`)];
    s.sites[site].players = players;
    return this.lobbyFrames();
  }

  private lobbyStart(conn: string, site: string, m: Frame): Out[] {
    const s = this.s;
    if (site !== s.host) return [this.rejected(conn, "lobby_start", "only the host can start the match")];
    if (s.phase !== "lobby") return [this.rejected(conn, "lobby_start", "the match is not in the lobby")];
    if (Object.values(s.sites).some((x) => x.connection === null)) return [this.rejected(conn, "lobby_start", "a site is not connected")];
    const players = Object.values(s.sites).flatMap((x) => x.players);
    const order = m.order as string[];
    if (players.length < LIMITS.MIN_PLAYERS) return [this.rejected(conn, "lobby_start", `at least ${LIMITS.MIN_PLAYERS} players are needed`)];
    if (order.length !== players.length || !order.every((p) => players.includes(p))) {
      return [this.rejected(conn, "lobby_start", "the order must list every lobby player once")];
    }
    s.phase = "playing";
    s.lives = m.lives as number;
    s.order = [...order];
    s.active = [...order];
    s.eliminated = [];
    s.current = order[0];
    s.owners = {};
    for (const x of Object.values(s.sites)) for (const p of x.players) s.owners[p] = x.name;
    s.matchId = this.deps.uuid();
    s.seq = 0;
    s.log = [];
    s.acks = {};
    return this.toAll(this.startedFrame());
  }

  /** The host opens the lobby again after a finished match: same sites and players, in the
   *  order of a local rematch (the first eliminated starts, the winner throws last). Sites
   *  that are not connected any more are dropped and can join again. */
  private rematch(conn: string, site: string): Out[] {
    const s = this.s;
    if (site !== s.host) return [this.rejected(conn, "rematch", "only the host can start a rematch")];
    if (s.phase !== "finished") return [this.rejected(conn, "rematch", "the match is not finished")];
    const ranked = this.placements(s.active[0] ?? null).map((p) => p.player).reverse();
    for (const [name, x] of Object.entries(s.sites)) if (x.left || x.connection === null) delete s.sites[name];
    const present = Object.values(s.sites).flatMap((x) => x.players);
    s.order = [...ranked.filter((p) => present.includes(p)), ...present.filter((p) => !ranked.includes(p))];
    s.phase = "lobby";
    s.expiresAt = this.deps.now() + LIMITS.CODE_TTL_MS;
    s.endedAt = null;
    s.active = [];
    s.eliminated = [];
    s.current = null;
    s.owners = {};
    s.seq = 0;
    s.log = [];
    s.acks = {};
    s.matchId = null;
    s.rejoinDeadline = null;
    s.decisionSent = false;
    return [...this.toAll({ type: "rematch" }), ...this.lobbyFrames()];
  }

  private dart(site: string, m: Frame): Out[] {
    const s = this.s;
    if (s.phase !== "playing" || s.owners[m.player as string] !== site || m.player !== s.current || m.seq !== s.seq + 1) return [];
    return this.toAll({ ...m, site }, site);
  }

  private turn(conn: string, site: string, m: Frame): Out[] {
    const s = this.s;
    const seq = m.seq as number;
    const no = (reason: string) => [{ to: conn, frame: { type: "turn_rejected", seq, reason } }];
    if (s.phase === "paused") return no("the match is paused");
    if (s.phase !== "playing") return no("the match is not being played");
    const player = m.player as string;
    if (s.owners[player] !== site) return no("that player is not yours");
    if (player !== s.current) return no("it is not that player's turn");
    if (seq !== s.seq + 1) return no(`expected seq ${s.seq + 1}`);
    const eliminated = m.eliminated as string[];
    if (new Set(eliminated).size !== eliminated.length || eliminated.some((p) => !s.active.includes(p))) return no("eliminated lists a player that is not active");
    const remaining = s.active.filter((p) => !eliminated.includes(p));
    const winner = m.winner as string | null;
    const next = m.next_player as string | null;
    if (winner !== null) {
      if (remaining.length !== 1 || remaining[0] !== winner) return no("the winner must be the only player left");
      if (next !== null) return no("next_player must be null when there is a winner");
    } else {
      if (remaining.length < 2) return no("a single player left must be named the winner");
      if (next === null || !remaining.includes(next)) return no("next_player must be an active player");
    }
    const record: TurnRecord = { seq, player, throws: m.throws as Throw[], next_player: next, eliminated, winner, site };
    s.log.push(record);
    s.seq = seq;
    s.eliminated.push(...eliminated);
    s.active = remaining;
    s.current = next;
    const out: Out[] = [{ to: conn, frame: { type: "turn_ok", seq } }, ...this.toAll({ type: "turn", ...record }, site)];
    if (winner !== null) out.push(...this.finish(winner));
    return out;
  }

  private ack(site: string, m: Frame): Out[] {
    const s = this.s;
    if (s.phase !== "playing" && s.phase !== "paused" && s.phase !== "finished") return [];
    const key = String(m.seq);
    (s.acks[key] ??= {})[site] = m.hash as string;
    const connected = Object.values(s.sites).filter((x) => x.connection !== null).map((x) => x.name);
    if (!connected.every((n) => n in s.acks[key])) return [];
    const hashes = Object.fromEntries(connected.map((n) => [n, s.acks[key][n]]));
    delete s.acks[key];
    if (new Set(Object.values(hashes)).size === 1) return [];
    const out = this.toAll({ type: "desync", seq: m.seq, hashes });
    if (s.phase !== "finished") out.push(...this.abort("desync"));
    return out;
  }

  private decision(conn: string, site: string, m: Frame): Out[] {
    const s = this.s;
    if (site !== s.host) return [this.rejected(conn, "decision", "only the host can decide")];
    if (s.phase !== "paused" || !s.decisionSent) return [this.rejected(conn, "decision", "there is nothing to decide")];
    if (m.choice === "abort") return this.abort();
    const dropped = this.droppedSites();
    const lost = new Set(dropped.map((d) => d.site));
    const gone = s.order.filter((p) => s.active.includes(p) && lost.has(s.owners[p]));
    const wasCurrent = s.current !== null && gone.includes(s.current);
    const currentIdx = s.current ? s.order.indexOf(s.current) : 0;
    s.eliminated.push(...gone);
    s.active = s.active.filter((p) => !gone.includes(p));
    for (const d of dropped) {
      s.sites[d.site].left = true;
      s.sites[d.site].droppedAt = null;
    }
    let next: string | null = s.current;
    if (wasCurrent) {
      next = null;
      for (let i = 1; i <= s.order.length && next === null; i++) {
        const cand = s.order[(currentIdx + i) % s.order.length];
        if (s.active.includes(cand)) next = cand;
      }
    }
    s.rejoinDeadline = null;
    s.decisionSent = false;
    if (s.active.length <= 1) {
      s.current = null;
      const out = this.toAll({ type: "site_dropped", sites: dropped, next_player: null });
      return [...out, ...this.finish(s.active[0] ?? null)];
    }
    s.current = next;
    s.phase = "playing";
    return this.toAll({ type: "site_dropped", sites: dropped, next_player: next });
  }

  private leave(conn: string, site: string): Out[] {
    const s = this.s;
    const x = s.sites[site];
    const out: Out[] = [{ to: conn, close: 1000 }];
    delete s.conns[conn];
    x.connection = null;
    if (s.phase === "lobby") {
      if (site === s.host) return [...out, ...this.abort()];
      delete s.sites[site];
      return [...out, ...this.lobbyFrames()];
    }
    if (s.phase === "playing" || s.phase === "paused") {
      x.left = true;
      x.droppedAt = this.deps.now();
      s.phase = "paused";
      s.rejoinDeadline = this.deps.now();
      if (site === s.host) return [...out, ...this.abort()];
      return [...out, ...this.toAll({ type: "paused", reason: "disconnect", site, rejoin_until: s.rejoinDeadline })];
    }
    return out;
  }

  // ── helpers ──────────────────────────────────────────────────────────────────

  private async addSite(conn: string, name: string): Promise<string> {
    const token = this.deps.randomHex(16);
    this.s.sites[name] = { name, tokenHash: await sha256(token), players: [], connection: conn, left: false, droppedAt: null };
    this.s.conns[conn] = name;
    return token;
  }

  private async passwordOk(password: string): Promise<boolean> {
    const { passwordSalt, passwordHash } = this.s;
    return !!passwordSalt && !!passwordHash && sameText(passwordHash, await pbkdf2(password, passwordSalt));
  }

  private droppedSites(): { site: string; players: string[] }[] {
    const s = this.s;
    return Object.values(s.sites)
      .filter((x) => (x.left ? x.droppedAt !== null : x.connection === null))
      .map((x) => ({ site: x.name, players: s.order.filter((p) => s.owners[p] === x.name && s.active.includes(p)) }));
  }

  private startedFrame(): Frame {
    const s = this.s;
    return { type: "started", match_id: s.matchId, lives: s.lives, order: s.order, owners: s.owners };
  }

  private welcome(conn: string, site: string, token: string, host: boolean): Out {
    return { to: conn, frame: { type: "welcome", code: this.s.code, site, token, host, state: this.s.phase } };
  }

  private lobbyFrames(): Out[] {
    const s = this.s;
    const sites = Object.values(s.sites).map((x) => ({ site: x.name, players: x.players, connected: x.connection !== null }));
    return this.toAll({ type: "lobby", host: s.host, sites, lives: s.lives, order: s.order });
  }

  private placements(winner: string | null): { player: string; placement: number }[] {
    const ranked = [...(winner ? [winner] : []), ...[...this.s.eliminated].reverse()];
    return ranked.map((player, i) => ({ player, placement: i + 1 }));
  }

  private finish(winner: string | null): Out[] {
    const s = this.s;
    s.phase = "finished";
    s.endedAt = this.deps.now();
    return this.toAll({ type: "ended", reason: "finished", placements: this.placements(winner) });
  }

  private abort(reason: "aborted" | "desync" = "aborted"): Out[] {
    const s = this.s;
    s.phase = "aborted";
    s.endedAt = this.deps.now();
    const out = this.toAll({ type: "ended", reason, placements: [] });
    return out.map((o) => ({ ...o, close: CLOSE.OVER }));
  }

  private toAll(frame: Frame, exceptSite?: string): Out[] {
    return Object.values(this.s.sites)
      .filter((x) => x.connection !== null && x.name !== exceptSite)
      .map((x) => ({ to: x.connection as string, frame }));
  }

  private fail(conn: string, code: number, message: string): Out {
    return { to: conn, frame: { type: "error", code, message }, close: code };
  }

  private failAuth(conn: string, message: string): Out {
    const s = this.s;
    s.failedHellos++;
    if (s.failedHellos >= LIMITS.MAX_FAILED_HELLOS) s.lockedUntil = this.deps.now() + LIMITS.LOCK_MS;
    return this.fail(conn, CLOSE.UNAUTHORIZED, message);
  }

  private rejected(conn: string, forType: string, reason: string): Out {
    return { to: conn, frame: { type: "rejected", for: forType, reason } };
  }
}
