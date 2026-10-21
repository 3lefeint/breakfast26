// Voice chat between the sites of a match: the signaling frames of the voice room and the ICE servers the browsers
// get. The audio itself never touches the relay (WebRTC, directly between the browsers); the relay only passes on
// offers, answers and ICE candidates. Plain TypeScript without Cloudflare APIs, like core.ts.

import { validName } from "./protocol";

export const VOICE_LIMITS = {
  MAX_PEERS: 6,
  FRAME_BYTES: 16 * 1024,
  JOIN_TIMEOUT_MS: 10_000,
  TURN_TTL_S: 24 * 3600,
} as const;

export const VOICE_CLOSE = { BAD_REQUEST: 4400, UNAUTHORIZED: 4401, CONFLICT: 4409 } as const;

export interface IceServer { urls: string[]; username?: string; credential?: string }

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const PEER = /^[0-9a-f]{16}$/;

/** null if `m` is a valid frame from a browser in the voice room, else why not. */
export function validateVoiceFrame(m: unknown): string | null {
  if (!isObj(m) || typeof m.type !== "string") return "frame must be an object with a type";
  switch (m.type) {
    case "join":
      if (!validName(m.site)) return "site must be a name of up to 24 characters";
      return typeof m.ticket === "string" && m.ticket.length > 0 && m.ticket.length <= 128 ? null : "ticket is required";
    case "signal":
      if (typeof m.to !== "string" || !PEER.test(m.to)) return "to must be a peer id";
      if (!isObj(m.data)) return "data must be an object";
      if (!("description" in m.data) && !("candidate" in m.data)) return "data needs a description or a candidate";
      return null;
    case "mute":
      return typeof m.muted === "boolean" ? null : "muted must be a boolean";
    default:
      return `unknown frame type ${m.type}`;
  }
}

const STUN: IceServer = { urls: ["stun:stun.cloudflare.com:3478"] };

/** STUN, and TURN as well when a TURN key is configured (a Worker secret, never sent to the browser). */
export async function iceServers(
  env: { TURN_KEY_ID?: string; TURN_KEY_API_TOKEN?: string },
  fetchFn: typeof fetch = fetch,
): Promise<IceServer[]> {
  if (!env.TURN_KEY_ID || !env.TURN_KEY_API_TOKEN) return [STUN];
  try {
    const res = await fetchFn(`https://rtc.live.cloudflare.com/v1/turn/keys/${encodeURIComponent(env.TURN_KEY_ID)}/credentials/generate-ice-servers`, {
      method: "POST",
      headers: { authorization: `Bearer ${env.TURN_KEY_API_TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify({ ttl: VOICE_LIMITS.TURN_TTL_S }),
    });
    if (!res.ok) return [STUN];
    const body = (await res.json()) as { iceServers?: IceServer[] };
    const servers = (body.iceServers ?? [])
      .map((s) => ({ ...s, urls: (Array.isArray(s.urls) ? s.urls : [s.urls]).filter((u) => typeof u === "string" && !u.includes(":53")) }))
      .filter((s) => s.urls.length > 0);
    return servers.length ? servers : [STUN];
  } catch {
    return [STUN];
  }
}
