import { beforeEach, describe, expect, it } from "vitest";
import { AdminEnv, handleAdmin, passwordHash } from "../src/admin";
import { CHANNEL_LIMITS, channelRoom, handleVoiceChannels, siteSeesChannel, VoiceChannelEnv } from "../src/voiceChannels";
import { FakeD1, newLocation, signed, Site } from "./support";

const NOW = 1_760_000_000_000;
const PASSWORD = "correct horse battery staple";
let t = NOW;
let env: AdminEnv & VoiceChannelEnv & { DB: FakeD1 };
let tickets: { room: string; body: Record<string, any> }[] = [];
let rechecks: string[] = [];
let refuseLimit = false;
let token: string;
let anna: Site, ben: Site, carl: Site;
const limited = async () => refuseLimit;

async function admin(method: string, path: string, body?: unknown) {
  const response = await handleAdmin(new Request(`https://relay.test${path}`, {
    method, headers: { authorization: `Bearer ${token}` }, body: body === undefined ? undefined : JSON.stringify(body) }), env, limited, t);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

async function site(who: Site | null, method: string, path: string, body?: unknown) {
  const response = await handleVoiceChannels(await signed(who, method, path, t, body), env, limited, t);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

beforeEach(async () => {
  t = NOW;
  tickets = [];
  rechecks = [];
  refuseLimit = false;
  const room = (name: string) => ({ fetch: async (url: string, init: RequestInit) => {
    if (url.endsWith("/recheck")) rechecks.push(name);
    else tickets.push({ room: name, body: JSON.parse(init.body as string) });
    return new Response(null, { status: 200 });
  } });
  env = {
    DB: new FakeD1(), ADMIN_PASSWORD_HASH: await passwordHash(PASSWORD, "ab".repeat(16)), ADMIN_TOKEN_KEY: "k".repeat(64),
    VOICE: { idFromName: (name: string) => name, get: (name: string) => room(name) },
  } as never;
  const login = await handleAdmin(new Request("https://relay.test/admin/login", { method: "POST", body: JSON.stringify({ password: PASSWORD }) }), env, limited, t);
  token = (await login!.json() as { token: string }).token;
  anna = await newLocation(env.DB, 1, "Anna's Board");
  ben = await newLocation(env.DB, 2, "Ben's Board");
  carl = await newLocation(env.DB, 3, "Carl's Board");
  for (const s of [anna, ben]) await env.DB.prepare("INSERT INTO circle_sites (location_id, approved, approved_at) VALUES (?, 1, ?)").bind(s.id, NOW).run();
  await env.DB.prepare("INSERT INTO circle_sites (location_id, approved) VALUES (?, 0)").bind(carl.id).run();
});

async function channel(name: string) {
  return (await admin("POST", "/admin/voice/channels", { name })).body.id as string;
}

describe("the channels in the admin", () => {
  it("renames a channel", async () => {
    const id = await channel("Kitchen");
    expect((await admin("PUT", `/admin/voice/channels/${id}`, { name: " Cellar " })).status).toBe(200);
    expect((await admin("GET", "/admin/voice")).body.channels.map((c: any) => c.name)).toEqual(["Cellar"]);
    const other = await channel("Attic");
    expect((await admin("PUT", `/admin/voice/channels/${other}`, { name: "CELLAR" })).status).toBe(409);
    expect((await admin("PUT", `/admin/voice/channels/${other}`, { name: "" })).status).toBe(400);
    expect((await admin("PUT", `/admin/voice/channels/${"0".repeat(32)}`, { name: "Attic 2" })).status).toBe(404);
    expect((await admin("PUT", `/admin/voice/channels/${other}`, { name: "Attic" })).status).toBe(200);        // its own name again
  });

  it("makes and deletes a channel", async () => {
    const res = await admin("POST", "/admin/voice/channels", { name: " Kitchen " });
    expect(res.status).toBe(201);
    expect(res.body.name).toBe("Kitchen");
    expect((await admin("GET", "/admin/voice")).body.channels.map((c: any) => c.name)).toEqual(["Kitchen"]);
    expect((await admin("DELETE", `/admin/voice/channels/${res.body.id}`)).status).toBe(200);
    expect((await admin("GET", "/admin/voice")).body.channels).toEqual([]);
  });

  it("refuses a bad, a double and a too many channels", async () => {
    expect((await admin("POST", "/admin/voice/channels", { name: "" })).status).toBe(400);
    await channel("Kitchen");
    expect((await admin("POST", "/admin/voice/channels", { name: "kitchen" })).status).toBe(409);
    for (let i = 1; i < CHANNEL_LIMITS.CHANNELS; i++) await channel(`Room ${i}`);
    expect((await admin("POST", "/admin/voice/channels", { name: "One more" })).status).toBe(409);
  });

  it("lists the approved sites as the rows of the matrix and ticks a cell", async () => {
    const kitchen = await channel("Kitchen");
    expect((await admin("GET", "/admin/voice")).body.sites.map((s: any) => s.name)).toEqual(["Anna's Board", "Ben's Board"]);
    expect((await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: true })).status).toBe(200);
    expect((await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: true })).status).toBe(200);
    expect((await admin("GET", "/admin/voice")).body.channels[0].sites).toEqual([anna.id]);
    expect((await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: false })).status).toBe(200);
    expect((await admin("GET", "/admin/voice")).body.channels[0].sites).toEqual([]);
  });

  it("only ticks a site that the circle approved and a channel that exists", async () => {
    const kitchen = await channel("Kitchen");
    expect((await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${carl.id}`, { visible: true })).status).toBe(404);
    expect((await admin("PUT", `/admin/voice/channels/${"0".repeat(32)}/sites/${anna.id}`, { visible: true })).status).toBe(404);
    expect((await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: "yes" })).status).toBe(400);
  });

  it("sends a site out of the channel when its tick is taken away, and not when one is added", async () => {
    const kitchen = await channel("Kitchen");
    await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: true });
    expect(rechecks).toEqual([]);
    await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: false });
    expect(rechecks).toEqual([channelRoom(kitchen)]);
  });

  it("sends everybody out of a channel that is deleted", async () => {
    const kitchen = await channel("Kitchen");
    await admin("DELETE", `/admin/voice/channels/${kitchen}`);
    expect(rechecks).toEqual([channelRoom(kitchen)]);
  });

  it("sends a site that is taken out of the circle out of its channels", async () => {
    const kitchen = await channel("Kitchen");
    const cellar = await channel("Cellar");
    await channel("Attic");
    await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: true });
    await admin("PUT", `/admin/voice/channels/${cellar}/sites/${anna.id}`, { visible: true });
    await admin("POST", `/admin/sites/${anna.id}/remove`, {});
    expect(rechecks.sort()).toEqual([channelRoom(kitchen), channelRoom(cellar)].sort());
  });

  it("forgets who saw a deleted channel", async () => {
    const kitchen = await channel("Kitchen");
    await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: true });
    await admin("DELETE", `/admin/voice/channels/${kitchen}`);
    expect(env.DB.count("SELECT COUNT(*) AS n FROM voice_channel_sites")).toBe(0);
  });
});

describe("the channels at a site", () => {
  let kitchen: string, cellar: string;
  beforeEach(async () => {
    kitchen = await channel("Kitchen");
    cellar = await channel("Cellar");
    await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${anna.id}`, { visible: true });
    await admin("PUT", `/admin/voice/channels/${kitchen}/sites/${ben.id}`, { visible: true });
    await admin("PUT", `/admin/voice/channels/${cellar}/sites/${ben.id}`, { visible: true });
  });

  it("lists only the channels it is ticked for", async () => {
    expect((await site(anna, "GET", "/circle/voice")).body.channels).toEqual([{ id: kitchen, name: "Kitchen" }]);
    expect((await site(ben, "GET", "/circle/voice")).body.channels.map((c: any) => c.name)).toEqual(["Cellar", "Kitchen"]);
  });

  it("needs a signed request from an approved site", async () => {
    expect((await site(null, "GET", "/circle/voice")).status).toBe(401);
    expect((await site(carl, "GET", "/circle/voice")).status).toBe(403);
    expect((await site(carl, "POST", `/circle/voice/${kitchen}/ticket`)).status).toBe(403);
  });

  it("gives a ticket for a channel it sees and passes it to the room of the channel", async () => {
    const res = await site(anna, "POST", `/circle/voice/${kitchen}/ticket`);
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ site: "Anna's Board", channel: { id: kitchen, name: "Kitchen" } });
    expect(res.body.ticket).toMatch(/^[0-9a-f]{32}$/);
    expect(tickets).toEqual([{ room: channelRoom(kitchen), body: { location: anna.id, site: "Anna's Board", ticket: res.body.ticket, until: NOW + CHANNEL_LIMITS.TICKET_TTL_MS } }]);
  });

  it("gives no ticket for a channel it does not see or that does not exist", async () => {
    expect((await site(anna, "POST", `/circle/voice/${cellar}/ticket`)).status).toBe(404);
    expect((await site(anna, "POST", `/circle/voice/${"0".repeat(32)}/ticket`)).status).toBe(404);
    expect(tickets).toEqual([]);
  });

  it("stops seeing a channel when the site is no longer in the circle", async () => {
    expect(await siteSeesChannel(env.DB as never, kitchen, anna.id)).toBe(true);
    await env.DB.prepare("UPDATE circle_sites SET approved = 0 WHERE location_id = ?").bind(anna.id).run();
    expect(await siteSeesChannel(env.DB as never, kitchen, anna.id)).toBe(false);
    expect((await site(anna, "GET", "/circle/voice")).status).toBe(403);
  });

  it("answers 429 when the limit is reached and ignores other routes", async () => {
    refuseLimit = true;
    expect((await site(anna, "GET", "/circle/voice")).status).toBe(429);
    expect((await site(anna, "POST", `/circle/voice/${kitchen}/ticket`)).status).toBe(429);
    expect(await handleVoiceChannels(await signed(anna, "GET", "/circle/config", t), env, limited, t)).toBeNull();
  });
});
