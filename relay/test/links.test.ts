import { beforeEach, describe, expect, it } from "vitest";
import { AdminEnv, handleAdmin, makeToken, passwordHash } from "../src/admin";
import { handleLocations, Rooms } from "../src/locations";
import { FakeD1, id, newLocation, signed, Site } from "./support";

const NOW = 1_760_000_000_000;
const KEY = "k".repeat(64);
let db: FakeD1;
let adminEnv: AdminEnv & { DB: FakeD1 };
let token: string;
const rooms: Rooms = { status: async () => null, ticket: async () => null };
const limited = async () => false;

async function asSite(site: Site, method: string, path: string, body?: unknown) {
  const response = await handleLocations(await signed(site, method, path, NOW, body), { DB: db as never }, limited, rooms, NOW);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

async function asAdmin(method: string, path: string, body?: unknown) {
  const response = await handleAdmin(new Request(`https://relay.test${path}`, { method, headers: { authorization: `Bearer ${token}` }, body: body === undefined ? undefined : JSON.stringify(body) }),
    adminEnv, limited, NOW, async () => { throw new Error("no network"); });
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

const approve = (site: Site) => db.prepare("INSERT INTO circle_sites (location_id, approved, approved_at) VALUES (?, 1, ?)").bind(site.id, NOW).run();

let a: Site, b: Site, c: Site;

beforeEach(async () => {
  db = new FakeD1();
  adminEnv = { DB: db, ADMIN_PASSWORD_HASH: await passwordHash("pw", "ab".repeat(16)), ADMIN_TOKEN_KEY: KEY } as never;
  token = await makeToken(KEY, NOW + 3_600_000);
  a = await newLocation(db, 1, "Anna");
  b = await newLocation(db, 2, "Ben");
  c = await newLocation(db, 3, "Carl");
});

describe("links of the circle matrix", () => {
  it("lists the approved sites and the links with their source", async () => {
    await approve(a); await approve(b);
    await db.prepare("INSERT INTO links (id, location_a, location_b) VALUES (?, ?, ?)").bind(id(100), a.id, c.id).run();
    const { body } = await asAdmin("GET", "/admin/links");
    expect(body.sites.map((s: any) => s.name)).toEqual(["Anna", "Ben"]);
    expect(body.links).toEqual([{ a: a.id, b: c.id, source: "invitation" }]);
  });

  it("ticks and unticks a pair, once per pair, in either order of the ids", async () => {
    await approve(a); await approve(b);
    expect((await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: true })).body).toEqual({ ok: true });
    await asAdmin("PUT", `/admin/links/${b.id}/${a.id}`, { linked: true });          // a second tick changes nothing
    expect((await asAdmin("GET", "/admin/links")).body.links).toEqual([{ a: a.id, b: b.id, source: "admin" }]);
    expect(db.count("SELECT COUNT(*) AS n FROM links")).toBe(1);
    await asAdmin("PUT", `/admin/links/${b.id}/${a.id}`, { linked: false });
    await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: false });         // a second untick changes nothing
    expect(db.count("SELECT COUNT(*) AS n FROM links")).toBe(0);
  });

  it("removes a link that came from an invitation too", async () => {
    await approve(a); await approve(b);
    await db.prepare("INSERT INTO links (id, location_a, location_b) VALUES (?, ?, ?)").bind(id(100), a.id, b.id).run();
    await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: false });
    expect(db.count("SELECT COUNT(*) AS n FROM links")).toBe(0);
  });

  it("refuses a site that is not approved, itself and a bad body", async () => {
    await approve(a);
    expect((await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: true })).status).toBe(404);
    expect((await asAdmin("PUT", `/admin/links/${a.id}/${a.id}`, { linked: true })).status).toBe(400);
    await approve(b);
    expect((await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: "yes" })).status).toBe(400);
    expect(db.count("SELECT COUNT(*) AS n FROM links")).toBe(0);
  });

  it("gives an admin link the same effect as an invitation link", async () => {
    await approve(a); await approve(b);
    await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: true });
    await db.prepare("INSERT INTO open_matches (code, location_id, site, created_at, expires_at) VALUES ('ABC234', ?, 'x', ?, ?)").bind(b.id, NOW, NOW + 60_000).run();
    rooms.status = async () => ({ phase: "lobby", host: "x", sites: 1, players: 1 });
    try {
      expect((await asSite(a, "GET", `/locations/${a.id}/open-matches`)).body.matches).toHaveLength(1);
    } finally {
      rooms.status = async () => null;
    }
  });
});

describe("links seen by a location", () => {
  it("shows the source, and a location removes a link of either source itself", async () => {
    await approve(a); await approve(b);
    await asAdmin("PUT", `/admin/links/${a.id}/${b.id}`, { linked: true });
    await db.prepare("INSERT INTO links (id, location_a, location_b) VALUES (?, ?, ?)").bind(id(100), a.id, c.id).run();
    const list = (await asSite(a, "GET", `/locations/${a.id}/links`)).body.links;
    expect(list.map((l: any) => [l.peer.name, l.source])).toEqual([["Ben", "admin"], ["Carl", "invitation"]]);
    expect((await asSite(a, "DELETE", `/links/${list[0].link_id}`)).body).toEqual({ ok: true });
    expect((await asAdmin("GET", "/admin/links")).body.links).toEqual([{ a: a.id, b: c.id, source: "invitation" }]);
  });

  it("marks a link made by redeeming an invitation as such", async () => {
    const invite = (await asSite(a, "POST", `/locations/${a.id}/invitations`, {})).body;
    const redeemed = await asSite(b, "POST", "/invitations/redeem", { token: invite.token });
    expect(redeemed.status).toBe(201);
    expect((await asSite(b, "GET", `/locations/${b.id}/links`)).body.links[0].source).toBe("invitation");
  });
});
