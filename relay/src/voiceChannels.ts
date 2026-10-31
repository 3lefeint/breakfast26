// Voice chat channels of the circle: the admin makes channels and ticks which sites see which (see admin.ts), an approved site
// lists the channels it sees and asks for a ticket to enter one (see PROTOCOL.md, "Voice channels"). The room itself is a
// VoiceRoom per channel (worker.ts); the ticket is kept there. Requests are signed with the key of the location as for the other routes.

import { authenticate, Limiter, LocationEnv } from "./locations";

export const CHANNEL_LIMITS = {
  CHANNELS: 20,
  TICKET_TTL_MS: 24 * 3_600_000,
  BODY_BYTES: 1024,
};

export interface VoiceChannelEnv extends LocationEnv {
  VOICE: DurableObjectNamespace;
}

const READ_LIMIT = { limit: 600, windowMs: 3_600_000 };
const TICKET_LIMIT = { limit: 120, windowMs: 3_600_000 };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

export const channelRoom = (id: string) => `channel:${id}`;

/** The rooms of these channels check who is in them again: the admin took a site out of a channel, deleted it or took the site out
 *  of the circle, and whoever may not be there any more is sent out. */
export async function recheckChannels(voice: DurableObjectNamespace | undefined, channelIds: string[]): Promise<void> {
  if (!voice) return;
  for (const id of channelIds) {
    try { await voice.get(voice.idFromName(channelRoom(id))).fetch("https://room/recheck", { method: "POST" }); } catch { /* the room is not reachable, the next join checks again */ }
  }
}

/** Does this site see the channel? An approved site of the circle the admin ticked for it. */
export async function siteSeesChannel(db: D1Database, channelId: string, locationId: string): Promise<boolean> {
  const row = await db.prepare(
    "SELECT 1 AS ok FROM voice_channel_sites v JOIN circle_sites s ON s.location_id = v.location_id AND s.approved = 1 " +
    "WHERE v.channel_id = ? AND v.location_id = ?").bind(channelId, locationId).first();
  return row !== null;
}

/** The routes of the voice channels for the sites; null when the request is none of them. */
export async function handleVoiceChannels(request: Request, env: VoiceChannelEnv, limited: Limiter, now = Date.now()): Promise<Response | null> {
  const path = new URL(request.url).pathname;
  const method = request.method;
  const ticket = path.match(/^\/circle\/voice\/([0-9a-f]{32})\/ticket$/);
  const route = method === "GET" && path === "/circle/voice" ? "list" : method === "POST" && ticket ? "ticket" : null;
  if (!route) return null;
  if (!env.DB) return json({ error: "voice channels are not set up here" }, 503);
  const db = env.DB;

  const raw = await request.text();
  if (raw.length > CHANNEL_LIMITS.BODY_BYTES) return json({ error: "too large" }, 413);
  const who = await authenticate(request, env, raw, now);
  if (who instanceof Response) return who;
  const site = who.id;
  const approved = await db.prepare("SELECT approved FROM circle_sites WHERE location_id = ?").bind(site).first<{ approved: number }>();
  if (approved?.approved !== 1) return json({ error: "this site is not approved by the admin yet" }, 403);

  if (route === "list") {
    if (await limited("voice-channels", READ_LIMIT, site)) return json({ error: "too many requests" }, 429);
    const rows = await db.prepare(
      "SELECT c.id, c.name FROM voice_channels c JOIN voice_channel_sites v ON v.channel_id = c.id WHERE v.location_id = ? ORDER BY lower(c.name)")
      .bind(site).all<{ id: string; name: string }>();
    return json({ channels: rows.results });
  }

  if (await limited("voice-channel-ticket", TICKET_LIMIT, site)) return json({ error: "too many requests" }, 429);
  const channelId = ticket![1];
  const channel = await db.prepare("SELECT name FROM voice_channels WHERE id = ?").bind(channelId).first<{ name: string }>();
  if (!channel || !(await siteSeesChannel(db, channelId, site))) return json({ error: "unknown channel" }, 404);
  const me = await db.prepare("SELECT name FROM locations WHERE id = ?").bind(site).first<{ name: string }>();
  if (!me) return json({ error: "unknown location" }, 401);
  const value = [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const res = await env.VOICE.get(env.VOICE.idFromName(channelRoom(channelId))).fetch("https://room/ticket", {
    method: "POST", body: JSON.stringify({ location: site, site: me.name, ticket: value, until: now + CHANNEL_LIMITS.TICKET_TTL_MS }) });
  if (res.status !== 200) return json({ error: "could not issue a ticket" }, 503);
  return json({ ticket: value, site: me.name, channel: { id: channelId, name: channel.name } });
}
