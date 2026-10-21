// Locations: installations registered at the relay, one-time invitations and the links between two
// locations (see PROTOCOL.md, "Locations"). Requests are signed with the Ed25519 key of the location.

export const LOCATION_LIMITS = {
  BODY_BYTES: 2048,
  NAME_MAX: 24,
  CLOCK_SKEW_S: 300,
  INVITATION_TTL_MS: 7 * 24 * 3600 * 1000,
  PENDING_INVITATIONS: 5,
  LINKS_PER_LOCATION: 50,
};

const LOCATION_ID = /^[0-9a-f]{32}$/;
const KEY = /^[A-Za-z0-9_-]{43}$/;
const SIGNATURE = /^[A-Za-z0-9_-]{86}$/;
const TOKEN = /^[A-Za-z0-9_-]{32}$/;

export const validName = (v: unknown): v is string => typeof v === "string" && v.trim().length >= 1 && v.trim().length <= LOCATION_LIMITS.NAME_MAX && !/\p{C}/u.test(v);
export const validLocationId = (v: unknown): v is string => typeof v === "string" && LOCATION_ID.test(v);
export const validPublicKey = (v: unknown): v is string => typeof v === "string" && KEY.test(v);
export const validToken = (v: unknown): v is string => typeof v === "string" && TOKEN.test(v);

export function b64urlEncode(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64urlDecode(text: string): Uint8Array {
  const s = text.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(s + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

export async function sha256Hex(data: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(data));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** The text a request is signed over: method, path, the timestamp header and the hash of the body. */
export function signingString(method: string, path: string, timestamp: string, bodyHash: string): string {
  return `${method}\n${path}\n${timestamp}\n${bodyHash}`;
}

export async function verifySignature(publicKey: string, message: string, signature: string): Promise<boolean> {
  if (!validPublicKey(publicKey) || !SIGNATURE.test(signature)) return false;
  try {
    const key = await crypto.subtle.importKey("raw", b64urlDecode(publicKey), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, b64urlDecode(signature), new TextEncoder().encode(message));
  } catch {
    return false;
  }
}

/** True when the timestamp header (unix seconds) is within the allowed clock skew of `nowMs`. */
export function freshTimestamp(timestamp: string | null, nowMs: number): boolean {
  if (!timestamp || !/^\d{1,12}$/.test(timestamp)) return false;
  return Math.abs(nowMs / 1000 - Number(timestamp)) <= LOCATION_LIMITS.CLOCK_SKEW_S;
}

export interface LocationEnv { DB?: D1Database }
export type Limiter = (purpose: string, cfg: { limit: number; windowMs: number }, key?: string) => Promise<boolean>;

const REGISTER_LIMIT = { limit: 20, windowMs: 3_600_000 };
const INVITE_LIMIT = { limit: 20, windowMs: 24 * 3_600_000 };
const REDEEM_LIMIT = { limit: 10, windowMs: 3_600_000 };
const REDEEM_IP_LIMIT = { limit: 30, windowMs: 3_600_000 };
const READ_LIMIT = { limit: 120, windowMs: 3_600_000 };
const WRITE_LIMIT = { limit: 60, windowMs: 3_600_000 };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const tooMany = () => json({ error: "too many requests" }, 429);
const randomToken = () => b64urlEncode(crypto.getRandomValues(new Uint8Array(24)));
const randomId = () => [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");

async function readBody(request: Request): Promise<{ raw: string; data: Record<string, unknown> } | Response> {
  const raw = await request.text();
  if (raw.length > LOCATION_LIMITS.BODY_BYTES) return json({ error: "too large" }, 413);
  if (raw === "") return { raw, data: {} };
  try {
    const data = JSON.parse(raw);
    if (typeof data !== "object" || data === null || Array.isArray(data)) return json({ error: "not an object" }, 400);
    return { raw, data };
  } catch {
    return json({ error: "not JSON" }, 400);
  }
}

/** The location that signed the request, or the reason it is refused. */
async function authenticate(request: Request, env: LocationEnv, raw: string, now: number): Promise<{ id: string } | Response> {
  const id = request.headers.get("x-location");
  const timestamp = request.headers.get("x-timestamp");
  const signature = request.headers.get("x-signature") ?? "";
  if (!validLocationId(id) || !freshTimestamp(timestamp, now)) return json({ error: "not signed correctly" }, 401);
  const row = await env.DB!.prepare("SELECT public_key FROM locations WHERE id = ?").bind(id).first<{ public_key: string }>();
  if (!row) return json({ error: "unknown location" }, 401);
  const path = new URL(request.url).pathname;
  const message = signingString(request.method, path, timestamp as string, await sha256Hex(raw));
  if (!(await verifySignature(row.public_key, message, signature))) return json({ error: "not signed correctly" }, 401);
  return { id };
}

const SAME_LINK = "SELECT id FROM links WHERE (location_a = ?1 AND location_b = ?2) OR (location_a = ?2 AND location_b = ?1)";

/** The routes of the locations; null when the request is none of them. */
export async function handleLocations(request: Request, env: LocationEnv, limited: Limiter, now = Date.now()): Promise<Response | null> {
  const path = new URL(request.url).pathname;
  const method = request.method;
  const invite = path.match(/^\/locations\/([0-9a-f]{32})\/invitations$/);
  const links = path.match(/^\/locations\/([0-9a-f]{32})\/links$/);
  const link = path.match(/^\/links\/([0-9a-f]{32})$/);
  const own = path.match(/^\/locations\/([0-9a-f]{32})$/);
  const route =
    method === "POST" && path === "/locations" ? "register"
    : method === "POST" && invite ? "invite"
    : method === "POST" && path === "/invitations/redeem" ? "redeem"
    : method === "GET" && links ? "links"
    : method === "DELETE" && link ? "unlink"
    : method === "PATCH" && own ? "rename"
    : method === "DELETE" && own ? "delete"
    : null;
  if (!route) return null;
  if (!env.DB) return json({ error: "locations are not set up here" }, 503);

  const body = await readBody(request);
  if (body instanceof Response) return body;

  if (route === "register") {
    if (await limited("loc-register", REGISTER_LIMIT)) return tooMany();
    const { name, public_key: publicKey } = body.data;
    if (!validName(name) || !validPublicKey(publicKey)) return json({ error: "bad name or key" }, 400);
    const timestamp = request.headers.get("x-timestamp");
    const signature = request.headers.get("x-signature") ?? "";
    const message = signingString(method, path, timestamp ?? "", await sha256Hex(body.raw));
    if (!freshTimestamp(timestamp, now) || !(await verifySignature(publicKey, message, signature))) return json({ error: "not signed correctly" }, 401);
    const known = await env.DB.prepare("SELECT id FROM locations WHERE public_key = ?").bind(publicKey).first<{ id: string }>();
    if (known) return json({ id: known.id });
    const id = randomId();
    await env.DB.prepare("INSERT INTO locations (id, name, public_key) VALUES (?, ?, ?)").bind(id, name.trim(), publicKey).run();
    return json({ id }, 201);
  }

  const who = await authenticate(request, env, body.raw, now);
  if (who instanceof Response) return who;
  const db = env.DB;

  if (route === "invite") {
    if (who.id !== invite![1]) return json({ error: "not your location" }, 403);
    if (await limited("loc-invite", INVITE_LIMIT, who.id)) return tooMany();
    await db.prepare("DELETE FROM invitations WHERE location_id = ? AND (used_at IS NOT NULL OR expires_at < ?)").bind(who.id, now).run();
    const pending = await db.prepare("SELECT COUNT(*) AS n FROM invitations WHERE location_id = ?").bind(who.id).first<{ n: number }>();
    if ((pending?.n ?? 0) >= LOCATION_LIMITS.PENDING_INVITATIONS) return json({ error: "too many open invitations" }, 429);
    const token = randomToken();
    const expiresAt = now + LOCATION_LIMITS.INVITATION_TTL_MS;
    await db.prepare("INSERT INTO invitations (token_hash, location_id, expires_at) VALUES (?, ?, ?)").bind(await sha256Hex(token), who.id, expiresAt).run();
    return json({ token, expires_at: expiresAt }, 201);
  }

  if (route === "redeem") {
    if (await limited("loc-redeem", REDEEM_LIMIT, who.id) || await limited("loc-redeem-ip", REDEEM_IP_LIMIT)) return tooMany();
    const token = body.data.token;
    if (!validToken(token)) return json({ error: "invalid or expired invitation" }, 404);
    const hash = await sha256Hex(token);
    const inv = await db.prepare("SELECT location_id FROM invitations WHERE token_hash = ? AND used_at IS NULL AND expires_at >= ?").bind(hash, now).first<{ location_id: string }>();
    if (!inv) return json({ error: "invalid or expired invitation" }, 404);
    if (inv.location_id === who.id) return json({ error: "this is your own invitation" }, 400);
    const peer = await db.prepare("SELECT id, name FROM locations WHERE id = ?").bind(inv.location_id).first<{ id: string; name: string }>();
    if (!peer) return json({ error: "invalid or expired invitation" }, 404);
    const counts = await db.prepare("SELECT (SELECT COUNT(*) FROM links WHERE location_a = ?1 OR location_b = ?1) AS mine, (SELECT COUNT(*) FROM links WHERE location_a = ?2 OR location_b = ?2) AS theirs").bind(who.id, peer.id).first<{ mine: number; theirs: number }>();
    if ((counts?.mine ?? 0) >= LOCATION_LIMITS.LINKS_PER_LOCATION || (counts?.theirs ?? 0) >= LOCATION_LIMITS.LINKS_PER_LOCATION) return json({ error: "too many links" }, 429);
    const used = await db.prepare("UPDATE invitations SET used_at = ? WHERE token_hash = ? AND used_at IS NULL").bind(now, hash).run();
    if (used.meta.changes !== 1) return json({ error: "invalid or expired invitation" }, 404);
    const existing = await db.prepare(SAME_LINK).bind(who.id, peer.id).first<{ id: string }>();
    let linkId = existing?.id;
    if (!linkId) {
      linkId = randomId();
      await db.prepare("INSERT INTO links (id, location_a, location_b) VALUES (?, ?, ?)").bind(linkId, peer.id, who.id).run();
    }
    return json({ link_id: linkId, peer: { id: peer.id, name: peer.name } }, 201);
  }

  if (route === "links") {
    if (who.id !== links![1]) return json({ error: "not your location" }, 403);
    if (await limited("loc-read", READ_LIMIT, who.id)) return tooMany();
    const rows = await db.prepare(
      "SELECT links.id AS link_id, links.kind, links.created_at, locations.id AS peer_id, locations.name AS peer_name FROM links " +
      "JOIN locations ON locations.id = CASE WHEN links.location_a = ?1 THEN links.location_b ELSE links.location_a END " +
      "WHERE links.location_a = ?1 OR links.location_b = ?1 ORDER BY links.created_at",
    ).bind(who.id).all<{ link_id: string; kind: string; created_at: string; peer_id: string; peer_name: string }>();
    return json({ links: rows.results.map((r) => ({ link_id: r.link_id, kind: r.kind, created_at: r.created_at, peer: { id: r.peer_id, name: r.peer_name } })) });
  }

  if (route === "rename" || route === "delete") {
    if (who.id !== own![1]) return json({ error: "not your location" }, 403);
    if (await limited("loc-write", WRITE_LIMIT, who.id)) return tooMany();
    if (route === "rename") {
      const name = body.data.name;
      if (!validName(name)) return json({ error: "bad name" }, 400);
      await db.prepare("UPDATE locations SET name = ? WHERE id = ?").bind(name.trim(), who.id).run();
      return json({ ok: true });
    }
    await db.batch([
      db.prepare("DELETE FROM links WHERE location_a = ?1 OR location_b = ?1").bind(who.id),
      db.prepare("DELETE FROM invitations WHERE location_id = ?").bind(who.id),
      db.prepare("DELETE FROM locations WHERE id = ?").bind(who.id),
    ]);
    return json({ ok: true });
  }

  // unlink
  const row = await db.prepare("SELECT id FROM links WHERE id = ? AND (location_a = ? OR location_b = ?)").bind(link![1], who.id, who.id).first<{ id: string }>();
  if (!row) return json({ error: "unknown link" }, 404);
  await db.prepare("DELETE FROM links WHERE id = ?").bind(row.id).run();
  return json({ ok: true });
}
