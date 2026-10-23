// The circle: the match records of a group of friends travel through the relay as plain JSON. A site (a registered
// location the admin approved) puts the records of its finished matches, the relay says which sites get a record
// (those in the rule of a circle player who took part) and a site lists and fetches what is meant for it
// (see PROTOCOL.md, "Circle"). Requests are signed with the key of the location as for the other routes.

import { authenticate, Limiter, LocationEnv, sha256Hex } from "./locations";

export const CIRCLE_LIMITS = {
  BODY_BYTES: 300_000,
  RECORD_BYTES: 256 * 1024,
  RECORDS_PER_SITE_DAY: 500,
  RECORDS_TOTAL: 20_000,
  BYTES_TOTAL: 2 * 1024 * 1024 * 1024,
  PLAYERS_PER_SITE: 200,
  STATE_BYTES: 4096,
  LIST_MAX: 100,
  PARTICIPANTS: 24,
  PROFILE_PLAYERS: 50,
  VOICE_VARIANTS: 8,
  VOICE_TEXT: 100,
};

export interface CircleEnv extends LocationEnv {
  RECORDS?: R2Bucket;
  SHARING?: string;                    // "off" switches the sharing routes off
}

const MODES = ["X01", "Elimination"];
const MATCH_ID = /^[A-Za-z0-9._:-]{1,80}$/;
const COLOR = /^#[0-9a-f]{6}$/;
const PACK = /^[a-z0-9_-]{1,30}$/;
const NAME = /^[^\p{C}]{1,40}$/u;

const READ_LIMIT = { limit: 600, windowMs: 3_600_000 };
const WRITE_LIMIT = { limit: 600, windowMs: 3_600_000 };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const tooMany = () => json({ error: "too many requests" }, 429);
const objectKey = (matchId: string) => `circle/${matchId}`;

async function readBody(request: Request): Promise<{ raw: string; data: Record<string, unknown> } | Response> {
  const raw = await request.text();
  if (raw.length > CIRCLE_LIMITS.BODY_BYTES) return json({ error: "too large" }, 413);
  if (raw === "") return { raw, data: {} };
  try {
    const data = JSON.parse(raw);
    if (typeof data !== "object" || data === null || Array.isArray(data)) return json({ error: "not an object" }, 400);
    return { raw, data };
  } catch {
    return json({ error: "not JSON" }, 400);
  }
}

/** The circle players that took part, as the circle knows them: a local player through the mapping of the site that pushed the
 *  record, a guest of another site (`origin` is the name of that site) through the mapping of that site. */
export async function resolvePlayers(db: D1Database, originId: string, participants: { name: string; origin?: string }[]): Promise<string[]> {
  const ids = new Set<string>();
  for (const p of participants) {
    let location: string | undefined = originId;
    if (p.origin) {
      const row = await db.prepare("SELECT id FROM locations WHERE lower(name) = lower(?)").bind(p.origin).first<{ id: string }>();
      location = row?.id;
    }
    if (!location) continue;
    const mapped = await db.prepare("SELECT player_id FROM circle_mappings WHERE location_id = ? AND local_name = ?").bind(location, p.name.toLowerCase()).first<{ player_id: string }>();
    if (mapped) ids.add(mapped.player_id);
  }
  return [...ids];
}

/** The records meant for a site: not played there, with a circle player in them whose rule names the site. */
const FOR_SITE =
  "r.origin != ?1 AND EXISTS (SELECT 1 FROM json_each(r.players) j JOIN circle_rules ru ON ru.player_id = j.value AND ru.location_id = ?1)";

/** The routes of the circle for the sites; null when the request is none of them. */
export async function handleCircle(request: Request, env: CircleEnv, limited: Limiter, now = Date.now()): Promise<Response | null> {
  const path = new URL(request.url).pathname;
  const method = request.method;
  const record = path.match(/^\/circle\/records\/([^/]+)\/(\d{1,7})$/);
  const one = path.match(/^\/circle\/records\/([^/]+)$/);
  const route =
    method === "PUT" && path === "/circle/state" ? "state"
    : method === "PUT" && path === "/circle/profile" ? "profile"
    : method === "GET" && path === "/circle/config" ? "config"
    : method === "PUT" && record ? "put"
    : method === "GET" && path === "/circle/records" ? "list"
    : method === "GET" && one ? "fetch"
    : null;
  if (!route) return null;
  if (env.SHARING === "off") return json({ error: "sharing is switched off" }, 503);
  if (!env.DB || !env.RECORDS) return json({ error: "sharing is not set up here" }, 503);
  const db = env.DB;

  const body = await readBody(request);
  if (body instanceof Response) return body;
  const who = await authenticate(request, env, body.raw, now);
  if (who instanceof Response) return who;
  const site = who.id;
  const row = await db.prepare("SELECT approved FROM circle_sites WHERE location_id = ?").bind(site).first<{ approved: number }>();
  const approved = row?.approved === 1;

  if (route === "state") {
    if (await limited("circle-write", WRITE_LIMIT, site)) return tooMany();
    const { version, players, state } = body.data;
    const names = Array.isArray(players) ? players : null;
    if (names === null || names.length > CIRCLE_LIMITS.PLAYERS_PER_SITE || !names.every((n) => typeof n === "string" && NAME.test(n))) return json({ error: "players must be a list of names" }, 400);
    if (version !== undefined && (typeof version !== "string" || !/^[0-9A-Za-z.+-]{1,20}$/.test(version))) return json({ error: "bad version" }, 400);
    const stateText = JSON.stringify(state ?? {});
    if (typeof (state ?? {}) !== "object" || Array.isArray(state) || stateText.length > CIRCLE_LIMITS.STATE_BYTES) return json({ error: "bad state" }, 400);
    await db.prepare(
      "INSERT INTO circle_sites (location_id, last_seen, version, players, state) VALUES (?1, ?2, ?3, ?4, ?5) " +
      "ON CONFLICT(location_id) DO UPDATE SET last_seen = ?2, version = ?3, players = ?4, state = ?5")
      .bind(site, now, version ?? null, JSON.stringify([...new Set(names.map((n: string) => n.toLowerCase()))]), stateText).run();
    return json({ approved });
  }

  if (!approved) return json({ error: "this site is not approved by the admin yet" }, 403);

  if (route === "config") {
    if (await limited("circle-read", READ_LIMIT, site)) return tooMany();
    const players = await db.prepare("SELECT id, name FROM circle_players ORDER BY name").all<{ id: string; name: string }>();
    const rules = await db.prepare(
      "SELECT ru.player_id, l.id AS location_id, l.name AS location_name FROM circle_rules ru JOIN locations l ON l.id = ru.location_id").all<{ player_id: string; location_id: string; location_name: string }>();
    const mappings = await db.prepare("SELECT local_name, player_id FROM circle_mappings WHERE location_id = ? ORDER BY local_name").bind(site).all<{ local_name: string; player_id: string }>();
    const all = await db.prepare(
      "SELECT m.location_id, l.name AS location_name, m.local_name, m.player_id FROM circle_mappings m JOIN locations l ON l.id = m.location_id ORDER BY l.name, m.local_name")
      .all<{ location_id: string; location_name: string; local_name: string; player_id: string }>();
    const mine = await db.prepare("SELECT refetch FROM circle_sites WHERE location_id = ?").bind(site).first<{ refetch: number }>();
    const profiles = await db.prepare(
      "SELECT f.player_id, f.field, f.value, f.updated_at FROM circle_profiles f WHERE f.player_id IN (SELECT player_id FROM circle_mappings WHERE location_id = ?)")
      .bind(site).all<{ player_id: string; field: string; value: string | null; updated_at: number }>();
    return json({
      approved: true,
      refetch: mine?.refetch ?? 0,
      profiles: profiles.results.map((f) => ({ player_id: f.player_id, field: f.field, value: f.value === null ? null : JSON.parse(f.value), at: f.updated_at })),
      site_mappings: all.results,
      circle_players: players.results.map((p) => ({ ...p, sites: rules.results.filter((r) => r.player_id === p.id).map((r) => ({ id: r.location_id, name: r.location_name })) })),
      mappings: mappings.results,
    });
  }

  if (route === "profile") {
    if (await limited("circle-write", WRITE_LIMIT, site)) return tooMany();
    const players = body.data.players;
    if (!Array.isArray(players) || players.length < 1 || players.length > CIRCLE_LIMITS.PROFILE_PLAYERS) return json({ error: "players must be a list" }, 400);
    const changes: { playerId: string; field: string; value: string | null }[] = [];
    for (const entry of players) {
      if (typeof entry !== "object" || entry === null || typeof entry.name !== "string" || !NAME.test(entry.name)) return json({ error: "a player needs a name" }, 400);
      const mapped = await db.prepare("SELECT player_id FROM circle_mappings WHERE location_id = ? AND local_name = ?").bind(site, entry.name.toLowerCase()).first<{ player_id: string }>();
      if (!mapped) continue;                                  // not a player of the circle (the admin may map him later)
      if (entry.color !== undefined) {
        if (entry.color !== null && !(typeof entry.color === "string" && COLOR.test(entry.color))) return json({ error: "color must look like #rrggbb" }, 400);
        changes.push({ playerId: mapped.player_id, field: "color", value: entry.color === null ? null : JSON.stringify(entry.color) });
      }
      if (entry.voice !== undefined) {
        if (typeof entry.voice !== "object" || entry.voice === null || Array.isArray(entry.voice)) return json({ error: "voice must map packs to entries" }, 400);
        for (const [pack, voice] of Object.entries(entry.voice as Record<string, unknown>)) {
          if (!PACK.test(pack)) return json({ error: "bad voice pack name" }, 400);
          if (voice === null) { changes.push({ playerId: mapped.player_id, field: `voice:${pack}`, value: null }); continue; }
          const variants = (voice as { variants?: unknown })?.variants;
          if (typeof voice !== "object" || !Array.isArray(variants) || variants.length < 1 || variants.length > CIRCLE_LIMITS.VOICE_VARIANTS ||
              !variants.every((v) => typeof v === "string" && v.length >= 1 && v.length <= CIRCLE_LIMITS.VOICE_TEXT)) {
            return json({ error: "a voice entry needs 1 to 8 variants" }, 400);
          }
          changes.push({ playerId: mapped.player_id, field: `voice:${pack}`, value: JSON.stringify({ variants }) });
        }
      }
    }
    let updated = 0;
    for (const c of changes) {
      const current = await db.prepare("SELECT value FROM circle_profiles WHERE player_id = ? AND field = ?").bind(c.playerId, c.field).first<{ value: string | null }>();
      if (current && current.value === c.value) continue;     // nothing changed: keep the time of the change that is there
      await db.prepare(
        "INSERT INTO circle_profiles (player_id, field, value, updated_at) VALUES (?1, ?2, ?3, ?4) " +
        "ON CONFLICT(player_id, field) DO UPDATE SET value = ?3, updated_at = ?4").bind(c.playerId, c.field, c.value, now).run();
      updated++;
    }
    return json({ updated });
  }

  if (route === "list") {
    if (await limited("circle-read", READ_LIMIT, site)) return tooMany();
    const url = new URL(request.url);
    const since = Number(url.searchParams.get("since") ?? "0");
    const limit = Math.min(Number(url.searchParams.get("limit") ?? CIRCLE_LIMITS.LIST_MAX), CIRCLE_LIMITS.LIST_MAX);
    if (!Number.isInteger(since) || since < 0 || !Number.isInteger(limit) || limit < 1) return json({ error: "bad cursor" }, 400);
    const rows = await db.prepare(
      `SELECT r.seq, r.match_id, r.revision, r.game_mode, r.deleted, r.size, r.hash, r.created_at, r.origin, l.name AS origin_name ` +
      `FROM circle_records r LEFT JOIN locations l ON l.id = r.origin WHERE r.seq > ?2 AND ${FOR_SITE} ORDER BY r.seq LIMIT ?3`)
      .bind(site, since, limit).all<{ seq: number; match_id: string; revision: number; game_mode: string; deleted: number; size: number; hash: string; created_at: number; origin: string; origin_name: string | null }>();
    const records = rows.results.map((r) => ({ seq: r.seq, match_id: r.match_id, revision: r.revision, game_mode: r.game_mode, deleted: r.deleted === 1,
      size: r.size, hash: r.hash, created_at: r.created_at, origin: { id: r.origin, name: r.origin_name } }));
    return json({ records, next: records.length ? records[records.length - 1].seq : since });
  }

  if (route === "fetch") {
    if (await limited("circle-read", READ_LIMIT, site)) return tooMany();
    const matchId = decodeURIComponent(one![1]);
    if (!MATCH_ID.test(matchId)) return json({ error: "bad match id" }, 400);
    const r = await db.prepare(
      `SELECT r.seq, r.revision, r.game_mode, r.deleted, r.size, r.hash, r.created_at, r.origin FROM circle_records r WHERE r.match_id = ?2 AND ${FOR_SITE}`)
      .bind(site, matchId).first<{ seq: number; revision: number; game_mode: string; deleted: number; size: number; hash: string; created_at: number; origin: string }>();
    if (!r) return json({ error: "unknown record" }, 404);
    const object = await env.RECORDS.get(objectKey(matchId));
    if (!object) return json({ error: "unknown record" }, 404);
    return json({ seq: r.seq, match_id: matchId, revision: r.revision, game_mode: r.game_mode, deleted: r.deleted === 1, size: r.size, hash: r.hash,
      created_at: r.created_at, origin: { id: r.origin }, record: JSON.parse(await object.text()) });
  }

  // put
  if (await limited("circle-write", WRITE_LIMIT, site)) return tooMany();
  const matchId = decodeURIComponent(record![1]);
  const revision = Number(record![2]);
  if (!MATCH_ID.test(matchId) || revision < 1) return json({ error: "bad match id or revision" }, 400);
  const { game_mode: mode, deleted, participants, record: doc } = body.data;
  if (typeof mode !== "string" || !MODES.includes(mode)) return json({ error: "bad game_mode" }, 400);
  if (typeof deleted !== "boolean") return json({ error: "deleted must be true or false" }, 400);
  if (!Array.isArray(participants) || participants.length < 1 || participants.length > CIRCLE_LIMITS.PARTICIPANTS ||
      !participants.every((p) => typeof p === "object" && p !== null && typeof p.name === "string" && NAME.test(p.name) && (p.origin === undefined || (typeof p.origin === "string" && NAME.test(p.origin))))) {
    return json({ error: "participants must list {name, origin?}" }, 400);
  }
  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) return json({ error: "record must be an object" }, 400);
  const d = doc as Record<string, unknown>;
  if (d.match_id !== matchId || d.revision !== revision || d.deleted !== deleted || d.game_mode !== mode) return json({ error: "the record does not match its address" }, 400);
  const text = JSON.stringify(doc);
  if (text.length > CIRCLE_LIMITS.RECORD_BYTES) return json({ error: "the record is too large" }, 413);
  const hash = await sha256Hex(text);

  const existing = await db.prepare("SELECT revision, origin, hash, seq FROM circle_records WHERE match_id = ?").bind(matchId).first<{ revision: number; origin: string; hash: string; seq: number }>();
  if (existing && existing.origin !== site) return json({ error: "that match belongs to another site" }, 403);
  if (existing && existing.revision === revision) {
    if (existing.hash !== hash) return json({ error: "that revision exists with other content" }, 409);
    return json({ seq: existing.seq, size: text.length, hash });
  }
  if (existing && existing.revision > revision) return json({ error: "a newer revision exists" }, 409);

  const players = await resolvePlayers(db, site, participants as { name: string; origin?: string }[]);
  if (!players.length) return json({ error: "no player of this match is in the circle" }, 422);
  const day = await db.prepare("SELECT COUNT(*) AS n FROM circle_records WHERE origin = ? AND created_at >= ?").bind(site, now - 24 * 3_600_000).first<{ n: number }>();
  if ((day?.n ?? 0) >= CIRCLE_LIMITS.RECORDS_PER_SITE_DAY) return json({ error: "too many records today" }, 429);
  const used = await db.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM circle_records").first<{ n: number; bytes: number }>();
  if ((used?.n ?? 0) >= CIRCLE_LIMITS.RECORDS_TOTAL || (used?.bytes ?? 0) + text.length > CIRCLE_LIMITS.BYTES_TOTAL) return json({ error: "the circle store is full" }, 413);

  await env.RECORDS.put(objectKey(matchId), text);
  const statements = [
    db.prepare("DELETE FROM circle_records WHERE match_id = ?").bind(matchId),
    db.prepare("INSERT INTO circle_records (match_id, revision, origin, game_mode, deleted, size, hash, players, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(matchId, revision, site, mode, deleted ? 1 : 0, text.length, hash, JSON.stringify(players), now),
  ];
  const results = await db.batch(statements);
  return json({ seq: results[1].meta.last_row_id, size: text.length, hash }, 201);
}

/** Forget a location that signs off: its place in the circle goes, the records it sent stay. */
export async function dropSite(db: D1Database, locationId: string): Promise<void> {
  await db.batch([
    db.prepare("DELETE FROM circle_sites WHERE location_id = ?").bind(locationId),
    db.prepare("DELETE FROM circle_mappings WHERE location_id = ?").bind(locationId),
    db.prepare("DELETE FROM circle_rules WHERE location_id = ?").bind(locationId),
  ]);
}
