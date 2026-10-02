// Message shapes of protocol version 1 (see ../PROTOCOL.md) and their validation.
// Both the Worker and the Python client check their frames against the examples in
// ../protocol-tests/messages.json.

export const PROTOCOL_VERSION = 1;

export const CLOSE = {
  BAD_REQUEST: 4400,
  UNAUTHORIZED: 4401,
  UNKNOWN_CODE: 4404,
  CONFLICT: 4409,
  OVER: 4410,
  UPGRADE: 4426,
  RATE_LIMITED: 4429,
} as const;

export const LIMITS = {
  MAX_PLAYERS: 12,
  MAX_SITES: 6,
  MIN_PLAYERS: 2,
  MAX_LIVES: 10,
  NAME_LENGTH: 24,
  CODE_LENGTH: 6,
  CODE_ALPHABET: "ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
  CODE_TTL_MS: 10 * 60 * 1000,
  HELLO_TIMEOUT_MS: 10 * 1000,
  REJOIN_WINDOW_MS: 3 * 60 * 1000,
  MAX_FAILED_HELLOS: 8,
  LOCK_MS: 5 * 60 * 1000,
} as const;

export interface Throw {
  number: number;
  multiplier: number;
  name?: string;
  x?: number;
  y?: number;
  entry?: string;
}

export type Frame = { type: string; [key: string]: unknown };

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown, max = 200): v is string => typeof v === "string" && v.length > 0 && v.length <= max;
const isInt = (v: unknown, min: number, max: number): v is number => Number.isInteger(v) && (v as number) >= min && (v as number) <= max;

export function validName(v: unknown): v is string {
  return typeof v === "string" && v === v.trim() && v.length > 0 && v.length <= LIMITS.NAME_LENGTH;
}

function validThrow(t: unknown): string | null {
  if (!isObj(t)) return "throw must be an object";
  if (!(isInt(t.number, 0, 20) || t.number === 25)) return "throw.number must be 0 to 20 or 25";
  if (!isInt(t.multiplier, 0, 3)) return "throw.multiplier out of range";
  for (const k of ["x", "y"]) if (k in t && typeof t[k] !== "number") return `throw.${k} must be a number`;
  for (const k of ["name", "entry"]) if (k in t && typeof t[k] !== "string") return `throw.${k} must be a string`;
  return null;
}

function validThrows(v: unknown): string | null {
  if (!Array.isArray(v) || v.length > 3) return "throws must be a list of at most 3";
  for (const t of v) {
    const e = validThrow(t);
    if (e) return e;
  }
  return null;
}

const nameList = (v: unknown, min = 0): boolean =>
  Array.isArray(v) && v.length >= min && v.every(validName) && new Set(v).size === v.length;

/** null if `m` is a valid client frame, else why not. */
export function validateClientFrame(m: unknown): string | null {
  if (!isObj(m) || typeof m.type !== "string") return "frame must be an object with a type";
  switch (m.type) {
    case "hello":
      if (!isInt(m.protocol_version, 0, 1_000_000)) return "protocol_version must be an integer";
      if (m.mode !== "create" && m.mode !== "join" && m.mode !== "rejoin") return "mode must be create, join or rejoin";
      if (!validName(m.site)) return "site must be a name of up to 24 characters";
      if (!isStr(m.password, 128)) return "password is required";
      if (m.mode === "rejoin") {
        if (!isStr(m.token, 128)) return "token is required to rejoin";
        if (!isInt(m.last_seq, 0, 1_000_000)) return "last_seq must be an integer";
      }
      return null;
    case "lobby_set_players":
      return nameList(m.players) ? null : "players must be a list of unique names";
    case "lobby_start":
      if (!isInt(m.lives, 1, LIMITS.MAX_LIVES)) return "lives must be 1 to 10";
      return nameList(m.order, LIMITS.MIN_PLAYERS) ? null : "order must list the players once";
    case "dart":
      if (!isInt(m.seq, 1, 1_000_000)) return "seq must be a positive integer";
      if (!validName(m.player)) return "player must be a name";
      return validThrows(m.throws);
    case "turn": {
      if (!isInt(m.seq, 1, 1_000_000)) return "seq must be a positive integer";
      if (!validName(m.player)) return "player must be a name";
      const e = validThrows(m.throws);
      if (e) return e;
      if (m.next_player !== null && !validName(m.next_player)) return "next_player must be a name or null";
      if (!Array.isArray(m.eliminated) || !m.eliminated.every(validName)) return "eliminated must be a list of names";
      if (m.winner !== null && !validName(m.winner)) return "winner must be a name or null";
      return null;
    }
    case "ack":
      if (!isInt(m.seq, 1, 1_000_000)) return "seq must be a positive integer";
      return isStr(m.hash, 200) ? null : "hash is required";
    case "decision":
      return m.choice === "continue" || m.choice === "abort" ? null : "choice must be continue or abort";
    case "rematch":
    case "leave":
      return null;
    default:
      return `unknown frame type ${m.type}`;
  }
}

/** null if `m` is a valid relay frame, else why not. */
export function validateServerFrame(m: unknown): string | null {
  if (!isObj(m) || typeof m.type !== "string") return "frame must be an object with a type";
  const sites = (v: unknown) =>
    Array.isArray(v) && v.every((s) => isObj(s) && validName(s.site) && nameList(s.players));
  switch (m.type) {
    case "welcome":
      if (!isStr(m.code, 12) || !validName(m.site) || !isStr(m.token, 128)) return "welcome needs code, site and token";
      if (typeof m.host !== "boolean") return "host must be a boolean";
      return isStr(m.state, 20) ? null : "state is required";
    case "lobby":
      if (!validName(m.host)) return "host must be a name";
      if (!Array.isArray(m.sites) || !m.sites.every((s) => isObj(s) && validName(s.site) && nameList(s.players) && typeof s.connected === "boolean"))
        return "sites must list {site, players, connected}";
      return isInt(m.lives, 0, LIMITS.MAX_LIVES) ? null : "lives must be 0 to 10";
    case "rematch":
      return null;
    case "started":
      if (!isStr(m.match_id, 64) || !isInt(m.lives, 1, LIMITS.MAX_LIVES) || !nameList(m.order, LIMITS.MIN_PLAYERS)) return "started needs match_id, lives and order";
      return isObj(m.owners) ? null : "owners must be an object";
    case "dart":
      return validateClientFrame({ ...m, type: "dart" }) ?? (validName(m.site) ? null : "site must be a name");
    case "turn":
      return validateClientFrame({ ...m, type: "turn" }) ?? (validName(m.site) ? null : "site must be a name");
    case "turn_ok":
      return isInt(m.seq, 1, 1_000_000) ? null : "seq must be a positive integer";
    case "turn_rejected":
      return isInt(m.seq, 0, 1_000_000) && isStr(m.reason) ? null : "turn_rejected needs seq and reason";
    case "rejected":
      return isStr(m.for) && isStr(m.reason) ? null : "rejected needs for and reason";
    case "paused":
      return validName(m.site) && typeof m.rejoin_until === "number" && isStr(m.reason) ? null : "paused needs reason, site and rejoin_until";
    case "resumed":
      return validName(m.site) ? null : "site must be a name";
    case "decision_needed":
      return sites(m.sites) ? null : "sites must list {site, players}";
    case "site_dropped":
      if (!sites(m.sites)) return "sites must list {site, players}";
      return m.next_player === null || validName(m.next_player) ? null : "next_player must be a name or null";
    case "desync":
      return isInt(m.seq, 1, 1_000_000) && isObj(m.hashes) ? null : "desync needs seq and hashes";
    case "ended":
      if (m.reason !== "finished" && m.reason !== "aborted" && m.reason !== "desync") return "reason must be finished, aborted or desync";
      return Array.isArray(m.placements) && m.placements.every((p) => isObj(p) && validName(p.player) && isInt(p.placement, 1, LIMITS.MAX_PLAYERS))
        ? null : "placements must list {player, placement}";
    case "error":
      return isInt(m.code, 4000, 4999) && isStr(m.message, 300) ? null : "error needs code and message";
    default:
      return `unknown frame type ${m.type}`;
  }
}
