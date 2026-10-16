import { describe, expect, it } from "vitest";
import { validateTelemetry } from "../src/telemetry";

const base = { protocol_version: 1, install_id: "a".repeat(32), version: "1.4.0", platform: "docker" };
const ts = "2026-10-16T12:00:00Z";
const batch = (...events: unknown[]) => ({ ...base, events });
const refused = (body: unknown) => "error" in validateTelemetry(body);

describe("telemetry batches", () => {
  it("accepts every event type", () => {
    const res = validateTelemetry(batch(
      { type: "app_start", ts, language: "de", mqtt: true, caller: true, voice_pack: false, online: false },
      { type: "error", ts, source: "backend", exc: "KeyError", module: "breakfast.x01_game", where: ["x01_game.py:12 in start"] },
      { type: "error", ts, source: "frontend", exc: "TypeError", module: "frontend", where: ["index-ab.js:1:99"] },
      { type: "game_started", ts, mode: "x01" },
      { type: "game_finished", ts, mode: "elimination", duration_s: 600, players: 3 },
      { type: "game_aborted", ts, mode: "killer", duration_s: 20 },
    ));
    expect("batch" in res && res.batch.events.length).toBe(6);
  });

  it("refuses unknown fields, types and values", () => {
    expect(refused({ ...batch({ type: "game_started", ts, mode: "x01" }), extra: 1 })).toBe(true);
    expect(refused(batch({ type: "game_started", ts, mode: "x01", player: "anna" }))).toBe(true);
    expect(refused(batch({ type: "player_seen", ts }))).toBe(true);
    expect(refused(batch({ type: "game_started", ts, mode: "anna's game" }))).toBe(true);
    expect(refused(batch({ type: "game_finished", ts, mode: "x01", duration_s: -1, players: 2 }))).toBe(true);
    expect(refused(batch({ type: "game_finished", ts, mode: "x01", duration_s: 1.5, players: 2 }))).toBe(true);
    expect(refused(batch({ type: "error", ts, source: "backend", exc: "KeyError", module: "m", where: ["/home/anna/x.py:1 in f"] }))).toBe(true);
    expect(refused(batch({ type: "game_started", ts: "yesterday", mode: "x01" }))).toBe(true);
  });

  it("refuses a bad envelope", () => {
    const ok = batch({ type: "game_started", ts, mode: "x01" });
    expect(refused({ ...ok, install_id: "short" })).toBe(true);
    expect(refused({ ...ok, platform: "toaster" })).toBe(true);
    expect(refused({ ...ok, version: "1.4.0; DROP" })).toBe(true);
    expect(refused({ ...ok, events: [] })).toBe(true);
    expect(refused({ ...ok, events: Array(51).fill({ type: "game_started", ts, mode: "x01" }) })).toBe(true);
    expect(refused("text")).toBe(true);
    expect(refused(null)).toBe(true);
  });
});
