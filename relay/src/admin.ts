// The admin of the circle: JSON routes under /admin for the page in Breakfast (there is no web page here). One login, one
// password: the Worker secret ADMIN_PASSWORD_HASH holds its salted hash (written by `npm run admin-password`), the answer of a
// login is a token of about one hour signed with the secret ADMIN_TOKEN_KEY and sent as `Authorization: Bearer <token>`. The
// page runs in a browser on any installation, so the routes allow any origin; there are no cookies, the token is the only door.

import { b64urlEncode, Limiter, LocationEnv, sha256Hex } from "./locations";
import { Fetcher, readUsage, UsageEnv } from "./usage";

export const ADMIN_LIMITS = {
  TOKEN_TTL_MS: 3_600_000,
  LOGIN: { limit: 5, windowMs: 15 * 60_000 },
  BODY_BYTES: 8192,
  PASSWORD_MIN: 12,
  RECORDS_SHOWN: 50,
  EVENTS_SHOWN: 50,
};

export interface AdminEnv extends LocationEnv, UsageEnv {
  ADMIN_PASSWORD_HASH?: string;
  ADMIN_TOKEN_KEY?: string;
}

const CORS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
  "access-control-max-age": "86400",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...CORS } });
const randomId = () => [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
const LOCATION_ID = /^[0-9a-f]{32}$/;
const NAME = /^[^\p{C}]{1,40}$/u;

// ── password and token ─────────────────────────────────────────────────────────────────────

/** `sha256$<salt hex>$<hash hex>`: the stored form of the password. The password comes from a password manager and is long
 *  (the script that writes it refuses short ones); the Worker cannot afford a slow hash on the free plan (10 ms of CPU). */
export async function passwordHash(password: string, saltHex: string): Promise<string> {
  return `sha256$${saltHex}$${await sha256Hex(`${saltHex}:${password}`)}`;
}

export function sameText(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function verifyPassword(stored: string, password: string): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 3 || parts[0] !== "sha256" || !/^[0-9a-f]{16,64}$/.test(parts[1])) return false;
  return sameText(await passwordHash(password, parts[1]), stored);
}

async function hmac(key: string, message: string): Promise<string> {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64urlEncode(new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(message))));
}

export async function makeToken(key: string, expiresAt: number): Promise<string> {
  return `${expiresAt}.${await hmac(key, `admin.${expiresAt}`)}`;
}

export async function tokenOk(key: string, token: string, now: number): Promise<boolean> {
  const m = /^(\d{10,16})\.([A-Za-z0-9_-]{43})$/.exec(token);
  if (!m || Number(m[1]) < now) return false;
  return sameText(m[2], await hmac(key, `admin.${m[1]}`));
}

async function readBody(request: Request): Promise<Record<string, unknown> | Response> {
  const raw = await request.text();
  if (raw.length > ADMIN_LIMITS.BODY_BYTES) return json({ error: "too large" }, 413);
  if (raw === "") return {};
  try {
    const data = JSON.parse(raw);
    if (typeof data !== "object" || data === null || Array.isArray(data)) return json({ error: "not an object" }, 400);
    return data;
  } catch {
    return json({ error: "not JSON" }, 400);
  }
}

const parse = <T>(text: string, fallback: T): T => { try { return JSON.parse(text) as T; } catch { return fallback; } };

/** The routes of the admin; null when the request is none of them. */
export async function handleAdmin(request: Request, env: AdminEnv, limited: Limiter, now = Date.now(), fetcher: Fetcher = fetch): Promise<Response | null> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (!path.startsWith("/admin/")) return null;
  const method = request.method;
  if (method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (!env.ADMIN_PASSWORD_HASH || !env.ADMIN_TOKEN_KEY || !env.DB) return json({ error: "the admin is not set up here" }, 503);
  const db = env.DB;

  if (method === "POST" && path === "/admin/login") {
    if (await limited("admin-login", ADMIN_LIMITS.LOGIN)) return json({ error: "too many attempts, try again later" }, 429);
    const body = await readBody(request);
    if (body instanceof Response) return body;
    if (typeof body.password !== "string" || !(await verifyPassword(env.ADMIN_PASSWORD_HASH, body.password))) return json({ error: "wrong password" }, 401);
    const expiresAt = now + ADMIN_LIMITS.TOKEN_TTL_MS;
    return json({ token: await makeToken(env.ADMIN_TOKEN_KEY, expiresAt), expires_at: expiresAt });
  }

  const auth = request.headers.get("authorization") ?? "";
  if (!auth.startsWith("Bearer ") || !(await tokenOk(env.ADMIN_TOKEN_KEY, auth.slice(7), now))) return json({ error: "log in first" }, 401);

  const body = method === "GET" ? {} : await readBody(request);
  if (body instanceof Response) return body;
  const site = path.match(/^\/admin\/sites\/([0-9a-f]{32})\/(approve|remove|refetch)$/);
  const player = path.match(/^\/admin\/players\/([0-9a-f]{32})$/);

  if (method === "GET" && path === "/admin/sites") {
    const rows = await db.prepare(
      "SELECT l.id, l.name, l.created_at, s.approved, s.approved_at, s.last_seen, s.version, s.players, s.state, s.refetch " +
      "FROM locations l LEFT JOIN circle_sites s ON s.location_id = l.id ORDER BY l.name").all<Record<string, any>>();
    return json({ sites: rows.results.map((r) => ({
      id: r.id, name: r.name, registered_at: r.created_at, approved: r.approved === 1, approved_at: r.approved_at, last_seen: r.last_seen,
      version: r.version, refetch: r.refetch ?? 0, players: parse<string[]>(r.players ?? "[]", []), state: parse<Record<string, unknown>>(r.state ?? "{}", {}) })) });
  }

  if (method === "POST" && site) {
    const [, id, action] = site;
    if (!(await db.prepare("SELECT id FROM locations WHERE id = ?").bind(id).first())) return json({ error: "unknown site" }, 404);
    if (action === "refetch") {
      const changed = await db.prepare("UPDATE circle_sites SET refetch = refetch + 1 WHERE location_id = ? AND approved = 1").bind(id).run();
      if (!changed.meta.changes) return json({ error: "this site is not approved" }, 409);
      return json({ ok: true });
    }
    await db.prepare(
      "INSERT INTO circle_sites (location_id, approved, approved_at) VALUES (?1, ?2, ?3) ON CONFLICT(location_id) DO UPDATE SET approved = ?2, approved_at = ?3")
      .bind(id, action === "approve" ? 1 : 0, action === "approve" ? now : null).run();
    return json({ ok: true, approved: action === "approve" });
  }

  if (method === "GET" && path === "/admin/players") {
    const players = await db.prepare("SELECT id, name, created_at FROM circle_players ORDER BY name").all<{ id: string; name: string; created_at: number }>();
    const mappings = await db.prepare("SELECT location_id, local_name, player_id FROM circle_mappings ORDER BY location_id, local_name").all<{ location_id: string; local_name: string; player_id: string }>();
    const rules = await db.prepare("SELECT player_id, location_id FROM circle_rules").all<{ player_id: string; location_id: string }>();
    return json({ players: players.results.map((p) => ({
      ...p, mappings: mappings.results.filter((m) => m.player_id === p.id).map((m) => ({ location_id: m.location_id, local_name: m.local_name })),
      sites: rules.results.filter((r) => r.player_id === p.id).map((r) => r.location_id) })) });
  }

  if (method === "POST" && path === "/admin/players") {
    const name = typeof body.name === "string" ? body.name.trim() : "";
    if (!NAME.test(name)) return json({ error: "bad name" }, 400);
    if (await db.prepare("SELECT id FROM circle_players WHERE lower(name) = lower(?)").bind(name).first()) return json({ error: "that player exists already" }, 409);
    const id = randomId();
    await db.prepare("INSERT INTO circle_players (id, name, created_at) VALUES (?, ?, ?)").bind(id, name, now).run();
    return json({ id, name }, 201);
  }

  if (method === "DELETE" && player) {
    await db.batch([
      db.prepare("DELETE FROM circle_rules WHERE player_id = ?").bind(player[1]),
      db.prepare("DELETE FROM circle_mappings WHERE player_id = ?").bind(player[1]),
      db.prepare("DELETE FROM circle_players WHERE id = ?").bind(player[1]),
    ]);
    return json({ ok: true });
  }

  if (method === "PUT" && path === "/admin/mappings") {
    const { location_id: location, local_name: localName, player_id: playerId } = body;
    if (typeof location !== "string" || !LOCATION_ID.test(location) || typeof localName !== "string" || !NAME.test(localName.trim())) return json({ error: "bad mapping" }, 400);
    const name = localName.trim().toLowerCase();
    if (playerId === null) {
      await db.prepare("DELETE FROM circle_mappings WHERE location_id = ? AND local_name = ?").bind(location, name).run();
      return json({ ok: true });
    }
    if (typeof playerId !== "string" || !(await db.prepare("SELECT id FROM circle_players WHERE id = ?").bind(playerId).first())) return json({ error: "unknown player" }, 404);
    if (!(await db.prepare("SELECT id FROM locations WHERE id = ?").bind(location).first())) return json({ error: "unknown site" }, 404);
    await db.prepare("INSERT INTO circle_mappings (location_id, local_name, player_id) VALUES (?1, ?2, ?3) ON CONFLICT(location_id, local_name) DO UPDATE SET player_id = ?3").bind(location, name, playerId).run();
    return json({ ok: true });
  }

  if (method === "PUT" && path === "/admin/rules") {
    const { player_id: playerId, location_ids: sites } = body;
    if (typeof playerId !== "string" || !Array.isArray(sites) || !sites.every((s) => typeof s === "string" && LOCATION_ID.test(s))) return json({ error: "bad rule" }, 400);
    if (!(await db.prepare("SELECT id FROM circle_players WHERE id = ?").bind(playerId).first())) return json({ error: "unknown player" }, 404);
    await db.batch([
      db.prepare("DELETE FROM circle_rules WHERE player_id = ?").bind(playerId),
      ...[...new Set(sites as string[])].map((s) => db.prepare("INSERT INTO circle_rules (player_id, location_id) VALUES (?, ?)").bind(playerId, s)),
    ]);
    return json({ ok: true });
  }

  if (method === "GET" && path === "/admin/sync") {
    const counts = await db.prepare("SELECT origin, COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes, MAX(created_at) AS last FROM circle_records GROUP BY origin").all<{ origin: string; n: number; bytes: number; last: number }>();
    const sites = await db.prepare(
      "SELECT s.location_id, l.name, s.last_seen, s.version, s.state FROM circle_sites s LEFT JOIN locations l ON l.id = s.location_id WHERE s.approved = 1 ORDER BY l.name").all<Record<string, any>>();
    const totals = await db.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM circle_records").first<{ n: number; bytes: number }>();
    return json({
      totals,
      sites: sites.results.map((s) => ({ id: s.location_id, name: s.name, last_seen: s.last_seen, version: s.version, state: parse(s.state ?? "{}", {}),
        records_sent: counts.results.find((c) => c.origin === s.location_id) ?? { n: 0, bytes: 0, last: null } })),
    });
  }

  if (method === "GET" && path === "/admin/records") {
    const names = await db.prepare("SELECT id, name FROM circle_players").all<{ id: string; name: string }>();
    const rows = await db.prepare(
      "SELECT r.seq, r.match_id, r.revision, r.origin, l.name AS origin_name, r.game_mode, r.deleted, r.size, r.players, r.created_at " +
      "FROM circle_records r LEFT JOIN locations l ON l.id = r.origin ORDER BY r.seq DESC LIMIT ?").bind(ADMIN_LIMITS.RECORDS_SHOWN).all<Record<string, any>>();
    return json({ records: rows.results.map((r) => ({ seq: r.seq, match_id: r.match_id, revision: r.revision, origin: { id: r.origin, name: r.origin_name },
      game_mode: r.game_mode, deleted: r.deleted === 1, size: r.size, created_at: r.created_at,
      players: parse<string[]>(r.players, []).map((id) => names.results.find((n) => n.id === id)?.name ?? id) })) });
  }

  if (method === "GET" && path === "/admin/reports") {
    const days = Math.min(Math.max(Number(url.searchParams.get("days") ?? "30"), 1), 365);
    const since = new Date(now - days * 86_400_000).toISOString().replace(/\.\d+Z$/, "Z");
    const byType = await db.prepare("SELECT type, COUNT(*) AS n FROM events WHERE received_at >= ? GROUP BY type ORDER BY n DESC").bind(since).all<{ type: string; n: number }>();
    const installs = await db.prepare("SELECT COUNT(DISTINCT install_id) AS n FROM events WHERE received_at >= ?").bind(since).first<{ n: number }>();
    const versions = await db.prepare("SELECT version, COUNT(DISTINCT install_id) AS installs FROM events WHERE received_at >= ? GROUP BY version ORDER BY installs DESC").bind(since).all<{ version: string; installs: number }>();
    const platforms = await db.prepare("SELECT platform, COUNT(DISTINCT install_id) AS installs FROM events WHERE received_at >= ? GROUP BY platform ORDER BY installs DESC").bind(since).all<{ platform: string; installs: number }>();
    const recent = await db.prepare("SELECT id, received_at, install_id, version, platform, type, ts, data FROM events WHERE received_at >= ? ORDER BY id DESC LIMIT ?").bind(since, ADMIN_LIMITS.EVENTS_SHOWN).all<Record<string, any>>();
    return json({ days, installs: installs?.n ?? 0, by_type: byType.results, versions: versions.results, platforms: platforms.results,
      recent: recent.results.map((e) => ({ ...e, data: parse(e.data, {}) })) });
  }

  if (method === "GET" && path === "/admin/usage") return json(await readUsage(env, now, fetcher));

  return json({ error: "unknown admin route" }, 404);
}
