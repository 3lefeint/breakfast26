import { beforeEach, describe, expect, it } from "vitest";
import { makeHash } from "../scripts/adminHash.mjs";
import { ADMIN_LIMITS, AdminEnv, handleAdmin, makeToken, passwordHash, tokenOk, verifyPassword } from "../src/admin";
import { FakeD1, id, newLocation } from "./support";

const NOW = 1_760_000_000_000;
const PASSWORD = "correct horse battery staple";
const KEY = "k".repeat(64);
let t = NOW;
let env: AdminEnv & { DB: FakeD1 };
let refuseLimit = false;
let limitedCalls: string[] = [];
let fetcher: (url: string, init: RequestInit) => Promise<Response> = async () => { throw new Error("no network in tests"); };
const limited = async (purpose: string) => { limitedCalls.push(purpose); return refuseLimit; };

async function login(password = PASSWORD) {
  return call(null, "POST", "/admin/login", { password });
}

async function call(token: string | null, method: string, path: string, body?: unknown) {
  const headers: Record<string, string> = {};
  if (token) headers.authorization = `Bearer ${token}`;
  const response = await handleAdmin(new Request(`https://relay.test${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }), env, limited, t, fetcher);
  return { status: response!.status, body: response!.status === 204 ? null : await response!.json() as Record<string, any>, headers: response!.headers };
}

let token: string;

beforeEach(async () => {
  t = NOW;
  refuseLimit = false;
  limitedCalls = [];
  env = { DB: new FakeD1(), ADMIN_PASSWORD_HASH: await passwordHash(PASSWORD, "ab".repeat(16)), ADMIN_TOKEN_KEY: KEY } as never;
  token = (await login()).body!.token;
});

describe("password and token", () => {
  it("the script and the relay agree on the stored form", async () => {
    const stored = makeHash(PASSWORD);
    expect(stored).toMatch(/^sha256\$[0-9a-f]{32}\$[0-9a-f]{64}$/);
    expect(await verifyPassword(stored, PASSWORD)).toBe(true);
    expect(await verifyPassword(stored, PASSWORD + "x")).toBe(false);
    expect(makeHash(PASSWORD)).not.toBe(stored);                           // a new salt every time
    expect(await verifyPassword("plain", PASSWORD)).toBe(false);
    expect(await verifyPassword("sha256$zz$00", PASSWORD)).toBe(false);
  });

  it("a login answers a token of about an hour that opens the routes", async () => {
    const ok = await login();
    expect(ok.status).toBe(200);
    expect(ok.body!.expires_at).toBe(NOW + ADMIN_LIMITS.TOKEN_TTL_MS);
    expect((await call(ok.body!.token, "GET", "/admin/sites")).status).toBe(200);
  });

  it("a wrong password is refused and counts as an attempt", async () => {
    limitedCalls = [];
    expect((await login("wrong")).status).toBe(401);
    expect(limitedCalls).toEqual(["admin-login"]);
    refuseLimit = true;
    expect((await login()).status).toBe(429);
  });

  it("refuses a missing, forged, tampered or expired token", async () => {
    expect((await call(null, "GET", "/admin/sites")).status).toBe(401);
    expect((await call("1760003600000." + "A".repeat(43), "GET", "/admin/sites")).status).toBe(401);
    expect((await call(token.replace(/.$/, "x"), "GET", "/admin/sites")).status).toBe(401);
    expect(await tokenOk(KEY, await makeToken("other key", NOW + 1000), NOW)).toBe(false);
    t += ADMIN_LIMITS.TOKEN_TTL_MS + 1;
    expect((await call(token, "GET", "/admin/sites")).status).toBe(401);
  });

  it("answers 503 until the secrets are set, and leaves other paths alone", async () => {
    (env as AdminEnv).ADMIN_PASSWORD_HASH = undefined;
    expect((await login()).status).toBe(503);
    expect(await handleAdmin(new Request("https://relay.test/circle/config"), env, limited, t)).toBeNull();
  });

  it("allows any origin and answers the preflight, on every answer", async () => {
    const pre = await call(null, "OPTIONS", "/admin/sites");
    expect(pre.status).toBe(204);
    expect(pre.headers.get("access-control-allow-origin")).toBe("*");
    expect(pre.headers.get("access-control-allow-headers")).toContain("authorization");
    expect((await call(token, "GET", "/admin/sites")).headers.get("access-control-allow-origin")).toBe("*");
    expect((await login("wrong")).headers.get("access-control-allow-origin")).toBe("*");
  });
});

describe("sites", () => {
  it("lists the registered locations with what they reported, and approves and removes them", async () => {
    const home = await newLocation(env.DB, 1, "Ashitaka's Board");
    await newLocation(env.DB, 2, "Crealine");
    await env.DB.prepare("INSERT INTO circle_sites (location_id, last_seen, version, players, state) VALUES (?, ?, ?, ?, ?)")
      .bind(home.id, NOW - 5000, "1.9.0", '["ashi"]', '{"last_pull":"x"}').run();
    const list = (await call(token, "GET", "/admin/sites")).body!.sites;
    expect(list.map((s: any) => [s.name, s.approved, s.version, s.players])).toEqual([["Ashitaka's Board", false, "1.9.0", ["ashi"]], ["Crealine", false, null, []]]);
    expect(list[0].state).toEqual({ last_pull: "x" });
    expect((await call(token, "POST", `/admin/sites/${home.id}/approve`, {})).body).toEqual({ ok: true, approved: true });
    expect((await call(token, "GET", "/admin/sites")).body!.sites[0]).toMatchObject({ approved: true, approved_at: NOW, version: "1.9.0" });
    expect((await call(token, "POST", `/admin/sites/${id(2)}/approve`, {})).body!.approved).toBe(true);     // a site that never reported
    expect((await call(token, "POST", `/admin/sites/${home.id}/remove`, {})).body).toEqual({ ok: true, approved: false });
    expect((await call(token, "GET", "/admin/sites")).body!.sites[0].approved).toBe(false);
    expect((await call(token, "POST", `/admin/sites/${id(9)}/approve`, {})).status).toBe(404);
  });
});

describe("players, mappings and rules", () => {
  it("creates circle players once and deletes them with their mappings and rules", async () => {
    const home = await newLocation(env.DB, 1);
    const ashi = (await call(token, "POST", "/admin/players", { name: " Ashi " })).body!;
    expect(ashi.name).toBe("Ashi");
    expect((await call(token, "POST", "/admin/players", { name: "ASHI" })).status).toBe(409);
    expect((await call(token, "POST", "/admin/players", { name: "" })).status).toBe(400);
    expect((await call(token, "PUT", "/admin/mappings", { location_id: home.id, local_name: "Ashi", player_id: ashi.id })).body).toEqual({ ok: true });
    expect((await call(token, "PUT", "/admin/rules", { player_id: ashi.id, location_ids: [home.id, home.id] })).body).toEqual({ ok: true });
    const players = (await call(token, "GET", "/admin/players")).body!.players;
    expect(players).toMatchObject([{ id: ashi.id, name: "Ashi", mappings: [{ location_id: home.id, local_name: "ashi" }], sites: [home.id] }]);
    expect((await call(token, "DELETE", `/admin/players/${ashi.id}`)).body).toEqual({ ok: true });
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_mappings") + env.DB.count("SELECT COUNT(*) AS n FROM circle_rules") + env.DB.count("SELECT COUNT(*) AS n FROM circle_players")).toBe(0);
  });

  it("sets, changes and clears a mapping, and refuses a bad one", async () => {
    const home = await newLocation(env.DB, 1);
    const a = (await call(token, "POST", "/admin/players", { name: "Ashi" })).body!;
    const b = (await call(token, "POST", "/admin/players", { name: "Timo" })).body!;
    const set = (player: string | null) => call(token, "PUT", "/admin/mappings", { location_id: home.id, local_name: "x", player_id: player });
    await set(a.id);
    await set(b.id);
    expect((env.DB.db.prepare("SELECT player_id FROM circle_mappings").all() as any[]).map((r) => r.player_id)).toEqual([b.id]);
    await set(null);
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_mappings")).toBe(0);
    expect((await set(id(77))).status).toBe(404);
    expect((await call(token, "PUT", "/admin/mappings", { location_id: id(55), local_name: "x", player_id: a.id })).status).toBe(404);
    expect((await call(token, "PUT", "/admin/mappings", { location_id: "nope", local_name: "x", player_id: a.id })).status).toBe(400);
  });

  it("replaces the rule of a player", async () => {
    const [s1, s2] = [await newLocation(env.DB, 1), await newLocation(env.DB, 2)];
    const p = (await call(token, "POST", "/admin/players", { name: "Ashi" })).body!;
    await call(token, "PUT", "/admin/rules", { player_id: p.id, location_ids: [s1.id, s2.id] });
    await call(token, "PUT", "/admin/rules", { player_id: p.id, location_ids: [s2.id] });
    expect((env.DB.db.prepare("SELECT location_id FROM circle_rules").all() as any[]).map((r) => r.location_id)).toEqual([s2.id]);
    await call(token, "PUT", "/admin/rules", { player_id: p.id, location_ids: [] });
    expect(env.DB.count("SELECT COUNT(*) AS n FROM circle_rules")).toBe(0);
    expect((await call(token, "PUT", "/admin/rules", { player_id: id(1), location_ids: [] })).status).toBe(404);
    expect((await call(token, "PUT", "/admin/rules", { player_id: p.id, location_ids: ["x"] })).status).toBe(400);
  });
});

describe("sync state and reports", () => {
  it("shows the sync state of the approved sites and the records without their content", async () => {
    const home = await newLocation(env.DB, 1, "Meierhof");
    await env.DB.prepare("INSERT INTO circle_sites (location_id, approved, last_seen, version, state) VALUES (?, 1, ?, '1.9.0', '{\"last_push\":\"ok\"}')").bind(home.id, NOW).run();
    const p = (await call(token, "POST", "/admin/players", { name: "Peter" })).body!;
    await env.DB.prepare("INSERT INTO circle_records (match_id, revision, origin, game_mode, deleted, size, hash, players, created_at) VALUES ('m-1', 2, ?, 'X01', 0, 1234, 'h', ?, ?)")
      .bind(home.id, JSON.stringify([p.id]), NOW).run();
    const sync = (await call(token, "GET", "/admin/sync")).body!;
    expect(sync.totals).toEqual({ n: 1, bytes: 1234 });
    expect(sync.sites).toMatchObject([{ id: home.id, name: "Meierhof", version: "1.9.0", state: { last_push: "ok" }, records_sent: { n: 1, bytes: 1234, last: NOW } }]);
    const records = (await call(token, "GET", "/admin/records")).body!.records;
    expect(records).toMatchObject([{ match_id: "m-1", revision: 2, origin: { name: "Meierhof" }, game_mode: "X01", players: ["Peter"], size: 1234 }]);
    expect(JSON.stringify(records)).not.toContain("hash");
  });

  it("summarises the usage reports of the last days", async () => {
    const add = (install: string, version: string, platform: string, type: string, received: string, data = "{}") =>
      env.DB.prepare("INSERT INTO events (received_at, install_id, version, platform, type, ts, data) VALUES (?, ?, ?, ?, ?, ?, ?)").bind(received, install, version, platform, type, received, data).run();
    const day = (n: number) => new Date(NOW - n * 86_400_000).toISOString().replace(/\.\d+Z$/, "Z");
    await add("a".repeat(32), "1.9.0", "docker", "app_start", day(1));
    await add("a".repeat(32), "1.9.0", "docker", "game_started", day(1), '{"mode":"X01"}');
    await add("b".repeat(32), "1.8.0", "windows", "app_start", day(2));
    await add("c".repeat(32), "1.0.0", "docker", "app_start", day(60));
    const r = (await call(token, "GET", "/admin/reports")).body!;
    expect(r.days).toBe(30);
    expect(r.installs).toBe(2);
    expect(r.by_type).toEqual([{ type: "app_start", n: 2 }, { type: "game_started", n: 1 }]);
    expect(r.versions).toEqual(expect.arrayContaining([{ version: "1.9.0", installs: 1 }, { version: "1.8.0", installs: 1 }]));
    expect(r.recent.map((e: any) => e.type)).toEqual(["app_start", "game_started", "app_start"]);        // newest first, the old one is out
    expect(r.recent[1]).toMatchObject({ data: { mode: "X01" } });
    const wide = (await call(token, "GET", "/admin/reports?days=90")).body!;
    expect(wide.installs).toBe(3);
  });

  it("answers 404 for an unknown admin route", async () => {
    expect((await call(token, "GET", "/admin/nothing")).status).toBe(404);
  });
});

describe("the usage of the free plan", () => {
  const answers = (data: Record<string, unknown>) => async (_url: string, init: RequestInit) => {
    const query = JSON.parse(String(init.body)).query as string;
    const dataset = Object.keys(data).find((name) => query.includes(name))!;
    const value = data[dataset];
    return value instanceof Response ? value : new Response(JSON.stringify({ data: { viewer: { accounts: [{ [dataset]: value }] } } }));
  };

  it("says that it is not set up while the token or the account is missing", async () => {
    const res = await call(token, "GET", "/admin/usage");
    expect(res.body).toMatchObject({ configured: false, limits: { workers_requests_day: 100_000 } });
    env.ANALYTICS_API_TOKEN = "token";
    expect((await call(token, "GET", "/admin/usage")).body!.configured).toBe(false);
  });

  it("asks the API for every figure and adds them up", async () => {
    env.ANALYTICS_API_TOKEN = "token";
    env.CF_ACCOUNT_ID = "acc";
    env.CF_D1_DATABASE_ID = "db-1";
    const seen: { auth: string | null; variables: Record<string, unknown> }[] = [];
    fetcher = async (url, init) => {
      expect(url).toBe("https://api.cloudflare.com/client/v4/graphql");
      seen.push({ auth: new Headers(init.headers).get("authorization"), variables: JSON.parse(String(init.body)).variables });
      return answers({
        workersInvocationsAdaptive: [{ sum: { requests: 120, errors: 2, subrequests: 5 }, quantiles: { cpuTimeP50: 300, cpuTimeP99: 900 } },
          { sum: { requests: 30, errors: 0, subrequests: 1 }, quantiles: { cpuTimeP50: 100, cpuTimeP99: 1200 } }],
        d1AnalyticsAdaptiveGroups: [{ sum: { readQueries: 10, writeQueries: 4, rowsRead: 500, rowsWritten: 40 } }],
        d1StorageAdaptiveGroups: [{ max: { databaseSizeBytes: 90_000 }, dimensions: { date: "2025-10-09" } }, { max: { databaseSizeBytes: 80_000 }, dimensions: { date: "2025-10-08" } }],
        r2OperationsAdaptiveGroups: [{ sum: { requests: 7 }, dimensions: { actionType: "PutObject" } }, { sum: { requests: 40 }, dimensions: { actionType: "GetObject" } },
          { sum: { requests: 3 }, dimensions: { actionType: "DeleteObject" } }, { sum: { requests: 1 }, dimensions: { actionType: "Mystery" } }],
        r2StorageAdaptiveGroups: [{ max: { objectCount: 12, payloadSize: 2000, metadataSize: 100 }, dimensions: { datetime: "x" } }],
      })(url, init);
    };
    const { body } = await call(token, "GET", "/admin/usage");
    expect(body).toMatchObject({
      configured: true, day: "2025-10-09", month: "2025-10-01",
      workers: { data: { requests: 150, errors: 2, subrequests: 6, cpu_p50: 300, cpu_p99: 1200 } },
      d1: { data: { read_queries: 10, write_queries: 4, rows_read: 500, rows_written: 40 } },
      d1_size: { data: { bytes: 90_000 } },
      r2_operations: { data: { class_a: 7, class_b: 40, free: 3, other: 1 } },
      r2_storage: { data: { bytes: 2100, objects: 12 } },
    });
    expect(seen).toHaveLength(5);
    expect(seen.every((s) => s.auth === "Bearer token" && s.variables.accountTag === "acc")).toBe(true);
    expect(seen.filter((s) => s.variables.databaseId === "db-1")).toHaveLength(2);
  });

  it("one figure the API refuses does not take the others away", async () => {
    env.ANALYTICS_API_TOKEN = "token";
    env.CF_ACCOUNT_ID = "acc";
    fetcher = async (url, init) => {
      const query = JSON.parse(String(init.body)).query as string;
      if (query.includes("d1StorageAdaptiveGroups")) return new Response(JSON.stringify({ data: null, errors: [{ message: "unknown field databaseSizeBytes" }] }));
      if (query.includes("r2StorageAdaptiveGroups")) return new Response("{}", { status: 403 });
      return answers({ workersInvocationsAdaptive: [], d1AnalyticsAdaptiveGroups: [], r2OperationsAdaptiveGroups: [] })(url, init);
    };
    const { body } = await call(token, "GET", "/admin/usage");
    expect(body!.d1_size).toEqual({ error: "unknown field databaseSizeBytes" });
    expect(body!.r2_storage).toEqual({ error: "Cloudflare answered 403" });
    expect(body!.workers.data.requests).toBe(0);
    expect(body!.r2_operations.data).toMatchObject({ class_a: 0, class_b: 0 });
  });

  it("needs the login like the other routes", async () => {
    expect((await call(null, "GET", "/admin/usage")).status).toBe(401);
  });
});
