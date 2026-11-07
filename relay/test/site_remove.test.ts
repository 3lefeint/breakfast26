import { beforeEach, describe, expect, it } from "vitest";
import { AdminEnv, handleAdmin, makeToken } from "../src/admin";
import { authenticate } from "../src/locations";
import { FakeD1, FakeR2, id, newLocation, signed } from "./support";

const NOW = 1_760_000_000_000;
const KEY = "k".repeat(64);
const HASH_OWN = "a".repeat(64);
const HASH_SHARED = "b".repeat(64);
let db: FakeD1;
let r2: FakeR2;
let env: AdminEnv & { DB: FakeD1 };
let token: string;

async function remove(site: string) {
  const response = await handleAdmin(new Request(`https://relay.test/admin/sites/${site}/remove`, { method: "POST", headers: { authorization: `Bearer ${token}` }, body: "{}" }),
    env, async () => false, NOW);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

const count = (table: string, where = "1 = 1", ...params: unknown[]) => db.count(`SELECT COUNT(*) AS n FROM ${table} WHERE ${where}`, ...params);

async function fill(site: string, tag: string) {
  await db.prepare("INSERT INTO circle_sites (location_id, approved, approved_at) VALUES (?, 1, ?)").bind(site, NOW).run();
  await db.prepare("INSERT INTO circle_records (match_id, revision, origin, game_mode, size, hash, players, created_at) VALUES (?, 1, ?, 'X01', 1, 'h', '[]', ?)").bind(`m-${tag}`, site, NOW).run();
  await r2.put(`circle/m-${tag}`, "{}");
  await db.prepare("INSERT INTO circle_scenes (scene_id, origin, name, graph, sounds, updated_at) VALUES (?, ?, 'S', '{}', '[]', ?)").bind(`scene-${tag}-xx`, site, NOW).run();
  await db.prepare("INSERT INTO circle_achievement_sounds (achievement, origin, files, updated_at) VALUES ('first_win', ?, '[]', ?)").bind(site, NOW).run();
}

beforeEach(async () => {
  db = new FakeD1();
  r2 = new FakeR2();
  env = { DB: db, RECORDS: r2, ADMIN_PASSWORD_HASH: "x", ADMIN_TOKEN_KEY: KEY } as never;
  token = await makeToken(KEY, NOW + 3_600_000);
});

describe("removing a site", () => {
  it("deletes what the site left on the relay and keeps what belongs to the others", async () => {
    const gone = await newLocation(db, 1, "Gone");
    const stays = await newLocation(db, 2, "Stays");
    const third = await newLocation(db, 3, "Third");
    await fill(gone.id, "gone");
    await fill(stays.id, "stays");
    await db.prepare("INSERT INTO circle_mappings (location_id, local_name, player_id) VALUES (?, 'anna', 'p1')").bind(gone.id).run();
    await db.prepare("INSERT INTO circle_rules (player_id, location_id) VALUES ('p1', ?)").bind(gone.id).run();
    await db.prepare("INSERT INTO voice_channels (id, name, created_at) VALUES (?, 'Main', ?)").bind(id(50), NOW).run();
    await db.prepare("INSERT INTO voice_channel_sites (channel_id, location_id) VALUES (?, ?)").bind(id(50), gone.id).run();
    await db.prepare("INSERT INTO links (id, location_a, location_b, source) VALUES (?, ?, ?, 'admin')").bind(id(60), gone.id, stays.id).run();
    await db.prepare("INSERT INTO links (id, location_a, location_b) VALUES (?, ?, ?)").bind(id(61), third.id, gone.id).run();
    await db.prepare("INSERT INTO links (id, location_a, location_b) VALUES (?, ?, ?)").bind(id(62), stays.id, third.id).run();
    await db.prepare("INSERT INTO invitations (token_hash, location_id, expires_at) VALUES ('t', ?, ?)").bind(gone.id, NOW + 1000).run();
    await db.prepare("INSERT INTO open_matches (code, location_id, site, created_at, expires_at) VALUES ('ABC234', ?, 'x', ?, ?)").bind(gone.id, NOW, NOW + 1000).run();

    expect(await remove(gone.id)).toEqual({ status: 200, body: { ok: true, deleted: true } });

    expect(count("locations", "id = ?", gone.id)).toBe(0);
    for (const [table, column] of [["circle_sites", "location_id"], ["circle_mappings", "location_id"], ["circle_rules", "location_id"], ["circle_records", "origin"],
      ["circle_scenes", "origin"], ["circle_achievement_sounds", "origin"], ["voice_channel_sites", "location_id"], ["invitations", "location_id"], ["open_matches", "location_id"]]) {
      expect(count(table, `${column} = ?`, gone.id), table).toBe(0);
    }
    expect(count("links")).toBe(1);                                    // only the pair that does not involve the removed site
    expect([...r2.objects.keys()]).toEqual(["circle/m-stays"]);
    expect(count("circle_records")).toBe(1);
    expect(count("circle_scenes")).toBe(1);
    expect(count("circle_achievement_sounds")).toBe(1);
    expect(count("locations")).toBe(2);
  });

  it("deletes the sound files of the site, but not one that a scene of another site still names", async () => {
    const gone = await newLocation(db, 1);
    const stays = await newLocation(db, 2);
    for (const hash of [HASH_OWN, HASH_SHARED]) {
      await db.prepare("INSERT INTO circle_sounds (hash, size, origin, created_at) VALUES (?, 1, ?, ?)").bind(hash, gone.id, NOW).run();
      await r2.put(`sounds/${hash}`, "mp3");
    }
    await db.prepare("INSERT INTO circle_scenes (scene_id, origin, name, graph, sounds, updated_at) VALUES ('scene-stays-xx', ?, 'S', '{}', ?, ?)")
      .bind(stays.id, JSON.stringify([{ file: "a.mp3", hash: HASH_SHARED }]), NOW).run();
    expect((await remove(gone.id)).status).toBe(200);
    expect([...r2.objects.keys()]).toEqual([`sounds/${HASH_SHARED}`]);
    expect(count("circle_sounds")).toBe(1);
  });

  it("deletes nothing in the database when the files cannot be deleted, so that a retry works", async () => {
    const gone = await newLocation(db, 1);
    await fill(gone.id, "gone");
    const failing = { delete: async () => { throw new Error("R2 is down"); } };
    env.RECORDS = failing as never;
    const result = await remove(gone.id);
    expect(result.status).toBe(500);
    expect(count("locations")).toBe(1);
    expect(count("circle_records")).toBe(1);
    expect(count("circle_sites")).toBe(1);
    env.RECORDS = r2 as never;
    expect((await remove(gone.id)).status).toBe(200);
    expect(count("locations")).toBe(0);
    expect(r2.objects.size).toBe(0);
  });
});

describe("a location that was removed", () => {
  it("is answered with unknown_location, a bad signature is not", async () => {
    const site = await newLocation(db, 1);
    const ok = await authenticate(await signed(site, "GET", `/locations/${site.id}/links`, NOW), { DB: db as never }, "", NOW);
    expect(ok).toEqual({ id: site.id });
    await remove(site.id);
    const gone = await authenticate(await signed(site, "GET", `/locations/${site.id}/links`, NOW), { DB: db as never }, "", NOW) as Response;
    expect(gone.status).toBe(401);
    expect(await gone.json()).toEqual({ error: "unknown location", code: "unknown_location" });
    const bad = await authenticate(new Request("https://relay.test/x", { headers: { "x-location": site.id, "x-timestamp": "1", "x-signature": "x" } }), { DB: db as never }, "", NOW) as Response;
    expect(await bad.json()).toEqual({ error: "not signed correctly" });
  });
});
