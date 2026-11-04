import { beforeEach, describe, expect, it } from "vitest";
import { CircleEnv } from "../src/circle";
import { handleCircleShared, SHARED_LIMITS } from "../src/circle_shared";
import { FakeD1, FakeR2, newLocation, signed, Site } from "./support";

const NOW = 1_760_000_000_000;
let t = NOW;
let env: CircleEnv & { DB: FakeD1; RECORDS: FakeR2 };
let refuseLimit = false;
const limited = async () => refuseLimit;

async function call(site: Site, method: string, path: string, body?: unknown) {
  const response = await handleCircleShared(await signed(site, method, path, t, body), env, limited, t);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

let a: Site, b: Site, c: Site, unapproved: Site;

// The "mp3" is plain ASCII so the in-memory bucket of the tests keeps it byte for byte.
async function mp3(text: string) {
  const bytes = new TextEncoder().encode("ID3" + text);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return { bytes, hash: [...digest].map((x) => x.toString(16).padStart(2, "0")).join(""), data: btoa("ID3" + text) };
}
const upload = async (site: Site, text: string) => {
  const m = await mp3(text);
  const r = await call(site, "PUT", `/circle/sounds/${m.hash}`, { data: m.data });
  return { ...m, r };
};
const graph = { nodes: [{ id: "n1", type: "trigger", x: 0, y: 0, event: "x01.leg_won" }], edges: [] };

beforeEach(async () => {
  env = { DB: new FakeD1(), RECORDS: new FakeR2() } as never;
  t = NOW;
  refuseLimit = false;
  [a, b, c, unapproved] = [await newLocation(env.DB, 1, "Alpha"), await newLocation(env.DB, 2, "Bravo"), await newLocation(env.DB, 3, "Charlie"), await newLocation(env.DB, 4, "Delta")];
  for (const s of [a, b, c]) await env.DB.prepare("INSERT INTO circle_sites (location_id, approved, approved_at) VALUES (?, 1, ?)").bind(s.id, NOW).run();
});

describe("sounds", () => {
  it("stores a sound once per hash and hands it out", async () => {
    const first = await upload(a, "one");
    expect(first.r.status).toBe(201);
    expect((await upload(b, "one")).r.status).toBe(200);
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_sounds")).toBe(1);
    const got = await call(c, "GET", `/circle/sounds/${first.hash}`);
    expect(got.status).toBe(200);
    expect(got.body.data).toBe(first.data);
  });

  it("refuses a wrong hash, a file that is no mp3, too large and not base64", async () => {
    const m = await mp3("one");
    expect((await call(a, "PUT", `/circle/sounds/${"0".repeat(64)}`, { data: m.data })).status).toBe(400);
    const text = btoa("hello world");
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("hello world")));
    const hex = [...digest].map((x) => x.toString(16).padStart(2, "0")).join("");
    expect((await call(a, "PUT", `/circle/sounds/${hex}`, { data: text })).status).toBe(400);
    expect((await call(a, "PUT", `/circle/sounds/${m.hash}`, { data: "***" })).status).toBe(400);
    const big = "ID3" + "a".repeat(SHARED_LIMITS.SOUND_BYTES);
    const bigHash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(big)))].map((x) => x.toString(16).padStart(2, "0")).join("");
    expect((await call(a, "PUT", `/circle/sounds/${bigHash}`, { data: btoa(big) })).status).toBe(413);
  });

  it("answers 404 for an unknown sound and 403 for a site the admin has not approved", async () => {
    expect((await call(a, "GET", `/circle/sounds/${"1".repeat(64)}`)).status).toBe(404);
    const m = await mp3("one");
    expect((await call(unapproved, "PUT", `/circle/sounds/${m.hash}`, { data: m.data })).status).toBe(403);
  });
});

describe("scenes", () => {
  const scene = (sounds: unknown[] = [], extra: Record<string, unknown> = {}) => ({ name: "Cheer", graph, sounds, ...extra });

  it("publishes a scene that the other sites list, not its author", async () => {
    const s = await upload(a, "one");
    const put = await call(a, "PUT", "/circle/scenes/scene-0001", scene([{ file: "cheer.mp3", hash: s.hash }]));
    expect(put.status).toBe(201);
    const seen = await call(b, "GET", "/circle/scenes?since=0");
    expect(seen.body.scenes).toHaveLength(1);
    expect(seen.body.scenes[0]).toMatchObject({ scene_id: "scene-0001", name: "Cheer", origin: { id: a.id, name: "Alpha" }, deleted: false, sounds: [{ file: "cheer.mp3", hash: s.hash }] });
    expect(seen.body.next).toBe(seen.body.scenes[0].seq);
    expect((await call(a, "GET", "/circle/scenes?since=0")).body.scenes).toHaveLength(0);
  });

  it("refuses sounds that were not uploaded, with the missing hashes", async () => {
    const hash = "a".repeat(64);
    const put = await call(a, "PUT", "/circle/scenes/scene-0001", scene([{ file: "x.mp3", hash }]));
    expect(put.status).toBe(422);
    expect(put.body.missing).toEqual([hash]);
  });

  it("gives a changed scene a new seq, keeps an unchanged one and lets only the author change it", async () => {
    const first = await call(a, "PUT", "/circle/scenes/scene-0001", scene());
    const same = await call(a, "PUT", "/circle/scenes/scene-0001", scene());
    expect(same.body.seq).toBe(first.body.seq);
    const changed = await call(a, "PUT", "/circle/scenes/scene-0001", scene([], { name: "Cheer 2" }));
    expect(changed.status).toBe(200);
    expect(changed.body.seq).toBeGreaterThan(first.body.seq);
    const list = (await call(b, "GET", `/circle/scenes?since=${first.body.seq}`)).body.scenes;
    expect(list).toHaveLength(1);
    expect(list[0].name).toBe("Cheer 2");
    // the same id from another site is a scene of its own
    await call(b, "PUT", "/circle/scenes/scene-0001", scene([], { name: "Other" }));
    expect((await call(c, "GET", "/circle/scenes?since=0")).body.scenes.map((s: any) => s.name).sort()).toEqual(["Cheer 2", "Other"]);
  });

  it("marks a deleted scene so the copies go, and forgets a delete of a scene it never had", async () => {
    await call(a, "PUT", "/circle/scenes/scene-0001", scene());
    expect((await call(a, "PUT", "/circle/scenes/scene-0001", { deleted: true })).status).toBe(200);
    const list = (await call(b, "GET", "/circle/scenes?since=0")).body.scenes;
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ deleted: true, name: "" });
    expect((await call(a, "PUT", "/circle/scenes/scene-0002", { deleted: true })).body.seq).toBe(0);
    expect((await call(b, "GET", "/circle/scenes?since=0")).body.scenes).toHaveLength(1);
  });

  it("checks the id, the name, the graph, the sound list and the size", async () => {
    expect((await call(a, "PUT", "/circle/scenes/x", scene())).status).toBe(400);
    expect((await call(a, "PUT", "/circle/scenes/scene-0001", scene([], { name: "" }))).status).toBe(400);
    expect((await call(a, "PUT", "/circle/scenes/scene-0001", scene([], { graph: [] }))).status).toBe(400);
    expect((await call(a, "PUT", "/circle/scenes/scene-0001", scene([{ file: "../x.mp3", hash: "a".repeat(64) }]))).status).toBe(400);
    const huge = { nodes: [{ id: "n", text: "x".repeat(SHARED_LIMITS.SCENE_BYTES) }], edges: [] };
    expect((await call(a, "PUT", "/circle/scenes/scene-0001", scene([], { graph: huge }))).status).toBe(413);
  });

  it("limits the shared scenes per site and the request rate", async () => {
    for (let i = 0; i < SHARED_LIMITS.SCENES_PER_SITE; i++) {
      env.DB.db.exec(`INSERT INTO circle_scenes (scene_id, origin, name, graph, sounds, updated_at) VALUES ('s${i}', '${a.id}', 'n', '{}', '[]', 1)`);
    }
    expect((await call(a, "PUT", "/circle/scenes/scene-0001", scene())).status).toBe(429);
    refuseLimit = true;
    expect((await call(b, "GET", "/circle/scenes?since=0")).status).toBe(429);
  });

  it("pages by the cursor", async () => {
    for (const n of [1, 2, 3]) await call(a, "PUT", `/circle/scenes/scene-000${n}`, scene([], { name: `S${n}` }));
    const first = (await call(b, "GET", "/circle/scenes?since=0&limit=2")).body;
    expect(first.scenes.map((s: any) => s.name)).toEqual(["S1", "S2"]);
    const rest = (await call(b, "GET", `/circle/scenes?since=${first.next}&limit=2`)).body;
    expect(rest.scenes.map((s: any) => s.name)).toEqual(["S3"]);
    expect((await call(b, "GET", `/circle/scenes?since=${rest.next}`)).body.scenes).toEqual([]);
  });
});

describe("achievement sounds", () => {
  it("publishes, changes and removes the sounds of an achievement", async () => {
    const s1 = await upload(a, "one");
    const s2 = await upload(a, "two");
    const put = await call(a, "PUT", "/circle/achievement-sounds/ton_up", { files: [{ file: "fanfare.mp3", hash: s1.hash }] });
    expect(put.status).toBe(201);
    let list = (await call(b, "GET", "/circle/achievement-sounds?since=0")).body;
    expect(list.sounds[0]).toMatchObject({ achievement: "ton_up", files: [{ file: "fanfare.mp3", hash: s1.hash }], deleted: false, origin: { name: "Alpha" } });
    await call(a, "PUT", "/circle/achievement-sounds/ton_up", { files: [{ file: "fanfare.mp3", hash: s1.hash }, { file: "drum.mp3", hash: s2.hash }] });
    list = (await call(b, "GET", `/circle/achievement-sounds?since=${list.next}`)).body;
    expect(list.sounds).toHaveLength(1);
    expect(list.sounds[0].files).toHaveLength(2);
    await call(a, "PUT", "/circle/achievement-sounds/ton_up", { deleted: true });
    list = (await call(b, "GET", `/circle/achievement-sounds?since=${list.next}`)).body;
    expect(list.sounds[0]).toMatchObject({ deleted: true, files: [] });
    expect((await call(a, "GET", "/circle/achievement-sounds?since=0")).body.sounds).toHaveLength(0);
  });

  it("refuses bad ids, empty or unknown files", async () => {
    expect((await call(a, "PUT", "/circle/achievement-sounds/Bad-Id", { files: [] })).status).toBe(400);
    expect((await call(a, "PUT", "/circle/achievement-sounds/ton_up", { files: [] })).status).toBe(400);
    const r = await call(a, "PUT", "/circle/achievement-sounds/ton_up", { files: [{ file: "x.mp3", hash: "b".repeat(64) }] });
    expect(r.status).toBe(422);
  });
});

describe("switches", () => {
  it("answers 503 when sharing is off or the stores are missing and null for other routes", async () => {
    env.SHARING = "off";
    expect((await call(a, "GET", "/circle/scenes")).status).toBe(503);
    env.SHARING = undefined;
    const other = await handleCircleShared(await signed(a, "GET", "/circle/records", t), env, limited, t);
    expect(other).toBeNull();
  });
});
