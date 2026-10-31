// Message shapes of protocol version 4 (see ../PROTOCOL.md) and their validation.
// Both the Worker and the Python client check their frames against the examples in
// ../protocol-tests/messages.json.

export const PROTOCOL_VERSION = 4;

export const GAMES = ["elimination", "x01"] as const;
export type Game = (typeof GAMES)[number];
export const X01_MODES = ["straight", "double", "master"] as const;

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
  X01_START_MIN: 2,
  X01_START_MAX: 1501,
  X01_MAX_LEGS: 25,
  X01_MAX_ROUNDS: 99,
  NAME_LENGTH: 24,
  CODE_LENGTH: 6,
  CODE_ALPHABET: "ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
  CODE_TTL_MS: 10 * 60 * 1000,
  HELLO_TIMEOUT_MS: 10 * 1000,
  REJOIN_WINDOW_MS: 3 * 60 * 1000,
  MAX_FAILED_HELLOS: 8,
  LOCK_MS: 5 * 60 * 1000,
  TICKET_TTL_MS: 2 * 60 * 1000,
  MAX_TICKETS: 10,
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

/** The rules of an X01 match as the host sets them in the lobby, or why they are not valid. */
export function validX01Rules(r: unknown): string | null {
  if (!isObj(r)) return "rules must be an object";
  if (!isInt(r.start, LIMITS.X01_START_MIN, LIMITS.X01_START_MAX)) return "start must be 2 to 1501";
  if (!X01_MODES.includes(r.in_mode as never) || !X01_MODES.includes(r.out_mode as never)) return "in_mode and out_mode must be straight, double or master";
  if (!isInt(r.legs, 1, LIMITS.X01_MAX_LEGS)) return "legs must be 1 to 25";
  if (typeof r.bull_off !== "boolean") return "bull_off must be a boolean";
  if (r.max_rounds !== null && !isInt(r.max_rounds, 1, LIMITS.X01_MAX_ROUNDS)) return "max_rounds must be null or 1 to 99";
  return null;
}

/** The game of a lobby frame and the rules that belong to it (lives for Elimination, the rules of an X01 match), or why not. */
function validGameRules(m: Record<string, unknown>): string | null {
  const game = m.game ?? "elimination";
  if (!GAMES.includes(game as never)) return "game must be elimination or x01";
  if (game === "elimination") {
    if (m.rules !== undefined && m.rules !== null) return "rules belong to x01";
    return isInt(m.lives, 1, LIMITS.MAX_LIVES) ? null : "lives must be 1 to 10";
  }
  return validX01Rules(m.rules);
}

/** null if `m` is a valid client frame, else why not. */
export function validateClientFrame(m: unknown): string | null {
  if (!isObj(m) || typeof m.type !== "string") return "frame must be an object with a type";
  switch (m.type) {
    case "hello":
      if (!isInt(m.protocol_version, 0, 1_000_000)) return "protocol_version must be an integer";
      if (m.mode !== "create" && m.mode !== "join" && m.mode !== "rejoin") return "mode must be create, join or rejoin";
      if (!validName(m.site)) return "site must be a name of up to 24 characters";
      if (m.mode === "create" && !isStr(m.password, 128)) return "password is required";
      if (m.mode === "join" && (isStr(m.password, 128) === isStr(m.ticket, 128))) return "join needs a password or a ticket";
      if (m.mode === "rejoin") {
        if (!isStr(m.token, 128)) return "token is required to rejoin";
        if (!isInt(m.last_seq, 0, 1_000_000)) return "last_seq must be an integer";
        if (!isInt(m.epoch, 0, 1_000_000)) return "epoch must be an integer";
      }
      return null;
    case "lobby_set_players":
      return nameList(m.players) ? null : "players must be a list of unique names";
    case "lobby_set_ready":
      return typeof m.ready === "boolean" ? null : "ready must be a boolean";
    case "lobby_set_rules":
      return validGameRules(m);
    case "lobby_start":
      return validGameRules(m) ?? (nameList(m.order, LIMITS.MIN_PLAYERS) ? null : "order must list the players once");
    case "dart":
      if (!isInt(m.seq, 1, 1_000_000)) return "seq must be a positive integer";
      if (!validName(m.player)) return "player must be a name";
      return validThrows(m.throws);
    case "turn":
    case "turn_corrected": {
      if (!isInt(m.seq, 1, 1_000_000)) return "seq must be a positive integer";
      if (!validName(m.player)) return "player must be a name";
      const e = validThrows(m.throws);
      if (e) return e;
      if (m.next_player !== null && !validName(m.next_player)) return "next_player must be a name or null";
      if (!Array.isArray(m.eliminated) || !m.eliminated.every(validName)) return "eliminated must be a list of names";
      if (m.winner !== null && !validName(m.winner)) return "winner must be a name or null";
      if ("total" in m && !isInt(m.total, 0, 180)) return "total must be 0 to 180";
      for (const k of ["order", "rematch_order"]) if (k in m && !nameList(m[k], LIMITS.MIN_PLAYERS)) return `${k} must list the players once`;
      return null;
    }
    case "ack":
      if (!isInt(m.seq, 1, 1_000_000)) return "seq must be a positive integer";
      return isStr(m.hash, 200) ? null : "hash is required";
    case "undo":
      return isInt(m.seq, 1, 1_000_000) ? null : "seq must be a positive integer";
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
      if (!isInt(m.epoch, 0, 1_000_000)) return "epoch must be an integer";
      return isStr(m.state, 20) ? null : "state is required";
    case "lobby":
      if (!validName(m.host)) return "host must be a name";
      if (!Array.isArray(m.sites) || !m.sites.every((s) => isObj(s) && validName(s.site) && nameList(s.players) && typeof s.connected === "boolean" && typeof s.ready === "boolean"))
        return "sites must list {site, players, connected, ready}";
      if (m.game !== undefined && !GAMES.includes(m.game as never)) return "game must be elimination or x01";
      if (m.rules !== undefined && m.rules !== null && validX01Rules(m.rules)) return "rules must be the rules of an x01 match";
      return isInt(m.lives, 0, LIMITS.MAX_LIVES) ? null : "lives must be 0 to 10";
    case "rematch":
      return null;
    case "started":
      if (!isStr(m.match_id, 64) || !nameList(m.order, LIMITS.MIN_PLAYERS)) return "started needs match_id and order";
      if (!isObj(m.owners)) return "owners must be an object";
      return validGameRules({ game: m.game, lives: m.lives, rules: m.rules });
    case "dart":
      return validateClientFrame({ ...m, type: "dart" }) ?? (validName(m.site) ? null : "site must be a name");
    case "turn":
      return validateClientFrame({ ...m, type: "turn" }) ?? (validName(m.site) ? null : "site must be a name");
    case "turn_corrected":
      return validateClientFrame({ ...m, type: "turn_corrected" }) ?? (validName(m.site) && isInt(m.epoch, 1, 1_000_000) ? null : "turn_corrected needs site and epoch");
    case "turn_ok":
      if ("epoch" in m && !isInt(m.epoch, 1, 1_000_000)) return "epoch must be a positive integer";
      return isInt(m.seq, 1, 1_000_000) ? null : "seq must be a positive integer";
    case "turn_rejected":
      return isInt(m.seq, 0, 1_000_000) && isStr(m.reason) ? null : "turn_rejected needs seq and reason";
    case "rejected":
      return isStr(m.for) && isStr(m.reason) ? null : "rejected needs for and reason";
    case "undone":
      return isInt(m.seq, 1, 1_000_000) && validName(m.player) && validName(m.site) && isInt(m.epoch, 1, 1_000_000)
        ? null : "undone needs seq, player, site and epoch";
    case "undo_rejected":
      return isInt(m.seq, 0, 1_000_000) && isStr(m.reason) ? null : "undo_rejected needs seq and reason";
    case "resync":
      return null;
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
