// The anonymous usage and error reports of Breakfast installations (see README.md, "Usage reports"):
// the shape of a batch and its validation, in plain TypeScript without Cloudflare APIs.

export const TELEMETRY_VERSION = 1;
export const TELEMETRY_LIMITS = { BODY_BYTES: 16 * 1024, EVENTS: 50, FRAMES: 8, MAX_DURATION_S: 2 * 24 * 3600, MAX_PLAYERS: 64 };

const PLATFORMS = ["docker", "windows-build", "linux", "macos", "windows", "other"];
const INSTALL_ID = /^[0-9a-f]{32}$/;
const VERSION = /^[0-9A-Za-z.+-]{1,20}$/;
const TIMESTAMP = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/;
const MODE = /^[A-Za-z0-9 _-]{1,24}$/;
const NAME = /^[A-Za-z0-9_$.]{1,40}$/;
const LANGUAGE = /^[a-z]{2,8}$/;
const FRAME = /^[\w.$-]{1,60}:\d{1,6}(:\d{1,6})?( in [\w.<>$-]{1,80})?$/;

export interface TelemetryEvent { type: string; ts: string; [field: string]: unknown }
export interface TelemetryBatch { installId: string; version: string; platform: string; events: TelemetryEvent[] }

type Check = (v: unknown) => boolean;
const text = (re: RegExp): Check => (v) => typeof v === "string" && re.test(v);
const bool: Check = (v) => typeof v === "boolean";
const int = (max: number): Check => (v) => Number.isInteger(v) && (v as number) >= 0 && (v as number) <= max;
const oneOf = (...values: string[]): Check => (v) => typeof v === "string" && values.includes(v);
const frames: Check = (v) => Array.isArray(v) && v.length <= TELEMETRY_LIMITS.FRAMES && v.every((f) => typeof f === "string" && FRAME.test(f));

// The fields of each event type besides `type` and `ts`; nothing else is accepted.
const EVENTS: Record<string, Record<string, Check>> = {
  app_start: { language: text(LANGUAGE), mqtt: bool, caller: bool, voice_pack: bool, online: bool },
  error: { source: oneOf("backend", "frontend"), exc: text(NAME), module: text(NAME), where: frames },
  game_started: { mode: text(MODE) },
  game_finished: { mode: text(MODE), duration_s: int(TELEMETRY_LIMITS.MAX_DURATION_S), players: int(TELEMETRY_LIMITS.MAX_PLAYERS) },
  game_aborted: { mode: text(MODE), duration_s: int(TELEMETRY_LIMITS.MAX_DURATION_S) },
};

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Returns the batch, or the reason it is refused. */
export function validateTelemetry(body: unknown): { batch: TelemetryBatch } | { error: string } {
  if (!isObject(body)) return { error: "not an object" };
  const extra = Object.keys(body).filter((k) => !["protocol_version", "install_id", "version", "platform", "events"].includes(k));
  if (extra.length) return { error: `unknown field ${extra[0].slice(0, 30)}` };
  if (!text(INSTALL_ID)(body.install_id)) return { error: "bad install_id" };
  if (!text(VERSION)(body.version)) return { error: "bad version" };
  if (!oneOf(...PLATFORMS)(body.platform)) return { error: "bad platform" };
  const events = body.events;
  if (!Array.isArray(events) || events.length === 0 || events.length > TELEMETRY_LIMITS.EVENTS) return { error: "bad events" };
  for (const [i, e] of events.entries()) {
    if (!isObject(e) || typeof e.type !== "string" || !(e.type in EVENTS)) return { error: `event ${i}: unknown type` };
    if (!text(TIMESTAMP)(e.ts)) return { error: `event ${i}: bad ts` };
    const fields = EVENTS[e.type];
    for (const key of Object.keys(e)) {
      if (key !== "type" && key !== "ts" && !(key in fields)) return { error: `event ${i}: unknown field ${key.slice(0, 30)}` };
    }
    for (const [key, check] of Object.entries(fields)) {
      if (!check(e[key])) return { error: `event ${i}: bad ${key}` };
    }
  }
  return { batch: { installId: body.install_id as string, version: body.version as string, platform: body.platform as string, events: events as TelemetryEvent[] } };
}
