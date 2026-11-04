// Scenes and achievement sounds in the circle: a site publishes them, the other approved sites take them over in their catch-up
// (see PROTOCOL.md, "Circle"). Sound files are stored once per hash; a scene or an achievement entry names its files by hash.
// Requests are signed as for the other circle routes.

import { authenticate, Limiter } from "./locations";
import { CircleEnv } from "./circle";

export const SHARED_LIMITS = {
  BODY_CHARS: 3_000_000,        // a sound travels as base64 in a JSON body
  SOUND_BYTES: 2 * 1024 * 1024,
  SOUNDS_TOTAL: 2_000,
  SOUND_BYTES_TOTAL: 1024 * 1024 * 1024,
  SCENE_BYTES: 256 * 1024,
  SCENES_PER_SITE: 200,
  SOUNDS_PER_SCENE: 100,
  ACHIEVEMENTS_PER_SITE: 150,
  FILES_PER_ACHIEVEMENT: 20,
  LIST_MAX: 100,
};

const SCENE_ID = /^[A-Za-z0-9_-]{8,40}$/;
const ACHIEVEMENT = /^[a-z0-9_]{1,60}$/;
const HASH = /^[0-9a-f]{64}$/;
const FILE = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\.mp3$/;
const SCENE_NAME = /^[^\p{C}]{1,80}$/u;

const READ_LIMIT = { limit: 600, windowMs: 3_600_000 };
const WRITE_LIMIT = { limit: 600, windowMs: 3_600_000 };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const tooMany = () => json({ error: "too many requests" }, 429);
const soundKey = (hash: string) => `sounds/${hash}`;

function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

function fromBase64(text: string): Uint8Array | null {
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(text)) return null;
  try {
    return Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
  } catch {
    return null;
  }
}

async function sha256Bytes(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const looksLikeMp3 = (b: Uint8Array) => b.length > 2 && ((b[0] === 0x49 && b[1] === 0x44 && b[2] === 0x33) || (b[0] === 0xff && (b[1] & 0xe0) === 0xe0));

/** `[{file, hash}]` with valid names and hashes, at most `max` entries; null when it is none. */
function fileList(value: unknown, max: number): { file: string; hash: string }[] | null {
  if (!Array.isArray(value) || value.length > max) return null;
  const out = [];
  for (const e of value) {
    if (typeof e !== "object" || e === null || typeof e.file !== "string" || typeof e.hash !== "string" || !FILE.test(e.file) || !HASH.test(e.hash)) return null;
    out.push({ file: e.file, hash: e.hash });
  }
  return out;
}

async function missingSounds(db: D1Database, files: { hash: string }[]): Promise<string[]> {
  const missing: string[] = [];
  for (const hash of new Set(files.map((f) => f.hash))) {
    if (!(await db.prepare("SELECT 1 AS x FROM circle_sounds WHERE hash = ?").bind(hash).first())) missing.push(hash);
  }
  return missing;
}

/** The routes for scenes, achievement sounds and their sound files; null when the request is none of them. */
export async function handleCircleShared(request: Request, env: CircleEnv, limited: Limiter, now = Date.now()): Promise<Response | null> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;
  const sound = path.match(/^\/circle\/sounds\/([0-9a-f]{64})$/);
  const scene = path.match(/^\/circle\/scenes\/([^/]+)$/);
  const achievement = path.match(/^\/circle\/achievement-sounds\/([^/]+)$/);
  const route =
    method === "PUT" && sound ? "put-sound"
    : method === "GET" && sound ? "get-sound"
    : method === "PUT" && scene ? "put-scene"
    : method === "GET" && path === "/circle/scenes" ? "list-scenes"
    : method === "PUT" && achievement ? "put-achievement"
    : method === "GET" && path === "/circle/achievement-sounds" ? "list-achievements"
    : null;
  if (!route) return null;
  if (env.SHARING === "off") return json({ error: "sharing is switched off" }, 503);
  if (!env.DB || !env.RECORDS) return json({ error: "sharing is not set up here" }, 503);
  const db = env.DB;

  const raw = await request.text();
  if (raw.length > SHARED_LIMITS.BODY_CHARS) return json({ error: "too large" }, 413);
  let data: Record<string, unknown> = {};
  if (raw !== "") {
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return json({ error: "not an object" }, 400);
      data = parsed;
    } catch {
      return json({ error: "not JSON" }, 400);
    }
  }
  const who = await authenticate(request, env, raw, now);
  if (who instanceof Response) return who;
  const site = who.id;
  const row = await db.prepare("SELECT approved FROM circle_sites WHERE location_id = ?").bind(site).first<{ approved: number }>();
  if (row?.approved !== 1) return json({ error: "this site is not approved by the admin yet" }, 403);

  const reading = route.startsWith("get") || route.startsWith("list");
  if (await limited(reading ? "circle-read" : "circle-write", reading ? READ_LIMIT : WRITE_LIMIT, site)) return tooMany();

  if (route === "put-sound") {
    const hash = sound![1];
    const text = data.data;
    const bytes = typeof text === "string" ? fromBase64(text) : null;
    if (!bytes) return json({ error: "data must be the file as base64" }, 400);
    if (bytes.length === 0 || bytes.length > SHARED_LIMITS.SOUND_BYTES) return json({ error: "a sound is 2 MB at most" }, 413);
    if (!looksLikeMp3(bytes)) return json({ error: "this does not look like an mp3 file" }, 400);
    if ((await sha256Bytes(bytes)) !== hash) return json({ error: "the hash does not match the file" }, 400);
    if (await db.prepare("SELECT 1 AS x FROM circle_sounds WHERE hash = ?").bind(hash).first()) return json({ hash, size: bytes.length });
    const used = await db.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM circle_sounds").first<{ n: number; bytes: number }>();
    if ((used?.n ?? 0) >= SHARED_LIMITS.SOUNDS_TOTAL || (used?.bytes ?? 0) + bytes.length > SHARED_LIMITS.SOUND_BYTES_TOTAL) return json({ error: "the sound store is full" }, 413);
    await env.RECORDS.put(soundKey(hash), bytes);
    await db.prepare("INSERT INTO circle_sounds (hash, size, origin, created_at) VALUES (?, ?, ?, ?)").bind(hash, bytes.length, site, now).run();
    return json({ hash, size: bytes.length }, 201);
  }

  if (route === "get-sound") {
    const hash = sound![1];
    if (!(await db.prepare("SELECT 1 AS x FROM circle_sounds WHERE hash = ?").bind(hash).first())) return json({ error: "unknown sound" }, 404);
    const object = await env.RECORDS.get(soundKey(hash));
    if (!object) return json({ error: "unknown sound" }, 404);
    return json({ hash, data: toBase64(new Uint8Array(await object.arrayBuffer())) });
  }

  const page = (name: string) => {
    const since = Number(url.searchParams.get("since") ?? 0);
    const limit = Math.min(Number(url.searchParams.get(name) ?? SHARED_LIMITS.LIST_MAX) || SHARED_LIMITS.LIST_MAX, SHARED_LIMITS.LIST_MAX);
    return { since: Number.isFinite(since) && since >= 0 ? since : 0, limit: limit < 1 ? SHARED_LIMITS.LIST_MAX : limit };
  };

  if (route === "list-scenes") {
    const { since, limit } = page("limit");
    const rows = await db.prepare(
      "SELECT s.seq, s.scene_id, s.origin, l.name AS origin_name, s.name, s.graph, s.sounds, s.deleted, s.updated_at " +
      "FROM circle_scenes s JOIN locations l ON l.id = s.origin WHERE s.seq > ? AND s.origin != ? ORDER BY s.seq LIMIT ?")
      .bind(since, site, limit).all<{ seq: number; scene_id: string; origin: string; origin_name: string; name: string; graph: string; sounds: string; deleted: number; updated_at: number }>();
    const scenes = rows.results.map((r) => ({
      seq: r.seq, scene_id: r.scene_id, origin: { id: r.origin, name: r.origin_name }, name: r.name, graph: JSON.parse(r.graph),
      sounds: JSON.parse(r.sounds), deleted: r.deleted === 1, updated_at: r.updated_at,
    }));
    return json({ scenes, next: scenes.length ? scenes[scenes.length - 1].seq : since });
  }

  if (route === "list-achievements") {
    const { since, limit } = page("limit");
    const rows = await db.prepare(
      "SELECT s.seq, s.achievement, s.origin, l.name AS origin_name, s.files, s.deleted, s.updated_at " +
      "FROM circle_achievement_sounds s JOIN locations l ON l.id = s.origin WHERE s.seq > ? AND s.origin != ? ORDER BY s.seq LIMIT ?")
      .bind(since, site, limit).all<{ seq: number; achievement: string; origin: string; origin_name: string; files: string; deleted: number; updated_at: number }>();
    const sounds = rows.results.map((r) => ({
      seq: r.seq, achievement: r.achievement, origin: { id: r.origin, name: r.origin_name }, files: JSON.parse(r.files),
      deleted: r.deleted === 1, updated_at: r.updated_at,
    }));
    return json({ sounds, next: sounds.length ? sounds[sounds.length - 1].seq : since });
  }

  if (route === "put-scene") {
    const sceneId = decodeURIComponent(scene![1]);
    if (!SCENE_ID.test(sceneId)) return json({ error: "bad scene id" }, 400);
    const deleted = data.deleted === true;
    if (data.deleted !== undefined && typeof data.deleted !== "boolean") return json({ error: "deleted must be true or false" }, 400);
    let name = "", graphText = "{}", files: { file: string; hash: string }[] = [];
    if (!deleted) {
      if (typeof data.name !== "string" || !SCENE_NAME.test(data.name)) return json({ error: "bad name" }, 400);
      if (typeof data.graph !== "object" || data.graph === null || Array.isArray(data.graph)) return json({ error: "graph must be an object" }, 400);
      graphText = JSON.stringify(data.graph);
      if (graphText.length > SHARED_LIMITS.SCENE_BYTES) return json({ error: "the scene is too large" }, 413);
      const list = fileList(data.sounds, SHARED_LIMITS.SOUNDS_PER_SCENE);
      if (!list) return json({ error: "sounds must list {file, hash}" }, 400);
      files = list;
      const missing = await missingSounds(db, files);
      if (missing.length) return json({ error: "upload the sounds first", missing }, 422);
      name = data.name;
    }
    const soundsText = JSON.stringify(files);
    const existing = await db.prepare("SELECT seq, name, graph, sounds, deleted FROM circle_scenes WHERE origin = ? AND scene_id = ?")
      .bind(site, sceneId).first<{ seq: number; name: string; graph: string; sounds: string; deleted: number }>();
    if (existing && existing.name === name && existing.graph === graphText && existing.sounds === soundsText && (existing.deleted === 1) === deleted) {
      return json({ seq: existing.seq });
    }
    if (!existing) {
      const mine = await db.prepare("SELECT COUNT(*) AS n FROM circle_scenes WHERE origin = ? AND deleted = 0").bind(site).first<{ n: number }>();
      if (!deleted && (mine?.n ?? 0) >= SHARED_LIMITS.SCENES_PER_SITE) return json({ error: "too many shared scenes" }, 429);
      if (deleted) return json({ seq: 0 });
    }
    const results = await db.batch([
      db.prepare("DELETE FROM circle_scenes WHERE origin = ? AND scene_id = ?").bind(site, sceneId),
      db.prepare("INSERT INTO circle_scenes (scene_id, origin, name, graph, sounds, deleted, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
        .bind(sceneId, site, name, graphText, soundsText, deleted ? 1 : 0, now),
    ]);
    return json({ seq: results[1].meta.last_row_id }, existing ? 200 : 201);
  }

  // put-achievement
  const id = decodeURIComponent(achievement![1]);
  if (!ACHIEVEMENT.test(id)) return json({ error: "bad achievement id" }, 400);
  if (data.deleted !== undefined && typeof data.deleted !== "boolean") return json({ error: "deleted must be true or false" }, 400);
  const deleted = data.deleted === true;
  let files: { file: string; hash: string }[] = [];
  if (!deleted) {
    const list = fileList(data.files, SHARED_LIMITS.FILES_PER_ACHIEVEMENT);
    if (!list || !list.length) return json({ error: "files must list {file, hash}" }, 400);
    files = list;
    const missing = await missingSounds(db, files);
    if (missing.length) return json({ error: "upload the sounds first", missing }, 422);
  }
  const filesText = JSON.stringify(files);
  const existing = await db.prepare("SELECT seq, files, deleted FROM circle_achievement_sounds WHERE origin = ? AND achievement = ?")
    .bind(site, id).first<{ seq: number; files: string; deleted: number }>();
  if (existing && existing.files === filesText && (existing.deleted === 1) === deleted) return json({ seq: existing.seq });
  if (!existing) {
    if (deleted) return json({ seq: 0 });
    const mine = await db.prepare("SELECT COUNT(*) AS n FROM circle_achievement_sounds WHERE origin = ? AND deleted = 0").bind(site).first<{ n: number }>();
    if ((mine?.n ?? 0) >= SHARED_LIMITS.ACHIEVEMENTS_PER_SITE) return json({ error: "too many shared achievement sounds" }, 429);
  }
  const results = await db.batch([
    db.prepare("DELETE FROM circle_achievement_sounds WHERE origin = ? AND achievement = ?").bind(site, id),
    db.prepare("INSERT INTO circle_achievement_sounds (achievement, origin, files, deleted, updated_at) VALUES (?, ?, ?, ?, ?)")
      .bind(id, site, filesText, deleted ? 1 : 0, now),
  ]);
  return json({ seq: results[1].meta.last_row_id }, existing ? 200 : 201);
}

