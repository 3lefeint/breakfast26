import { beforeEach, describe, expect, it } from "vitest";
import { CIRCLE_LIMITS, CircleEnv, dropSite, handleCircle, resolvePlayers } from "../src/circle";
import { FakeD1, FakeR2, id, newLocation, signed, Site } from "./support";

const NOW = 1_760_000_000_000;
let t = NOW;
let env: CircleEnv & { DB: FakeD1; RECORDS: FakeR2 };
let limitedCalls: string[] = [];
let refuseLimit = false;
const limited = async (purpose: string) => { limitedCalls.push(purpose); return refuseLimit; };

async function call(site: Site | null, method: string, path: string, body?: unknown) {
  const response = await handleCircle(await signed(site, method, path, t, body), env, limited, t);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

let ashitaka: Site, streemo: Site, meierhof: Site, crealine: Site;
let ashi: string, timo: string, peter: string;

/** Four approved sites, three circle players, mappings and rules: Ashi goes to Ashitaka's and Streemo's board and Meierhof. */
async function circle() {
  ashitaka = await newLocation(env.DB, 1, "Ashitaka's Board");
  streemo = await newLocation(env.DB, 2, "Streemo's Board");
  meierhof = await newLocation(env.DB, 3, "Meierhof");
  crealine = await newLocation(env.DB, 4, "Crealine");
  for (const s of [ashitaka, streemo, meierhof, crealine]) {
    await env.DB.prepare("INSERT INTO circle_sites (location_id, approved, approved_at) VALUES (?, 1, ?)").bind(s.id, NOW).run();
  }
  [ashi, timo, peter] = [id(101), id(102), id(103)];
  for (const [pid, name] of [[ashi, "Ashi"], [timo, "Timo"], [peter, "Peter"]]) {
    await env.DB.prepare("INSERT INTO circle_players (id, name, created_at) VALUES (?, ?, ?)").bind(pid, name, NOW).run();
  }
  const map = (site: Site, local: string, player: string) =>
    env.DB.prepare("INSERT INTO circle_mappings (location_id, local_name, player_id) VALUES (?, ?, ?)").bind(site.id, local, player).run();
  await map(ashitaka, "ashi", ashi);
  await map(streemo, "timo", timo);
  await map(meierhof, "peter", peter);
  await map(meierhof, "ashi", ashi);                      // Ashi is also a player at Meierhof
  const rule = (player: string, ...sites: Site[]) => Promise.all(sites.map((s) =>
    env.DB.prepare("INSERT INTO circle_rules (player_id, location_id) VALUES (?, ?)").bind(player, s.id).run()));
  await rule(ashi, ashitaka, streemo, meierhof);
  await rule(timo, streemo, ashitaka);
  await rule(peter, meierhof);
}

const doc = (matchId: string, revision = 1, extra: Record<string, unknown> = {}) =>
  ({ record_version: 1, game_mode: "X01", match_id: matchId, revision, deleted: false, origin: { id: "x" }, ...extra });
const put = (site: Site, matchId: string, participants: unknown[], revision = 1, extra: Record<string, unknown> = {}, docExtra: Record<string, unknown> = {}) =>
  call(site, "PUT", `/circle/records/${matchId}/${revision}`, { game_mode: "X01", deleted: false, participants, record: doc(matchId, revision, docExtra), ...extra });

beforeEach(async () => {
  t = NOW;
  limitedCalls = [];
  refuseLimit = false;
  env = { DB: new FakeD1(), RECORDS: new FakeR2() } as never;
  await circle();
});

describe("the profile of a circle player", () => {
  const profile = (site: Site, ...players: unknown[]) => call(site, "PUT", "/circle/profile", { players });
  const fields = (res: Record<string, any>, player: string) =>
    Object.fromEntries(res.body.profiles.filter((f: any) => f.player_id === player).map((f: any) => [f.field, [f.value, f.at]]));

  it("takes the color and the voice entry of a player and hands them to every site that maps him", async () => {
    const res = await profile(ashitaka, { name: "Ashi", color: "#ff8800", voice: { ryan: { variants: ["Ashi", "Ashie"] } } });
    expect(res).toEqual({ status: 200, body: { updated: 2 } });
    const seen = fields(await call(meierhof, "GET", "/circle/config"), ashi);   // Ashi is a player at Meierhof too
    expect(seen).toEqual({ color: ["#ff8800", NOW], "voice:ryan": [{ variants: ["Ashi", "Ashie"] }, NOW] });
    expect((await call(streemo, "GET", "/circle/config")).body.profiles).toEqual([]);   // Streemo's board maps no Ashi
  });

  it("the latest change wins and the time only moves with a change", async () => {
    await profile(ashitaka, { name: "ashi", color: "#ff8800" });
    t += 1000;
    expect((await profile(meierhof, { name: "ashi", color: "#ff8800" })).body.updated).toBe(0);
    expect(fields(await call(ashitaka, "GET", "/circle/config"), ashi).color).toEqual(["#ff8800", NOW]);
    t += 1000;
    expect((await profile(meierhof, { name: "ashi", color: "#00aa00" })).body.updated).toBe(1);
    expect(fields(await call(ashitaka, "GET", "/circle/config"), ashi).color).toEqual(["#00aa00", NOW + 2000]);
  });

  it("a cleared field is told as null", async () => {
    await profile(ashitaka, { name: "ashi", color: "#ff8800", voice: { ryan: { variants: ["Ashi"] } } });
    t += 1000;
    await profile(ashitaka, { name: "ashi", color: null, voice: { ryan: null } });
    expect(fields(await call(ashitaka, "GET", "/circle/config"), ashi)).toEqual({ color: [null, NOW + 1000], "voice:ryan": [null, NOW + 1000] });
  });

  it("ignores a player the admin has not mapped and refuses what is not a profile", async () => {
    expect((await profile(ashitaka, { name: "stranger", color: "#ff8800" })).body.updated).toBe(0);
    for (const bad of [{ name: "ashi", color: "red" }, { name: "ashi", voice: { ryan: { variants: [] } } },
        { name: "ashi", voice: { "Bad Pack": { variants: ["x"] } } }, { name: "ashi", voice: { ryan: { variants: ["x".repeat(101)] } } }]) {
      expect((await profile(ashitaka, bad)).status).toBe(400);
    }
    expect((await call(ashitaka, "PUT", "/circle/profile", { players: [] })).status).toBe(400);
    expect((await profile(await newLocation(env.DB, 9), { name: "ashi", color: "#ff8800" })).status).toBe(403);
  });
});

describe("the state a site reports", () => {
  it("a site that is not approved yet can report and is told so", async () => {
    const newcomer = await newLocation(env.DB, 9, "Newcomer");
    const res = await call(newcomer, "PUT", "/circle/state", { version: "1.9.0", players: ["Anna", "ben", "anna"], state: { last_pull: "now" } });
    expect(res.body).toEqual({ approved: false });
    const row = env.DB.db.prepare("SELECT approved, version, players, state, last_seen FROM circle_sites WHERE location_id = ?").get(newcomer.id) as any;
    expect(row).toMatchObject({ approved: 0, version: "1.9.0", players: '["anna","ben"]', last_seen: NOW });
    expect(JSON.parse(row.state)).toEqual({ last_pull: "now" });
  });

  it("an approved site keeps its approval when it reports again", async () => {
    expect((await call(ashitaka, "PUT", "/circle/state", { players: ["ashi"] })).body).toEqual({ approved: true });
    expect(env.DB.count("SELECT approved AS n FROM circle_sites WHERE location_id = ?", ashitaka.id)).toBe(1);
  });

  it("refuses what is not a list of names, a bad version and a big state", async () => {
    expect((await call(ashitaka, "PUT", "/circle/state", { players: "ashi" })).status).toBe(400);
    expect((await call(ashitaka, "PUT", "/circle/state", { players: [5] })).status).toBe(400);
    expect((await call(ashitaka, "PUT", "/circle/state", { players: [], version: "bad version!" })).status).toBe(400);
    expect((await call(ashitaka, "PUT", "/circle/state", { players: [], state: { x: "y".repeat(CIRCLE_LIMITS.STATE_BYTES) } })).status).toBe(400);
    expect((await call(null, "PUT", "/circle/state", { players: [] })).status).toBe(401);
  });
});

describe("what a site may do", () => {
  it("an unapproved site gets nothing else", async () => {
    const newcomer = await newLocation(env.DB, 9);
    for (const [method, path, body] of [["GET", "/circle/config"], ["GET", "/circle/records"], ["GET", "/circle/records/m-1"], ["PUT", "/circle/records/m-1/1", {}]] as const) {
      expect((await call(newcomer, method, path, body)).status).toBe(403);
    }
  });

  it("the config tells the circle players with their sites and the mappings of this site", async () => {
    const res = await call(meierhof, "GET", "/circle/config");
    expect(res.body.approved).toBe(true);
    expect(res.body.circle_players.map((p: any) => [p.name, p.sites.map((s: any) => s.name).sort()])).toEqual([
      ["Ashi", ["Ashitaka's Board", "Meierhof", "Streemo's Board"]], ["Peter", ["Meierhof"]], ["Timo", ["Ashitaka's Board", "Streemo's Board"]]]);
    expect(res.body.mappings).toEqual([{ local_name: "ashi", player_id: ashi }, { local_name: "peter", player_id: peter }]);
    expect(res.body.refetch).toBe(0);
    expect(res.body.site_mappings.map((m: any) => [m.location_name, m.local_name, m.player_id])).toEqual([
      ["Ashitaka's Board", "ashi", ashi], ["Meierhof", "ashi", ashi], ["Meierhof", "peter", peter], ["Streemo's Board", "timo", timo]]);
  });

  it("answers 503 while the circle is off or without a bucket", async () => {
    env.SHARING = "off";
    expect((await call(ashitaka, "GET", "/circle/config")).status).toBe(503);
    env.SHARING = undefined;
    const saved = env.RECORDS;
    (env as { RECORDS?: FakeR2 }).RECORDS = undefined;
    expect((await call(ashitaka, "GET", "/circle/config")).status).toBe(503);
    env.RECORDS = saved;
    expect(await handleCircle(new Request("https://relay.test/other"), env, limited, t)).toBeNull();
  });
});

describe("putting a record", () => {
  it("stores the record as plain JSON and the circle players in it", async () => {
    const res = await put(ashitaka, "m-1", [{ name: "Ashi" }, { name: "stranger" }]);
    expect(res.status).toBe(201);
    expect(JSON.parse(env.RECORDS.objects.get("circle/m-1")!)).toMatchObject({ match_id: "m-1", revision: 1 });
    const row = env.DB.db.prepare("SELECT origin, revision, players, deleted FROM circle_records WHERE match_id = 'm-1'").get() as any;
    expect(row).toMatchObject({ origin: ashitaka.id, revision: 1, players: JSON.stringify([ashi]), deleted: 0 });
  });

  it("finds the circle player of a guest of another site through the mapping of that site, by the name of the site", async () => {
    await put(crealine, "m-2", [{ name: "hannes" }, { name: "ashi", origin: "ashitaka's board" }]);
    expect((env.DB.db.prepare("SELECT players FROM circle_records WHERE match_id = 'm-2'").get() as any).players).toBe(JSON.stringify([ashi]));
    expect(await resolvePlayers(env.DB as never, crealine.id, [{ name: "timo", origin: "nowhere" }, { name: "peter", origin: "Meierhof" }])).toEqual([peter]);
  });

  it("refuses a match without a circle player", async () => {
    const res = await put(crealine, "m-3", [{ name: "hannes" }, { name: "eric" }]);
    expect(res.status).toBe(422);
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_records")).toBe(0);
  });

  it("the same record again changes nothing, other content for the same revision is refused, an older one too", async () => {
    const first = await put(ashitaka, "m-1", [{ name: "ashi" }]);
    expect((await put(ashitaka, "m-1", [{ name: "ashi" }])).body.seq).toBe(first.body.seq);
    expect((await put(ashitaka, "m-1", [{ name: "ashi" }], 1, {}, { note: "other" })).status).toBe(409);
    await put(ashitaka, "m-1", [{ name: "ashi" }], 2);
    expect((await put(ashitaka, "m-1", [{ name: "ashi" }], 1)).status).toBe(409);
  });

  it("a newer revision replaces the record and gets a new place in the order", async () => {
    const first = await put(ashitaka, "m-1", [{ name: "ashi" }]);
    const second = await put(ashitaka, "m-1", [{ name: "ashi" }], 2, {}, { note: "changed" });
    expect(second.body.seq).toBeGreaterThan(first.body.seq);
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_records")).toBe(1);
    expect(JSON.parse(env.RECORDS.objects.get("circle/m-1")!).note).toBe("changed");
  });

  it("only the site that played a match changes it", async () => {
    await put(ashitaka, "m-1", [{ name: "ashi" }]);
    expect((await put(meierhof, "m-1", [{ name: "ashi" }], 2)).status).toBe(403);
  });

  it("takes a deletion record like any other", async () => {
    await put(ashitaka, "m-1", [{ name: "ashi" }]);
    const res = await call(ashitaka, "PUT", "/circle/records/m-1/2", {
      game_mode: "X01", deleted: true, participants: [{ name: "ashi" }], record: { record_version: 1, game_mode: "X01", match_id: "m-1", revision: 2, deleted: true } });
    expect(res.status).toBe(201);
    expect((env.DB.db.prepare("SELECT deleted FROM circle_records WHERE match_id = 'm-1'").get() as any).deleted).toBe(1);
  });

  it("refuses a record that does not fit its address, bad parts and a record that is too big", async () => {
    const bad = (extra: Record<string, unknown>, matchId = "m-1", revision = 1) => call(ashitaka, "PUT", `/circle/records/${matchId}/${revision}`,
      { game_mode: "X01", deleted: false, participants: [{ name: "ashi" }], record: doc(matchId, revision), ...extra });
    expect((await bad({ record: doc("m-9") })).status).toBe(400);
    expect((await bad({ record: doc("m-1", 2) })).status).toBe(400);
    expect((await bad({ game_mode: "Cricket" })).status).toBe(400);
    expect((await bad({ deleted: "no" })).status).toBe(400);
    expect((await bad({ participants: [] })).status).toBe(400);
    expect((await bad({ participants: [{ name: 5 }] })).status).toBe(400);
    expect((await bad({ record: [1] })).status).toBe(400);
    expect((await bad({}, "bad%20id", 1)).status).toBe(400);
    expect((await bad({ record: doc("m-1", 1, { filler: "x".repeat(CIRCLE_LIMITS.RECORD_BYTES) }) })).status).toBe(413);
  });

  it("limits the records of a site per day and what the circle holds, and asks for the rate limits", async () => {
    const saved = { ...CIRCLE_LIMITS };
    try {
      CIRCLE_LIMITS.RECORDS_PER_SITE_DAY = 2;
      expect((await put(ashitaka, "a-1", [{ name: "ashi" }])).status).toBe(201);
      expect((await put(ashitaka, "a-2", [{ name: "ashi" }])).status).toBe(201);
      expect((await put(ashitaka, "a-3", [{ name: "ashi" }])).status).toBe(429);
      t += 25 * 3_600_000;
      expect((await put(ashitaka, "a-3", [{ name: "ashi" }])).status).toBe(201);
      CIRCLE_LIMITS.RECORDS_PER_SITE_DAY = saved.RECORDS_PER_SITE_DAY;
      CIRCLE_LIMITS.RECORDS_TOTAL = 3;
      expect((await put(ashitaka, "a-4", [{ name: "ashi" }])).status).toBe(413);
      CIRCLE_LIMITS.RECORDS_TOTAL = saved.RECORDS_TOTAL;
      CIRCLE_LIMITS.BYTES_TOTAL = 10;
      expect((await put(ashitaka, "a-4", [{ name: "ashi" }])).status).toBe(413);
    } finally {
      Object.assign(CIRCLE_LIMITS, saved);
    }
    limitedCalls = [];
    refuseLimit = true;
    expect((await put(ashitaka, "a-9", [{ name: "ashi" }])).status).toBe(429);
    expect(limitedCalls).toEqual(["circle-write"]);
  });
});

describe("what a site gets", () => {
  it("a match goes to the sites in the rule of a player in it, not back to where it was played", async () => {
    await put(meierhof, "m-1", [{ name: "peter" }, { name: "ashi" }]);          // Peter and Ashi at Meierhof
    const at = async (site: Site) => (await call(site, "GET", "/circle/records")).body.records.map((r: any) => r.match_id);
    expect(await at(ashitaka)).toEqual(["m-1"]);                              // Ashi's rule
    expect(await at(streemo)).toEqual(["m-1"]);                               // Ashi's rule
    expect(await at(meierhof)).toEqual([]);                                   // played there
    expect(await at(crealine)).toEqual([]);                                   // in nobody's rule
  });

  it("a match with players of several rules goes to the union of the sites", async () => {
    await put(streemo, "m-2", [{ name: "timo" }]);
    const res = await call(ashitaka, "GET", "/circle/records");
    expect(res.body.records.map((r: any) => r.match_id)).toEqual(["m-2"]);
    expect((await call(meierhof, "GET", "/circle/records")).body.records).toEqual([]);
    await put(crealine, "m-3", [{ name: "peter", origin: "Meierhof" }, { name: "timo", origin: "Streemo's Board" }]);
    const sites = [ashitaka, streemo, meierhof].map(async (s) => (await call(s, "GET", "/circle/records")).body.records.map((r: any) => r.match_id));
    expect(await Promise.all(sites)).toEqual([["m-2", "m-3"], ["m-3"], ["m-3"]]);
  });

  it("lists with a cursor, with the origin and the deleted flag, and the newest revision only", async () => {
    await put(meierhof, "m-1", [{ name: "ashi" }]);
    await put(meierhof, "m-2", [{ name: "ashi" }]);
    const all = (await call(ashitaka, "GET", "/circle/records?since=0")).body;
    expect(all.records.map((r: any) => [r.match_id, r.revision, r.deleted, r.origin.name])).toEqual([["m-1", 1, false, "Meierhof"], ["m-2", 1, false, "Meierhof"]]);
    expect(all.next).toBe(all.records[1].seq);
    expect((await call(ashitaka, "GET", `/circle/records?since=${all.records[0].seq}`)).body.records.map((r: any) => r.match_id)).toEqual(["m-2"]);
    expect((await call(ashitaka, "GET", `/circle/records?since=${all.next}`)).body).toEqual({ records: [], next: all.next });
    await put(meierhof, "m-1", [{ name: "ashi" }], 2);
    expect((await call(ashitaka, "GET", `/circle/records?since=${all.next}`)).body.records.map((r: any) => [r.match_id, r.revision])).toEqual([["m-1", 2]]);
    expect((await call(ashitaka, "GET", "/circle/records?since=-1")).status).toBe(400);
  });

  it("fetches the record only for a site that gets it", async () => {
    await put(meierhof, "m-1", [{ name: "ashi" }], 1, {}, { filler: "content" });
    const got = await call(ashitaka, "GET", "/circle/records/m-1");
    expect(got.body).toMatchObject({ match_id: "m-1", revision: 1, game_mode: "X01", deleted: false, origin: { id: meierhof.id }, record: { filler: "content" } });
    expect((await call(crealine, "GET", "/circle/records/m-1")).status).toBe(404);
    expect((await call(meierhof, "GET", "/circle/records/m-1")).status).toBe(404);
    expect((await call(ashitaka, "GET", "/circle/records/unknown")).status).toBe(404);
  });

  it("asks for the rate limits when reading", async () => {
    limitedCalls = [];
    await call(ashitaka, "GET", "/circle/records");
    expect(limitedCalls).toEqual(["circle-read"]);
    refuseLimit = true;
    expect((await call(ashitaka, "GET", "/circle/records")).status).toBe(429);
  });
});

describe("signing off", () => {
  it("a location that leaves loses its place in the circle, the records it sent stay", async () => {
    await put(meierhof, "m-1", [{ name: "peter" }]);
    await dropSite(env.DB as never, meierhof.id);
    for (const table of ["circle_sites", "circle_mappings", "circle_rules"]) {
      expect(env.DB.count(`SELECT COUNT(*) AS n FROM ${table} WHERE location_id = ?`, meierhof.id)).toBe(0);
    }
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_records")).toBe(1);
  });
});
