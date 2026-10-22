// Mailboxes: where the match records of a member travel between a location and the member's installations
// (see PROTOCOL.md, "Mailboxes"). The relay stores ciphertext and a small clear envelope, never the content:
// the index lives in D1, the ciphertext in R2. A location signs as it does for the other routes, a member's
// device signs with its own Ed25519 key, registered when the invitation of the member was redeemed.

import {
  b64urlDecode, b64urlEncode, freshTimestamp, Limiter, LocationEnv, sha256Hex, signingString, validLocationId, validPublicKey,
  validToken, verifySignature, authenticate,
} from "./locations";

export const MAILBOX_LIMITS = {
  RECORD_BYTES: 256 * 1024,            // a record, as ciphertext
  BODY_BYTES: 400_000,                 // the JSON body that carries it (base64url is a third larger)
  RECORDS_PER_WRITER_DAY: 200,
  RECORDS_PER_MAILBOX: 1000,
  BYTES_PER_MAILBOX: 20 * 1024 * 1024,
  MAILBOXES_PER_LOCATION: 200,
  DEVICES_PER_MAILBOX: 5,
  PENDING_INVITATIONS_PER_MAILBOX: 3,
  INVITATION_TTL_MS: 7 * 24 * 3600 * 1000,
  LIST_MAX: 100,
};

export interface MailboxEnv extends LocationEnv {
  RECORDS?: R2Bucket;
  SHARING?: string;                    // "off" switches the sharing routes off
}

const MODES = ["X01", "Elimination"];
const CHANNELS = ["down", "up"];
const ID = /^[0-9a-f]{32}$/;
const MATCH_ID = /^[A-Za-z0-9._:-]{1,80}$/;

const INVITE_LIMIT = { limit: 60, windowMs: 24 * 3_600_000 };
const REDEEM_LIMIT = { limit: 10, windowMs: 3_600_000 };
const REDEEM_IP_LIMIT = { limit: 30, windowMs: 3_600_000 };
const READ_LIMIT = { limit: 600, windowMs: 3_600_000 };
const WRITE_LIMIT = { limit: 600, windowMs: 3_600_000 };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const tooMany = () => json({ error: "too many requests" }, 429);
const randomToken = () => b64urlEncode(crypto.getRandomValues(new Uint8Array(24)));
const randomId = () => [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
const objectKey = (mailbox: string, channel: string, matchId: string, revision: number) => `${mailbox}/${channel}/${matchId}/${revision}`;

async function readBody(request: Request): Promise<{ raw: string; data: Record<string, unknown> } | Response> {
  const raw = await request.text();
  if (raw.length > MAILBOX_LIMITS.BODY_BYTES) return json({ error: "too large" }, 413);
  if (raw === "") return { raw, data: {} };
  try {
    const data = JSON.parse(raw);
    if (typeof data !== "object" || data === null || Array.isArray(data)) return json({ error: "not an object" }, 400);
    return { raw, data };
  } catch {
    return json({ error: "not JSON" }, 400);
  }
}

type Who = { kind: "location"; id: string } | { kind: "device"; id: string; mailbox: string };

/** The location or the member device that signed the request, or the reason it is refused. */
async function whoSigned(request: Request, env: MailboxEnv, raw: string, now: number): Promise<Who | Response> {
  const device = request.headers.get("x-device");
  if (device === null) {
    const located = await authenticate(request, env, raw, now);
    return located instanceof Response ? located : { kind: "location", id: located.id };
  }
  const timestamp = request.headers.get("x-timestamp");
  const signature = request.headers.get("x-signature") ?? "";
  if (!ID.test(device) || !freshTimestamp(timestamp, now)) return json({ error: "not signed correctly" }, 401);
  const row = await env.DB!.prepare("SELECT public_key, mailbox_id FROM devices WHERE id = ?").bind(device).first<{ public_key: string; mailbox_id: string }>();
  if (!row) return json({ error: "unknown device" }, 401);
  const message = signingString(request.method, new URL(request.url).pathname, timestamp as string, await sha256Hex(raw));
  if (!(await verifySignature(row.public_key, message, signature))) return json({ error: "not signed correctly" }, 401);
  return { kind: "device", id: device, mailbox: row.mailbox_id };
}

/** Delete a mailbox: its ciphertext, then its rows. */
export async function dropMailbox(env: MailboxEnv, mailboxId: string): Promise<void> {
  const prefix = `${mailboxId}/`;
  let cursor: string | undefined;
  do {
    const listed = await env.RECORDS!.list({ prefix, cursor, limit: 500 });
    if (listed.objects.length) await env.RECORDS!.delete(listed.objects.map((o) => o.key));
    cursor = listed.truncated ? listed.cursor : undefined;
  } while (cursor);
  await env.DB!.batch([
    env.DB!.prepare("DELETE FROM records WHERE mailbox_id = ?").bind(mailboxId),
    env.DB!.prepare("DELETE FROM devices WHERE mailbox_id = ?").bind(mailboxId),
    env.DB!.prepare("DELETE FROM mailbox_invitations WHERE mailbox_id = ?").bind(mailboxId),
    env.DB!.prepare("DELETE FROM mailboxes WHERE id = ?").bind(mailboxId),
  ]);
}

/** Delete every mailbox of a location (when the location signs off). */
export async function dropMailboxesOf(env: MailboxEnv, locationId: string): Promise<void> {
  if (!env.DB || !env.RECORDS) return;
  const rows = await env.DB.prepare("SELECT id FROM mailboxes WHERE location_id = ?").bind(locationId).all<{ id: string }>();
  for (const row of rows.results) await dropMailbox(env, row.id);
}

/** The routes of the mailboxes; null when the request is none of them. */
export async function handleMailboxes(request: Request, env: MailboxEnv, limited: Limiter, now = Date.now()): Promise<Response | null> {
  const path = new URL(request.url).pathname;
  const method = request.method;
  const members = path.match(/^\/locations\/([0-9a-f]{32})\/members$/);
  const box = path.match(/^\/mailboxes\/([0-9a-f]{32})$/);
  const invites = path.match(/^\/mailboxes\/([0-9a-f]{32})\/invitations$/);
  const channel = path.match(/^\/mailboxes\/([0-9a-f]{32})\/(down|up)$/);
  const record = path.match(/^\/mailboxes\/([0-9a-f]{32})\/(down|up)\/([^/]+)\/(\d{1,7})$/);
  const route =
    method === "POST" && members ? "member"
    : method === "POST" && invites ? "reinvite"
    : method === "POST" && path === "/mailbox-invitations/redeem" ? "redeem"
    : method === "DELETE" && box ? "drop"
    : method === "PATCH" && box ? "up"
    : method === "PUT" && record ? "put"
    : method === "GET" && channel ? "list"
    : method === "GET" && record ? "fetch"
    : null;
  if (!route) return null;
  if (env.SHARING === "off") return json({ error: "sharing is switched off" }, 503);
  if (!env.DB || !env.RECORDS) return json({ error: "sharing is not set up here" }, 503);
  const db = env.DB;

  const body = await readBody(request);
  if (body instanceof Response) return body;

  if (route === "redeem") {
    if (await limited("mbx-redeem-ip", REDEEM_IP_LIMIT)) return tooMany();
    const { token, public_key: publicKey } = body.data;
    if (!validToken(token) || !validPublicKey(publicKey)) return json({ error: "invalid or expired invitation" }, 404);
    // the device proves that it holds the key it registers
    const timestamp = request.headers.get("x-timestamp");
    const message = signingString(method, path, timestamp ?? "", await sha256Hex(body.raw));
    if (!freshTimestamp(timestamp, now) || !(await verifySignature(publicKey, message, request.headers.get("x-signature") ?? ""))) {
      return json({ error: "not signed correctly" }, 401);
    }
    const hash = await sha256Hex(token);
    if (await limited("mbx-redeem", REDEEM_LIMIT, hash)) return tooMany();
    const inv = await db.prepare("SELECT mailbox_id FROM mailbox_invitations WHERE token_hash = ? AND used_at IS NULL AND expires_at >= ?").bind(hash, now).first<{ mailbox_id: string }>();
    if (!inv) return json({ error: "invalid or expired invitation" }, 404);
    const mailbox = await db.prepare(
      "SELECT mailboxes.id, mailboxes.up_enabled, locations.id AS location_id, locations.name AS location_name FROM mailboxes " +
      "JOIN locations ON locations.id = mailboxes.location_id WHERE mailboxes.id = ?").bind(inv.mailbox_id)
      .first<{ id: string; up_enabled: number; location_id: string; location_name: string }>();
    if (!mailbox) return json({ error: "invalid or expired invitation" }, 404);
    const devices = await db.prepare("SELECT COUNT(*) AS n FROM devices WHERE mailbox_id = ?").bind(mailbox.id).first<{ n: number }>();
    if ((devices?.n ?? 0) >= MAILBOX_LIMITS.DEVICES_PER_MAILBOX) return json({ error: "too many devices" }, 429);
    const used = await db.prepare("UPDATE mailbox_invitations SET used_at = ? WHERE token_hash = ? AND used_at IS NULL").bind(now, hash).run();
    if (used.meta.changes !== 1) return json({ error: "invalid or expired invitation" }, 404);
    const deviceId = randomId();
    await db.prepare("INSERT INTO devices (id, mailbox_id, public_key, created_at) VALUES (?, ?, ?, ?)").bind(deviceId, mailbox.id, publicKey, now).run();
    return json({ mailbox_id: mailbox.id, device_id: deviceId, up: mailbox.up_enabled === 1, location: { id: mailbox.location_id, name: mailbox.location_name } }, 201);
  }

  const who = await whoSigned(request, env, body.raw, now);
  if (who instanceof Response) return who;

  // the mailbox the request is about, and the rule that it is the signer's
  const mailboxId = (members?.[1] ?? box?.[1] ?? invites?.[1] ?? channel?.[1] ?? record?.[1]) as string;
  if (members) {
    if (who.kind !== "location" || who.id !== members[1]) return json({ error: "not your location" }, 403);
    if (await limited("mbx-invite", INVITE_LIMIT, who.id)) return tooMany();
    const owned = await db.prepare("SELECT COUNT(*) AS n FROM mailboxes WHERE location_id = ?").bind(who.id).first<{ n: number }>();
    if ((owned?.n ?? 0) >= MAILBOX_LIMITS.MAILBOXES_PER_LOCATION) return json({ error: "too many members" }, 429);
    const id = randomId();
    const token = randomToken();
    const expiresAt = now + MAILBOX_LIMITS.INVITATION_TTL_MS;
    await db.batch([
      db.prepare("INSERT INTO mailboxes (id, location_id, up_enabled, created_at) VALUES (?, ?, 0, ?)").bind(id, who.id, now),
      db.prepare("INSERT INTO mailbox_invitations (token_hash, mailbox_id, expires_at) VALUES (?, ?, ?)").bind(await sha256Hex(token), id, expiresAt),
    ]);
    return json({ mailbox_id: id, token, expires_at: expiresAt }, 201);
  }

  const mailbox = await db.prepare("SELECT id, location_id, up_enabled FROM mailboxes WHERE id = ?").bind(mailboxId).first<{ id: string; location_id: string; up_enabled: number }>();
  const mine = mailbox && (who.kind === "location" ? mailbox.location_id === who.id : who.mailbox === mailbox.id);
  if (!mailbox || !mine) return json({ error: "unknown mailbox" }, 404);        // not told apart: nobody learns which mailboxes exist

  if (route === "drop" || route === "up" || route === "reinvite") {
    if (who.kind !== "location") return json({ error: "only the location does that" }, 403);
    if (await limited("mbx-write", WRITE_LIMIT, who.id)) return tooMany();
    if (route === "drop") {
      await dropMailbox(env, mailbox.id);
      return json({ ok: true });
    }
    if (route === "up") {
      if (typeof body.data.up !== "boolean") return json({ error: "up must be true or false" }, 400);
      await db.prepare("UPDATE mailboxes SET up_enabled = ? WHERE id = ?").bind(body.data.up ? 1 : 0, mailbox.id).run();
      return json({ ok: true, up: body.data.up });
    }
    if (await limited("mbx-invite", INVITE_LIMIT, who.id)) return tooMany();
    await db.prepare("DELETE FROM mailbox_invitations WHERE mailbox_id = ? AND (used_at IS NOT NULL OR expires_at < ?)").bind(mailbox.id, now).run();
    const pending = await db.prepare("SELECT COUNT(*) AS n FROM mailbox_invitations WHERE mailbox_id = ?").bind(mailbox.id).first<{ n: number }>();
    if ((pending?.n ?? 0) >= MAILBOX_LIMITS.PENDING_INVITATIONS_PER_MAILBOX) return json({ error: "too many open invitations" }, 429);
    const token = randomToken();
    const expiresAt = now + MAILBOX_LIMITS.INVITATION_TTL_MS;
    await db.prepare("INSERT INTO mailbox_invitations (token_hash, mailbox_id, expires_at) VALUES (?, ?, ?)").bind(await sha256Hex(token), mailbox.id, expiresAt).run();
    return json({ mailbox_id: mailbox.id, token, expires_at: expiresAt }, 201);
  }

  // channels: the location writes `down` and reads `up`, a device of the member the other way round
  const name = (channel?.[2] ?? record?.[2]) as string;
  if (!CHANNELS.includes(name)) return json({ error: "unknown channel" }, 404);
  const writes = (name === "down") === (who.kind === "location");
  if ((route === "put") !== writes) return json({ error: "this channel is not yours to " + (route === "put" ? "write" : "read") }, 403);

  if (route === "list") {
    if (await limited("mbx-read", READ_LIMIT, who.id)) return tooMany();
    const url = new URL(request.url);
    const since = Number(url.searchParams.get("since") ?? "0");
    const limit = Math.min(Number(url.searchParams.get("limit") ?? MAILBOX_LIMITS.LIST_MAX), MAILBOX_LIMITS.LIST_MAX);
    if (!Number.isInteger(since) || since < 0 || !Number.isInteger(limit) || limit < 1) return json({ error: "bad cursor" }, 400);
    const rows = await db.prepare(
      "SELECT seq, match_id, revision, game_mode, deleted, size, hash, envelope_version, created_at FROM records " +
      "WHERE mailbox_id = ? AND channel = ? AND seq > ? ORDER BY seq LIMIT ?").bind(mailbox.id, name, since, limit)
      .all<{ seq: number; match_id: string; revision: number; game_mode: string; deleted: number; size: number; hash: string; envelope_version: number; created_at: number }>();
    const records = rows.results.map((r) => ({ ...r, deleted: r.deleted === 1 }));
    return json({ records, next: records.length ? records[records.length - 1].seq : since });
  }

  const matchId = decodeURIComponent(record![3]);
  const revision = Number(record![4]);
  if (!MATCH_ID.test(matchId) || revision < 1) return json({ error: "bad match id or revision" }, 400);

  if (route === "fetch") {
    if (await limited("mbx-read", READ_LIMIT, who.id)) return tooMany();
    const row = await db.prepare(
      "SELECT seq, game_mode, deleted, size, hash, envelope_version, created_at FROM records WHERE mailbox_id = ? AND channel = ? AND match_id = ? AND revision = ?")
      .bind(mailbox.id, name, matchId, revision).first<{ seq: number; game_mode: string; deleted: number; size: number; hash: string; envelope_version: number; created_at: number }>();
    if (!row) return json({ error: "unknown record" }, 404);
    let ciphertext: string | null = null;
    if (row.deleted !== 1) {
      const object = await env.RECORDS.get(objectKey(mailbox.id, name, matchId, revision));
      if (!object) return json({ error: "unknown record" }, 404);
      ciphertext = b64urlEncode(new Uint8Array(await object.arrayBuffer()));
    }
    return json({ seq: row.seq, match_id: matchId, revision, game_mode: row.game_mode, deleted: row.deleted === 1, size: row.size, hash: row.hash,
      envelope_version: row.envelope_version, created_at: row.created_at, ciphertext });
  }

  // put
  if (name === "up" && mailbox.up_enabled !== 1) return json({ error: "the member does not send matches to this location" }, 403);
  if (await limited("mbx-write", WRITE_LIMIT, who.id)) return tooMany();
  const { envelope_version: version, game_mode: mode, deleted, ciphertext } = body.data;
  if (!Number.isInteger(version) || (version as number) < 1 || (version as number) > 1000) return json({ error: "bad envelope_version" }, 400);
  if (typeof mode !== "string" || !MODES.includes(mode)) return json({ error: "bad game_mode" }, 400);
  if (typeof deleted !== "boolean") return json({ error: "deleted must be true or false" }, 400);
  let bytes: Uint8Array<ArrayBuffer> = new Uint8Array(0);
  if (deleted) {
    if (ciphertext !== undefined && ciphertext !== null) return json({ error: "a deletion carries no ciphertext" }, 400);
  } else {
    if (typeof ciphertext !== "string" || ciphertext === "" || !/^[A-Za-z0-9_-]+$/.test(ciphertext)) return json({ error: "ciphertext must be base64url" }, 400);
    try { bytes = b64urlDecode(ciphertext) as Uint8Array<ArrayBuffer>; } catch { return json({ error: "ciphertext must be base64url" }, 400); }
    if (bytes.length > MAILBOX_LIMITS.RECORD_BYTES) return json({ error: "the record is too large" }, 413);
  }
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const existing = await db.prepare("SELECT hash, revision FROM records WHERE mailbox_id = ? AND channel = ? AND match_id = ? ORDER BY revision DESC LIMIT 1")
    .bind(mailbox.id, name, matchId).first<{ hash: string; revision: number }>();
  if (existing && existing.revision === revision) {
    if (existing.hash !== hash) return json({ error: "that revision exists with other content" }, 409);
    const same = await db.prepare("SELECT seq FROM records WHERE mailbox_id = ? AND channel = ? AND match_id = ? AND revision = ?").bind(mailbox.id, name, matchId, revision).first<{ seq: number }>();
    return json({ seq: same!.seq, size: bytes.length, hash });                 // the same record again: nothing changes
  }
  if (existing && existing.revision > revision) return json({ error: "a newer revision exists" }, 409);

  const day = await db.prepare("SELECT COUNT(*) AS n FROM records WHERE writer = ? AND created_at >= ?").bind(who.id, now - 24 * 3_600_000).first<{ n: number }>();
  if ((day?.n ?? 0) >= MAILBOX_LIMITS.RECORDS_PER_WRITER_DAY) return json({ error: "too many records today" }, 429);
  const used = await db.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM records WHERE mailbox_id = ?").bind(mailbox.id).first<{ n: number; bytes: number }>();
  if ((used?.n ?? 0) >= MAILBOX_LIMITS.RECORDS_PER_MAILBOX || (used?.bytes ?? 0) + bytes.length > MAILBOX_LIMITS.BYTES_PER_MAILBOX) return json({ error: "the mailbox is full" }, 413);

  const key = objectKey(mailbox.id, name, matchId, revision);
  if (!deleted) await env.RECORDS.put(key, bytes);
  let seq: number;
  try {
    const result = await db.prepare(
      "INSERT INTO records (mailbox_id, channel, match_id, revision, game_mode, deleted, size, hash, envelope_version, writer, created_at) " +
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind(mailbox.id, name, matchId, revision, mode, deleted ? 1 : 0, bytes.length, hash, version, who.id, now).run();
    seq = result.meta.last_row_id;
  } catch (e) {
    if (!deleted) await env.RECORDS.delete(key);
    throw e;
  }
  // an older revision of the match is not needed any more
  const older = await db.prepare("SELECT revision, deleted FROM records WHERE mailbox_id = ? AND channel = ? AND match_id = ? AND revision < ?").bind(mailbox.id, name, matchId, revision).all<{ revision: number; deleted: number }>();
  for (const o of older.results) if (o.deleted !== 1) await env.RECORDS.delete(objectKey(mailbox.id, name, matchId, o.revision));
  if (older.results.length) await db.prepare("DELETE FROM records WHERE mailbox_id = ? AND channel = ? AND match_id = ? AND revision < ?").bind(mailbox.id, name, matchId, revision).run();
  return json({ seq, size: bytes.length, hash }, 201);
}
