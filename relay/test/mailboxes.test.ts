import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { b64urlEncode, sha256Hex, signingString } from "../src/locations";
import { dropMailboxesOf, handleMailboxes, MailboxEnv, MAILBOX_LIMITS } from "../src/mailboxes";

// ── a D1 over node:sqlite with the real migrations, and an R2 in memory ────────────────────────

class Statement {
  constructor(private db: DatabaseSync, private sql: string, private params: unknown[] = []) {}
  bind(...params: unknown[]) { return new Statement(this.db, this.sql, params); }
  async first<T>(): Promise<T | null> { return ((this.db.prepare(this.sql).get(...(this.params as never[])) as T | undefined) ?? null); }
  async all<T>() { return { results: this.db.prepare(this.sql).all(...(this.params as never[])) as T[] }; }
  async run() {
    const r = this.db.prepare(this.sql).run(...(this.params as never[]));
    return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } };
  }
}

class FakeD1 {
  db = new DatabaseSync(":memory:");
  constructor() {
    for (const file of readdirSync("migrations").sort()) this.db.exec(readFileSync(`migrations/${file}`, "utf8"));
  }
  prepare(sql: string) { return new Statement(this.db, sql); }
  async batch(statements: Statement[]) { return Promise.all(statements.map((s) => s.run())); }
}

class FakeR2 {
  objects = new Map<string, Uint8Array>();
  async put(key: string, value: Uint8Array) { this.objects.set(key, value); }
  async get(key: string) {
    const v = this.objects.get(key);
    return v ? { arrayBuffer: async () => v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength) } : null;
  }
  async delete(keys: string | string[]) { for (const k of Array.isArray(keys) ? keys : [keys]) this.objects.delete(k); }
  async list({ prefix = "" }: { prefix?: string; cursor?: string; limit?: number }) {
    return { objects: [...this.objects.keys()].filter((k) => k.startsWith(prefix)).map((key) => ({ key })), truncated: false, cursor: undefined };
  }
}

// ── signing ────────────────────────────────────────────────────────────────────────────────

async function keyPair() {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey) as ArrayBuffer);
  return { pair, publicKey: b64urlEncode(raw) };
}

const NOW = 1_760_000_000_000;
let t = NOW;
let env: MailboxEnv & { DB: FakeD1; RECORDS: FakeR2 };
let limitedCalls: string[] = [];
let refuseLimit = false;
const limited = async (purpose: string) => { limitedCalls.push(purpose); return refuseLimit; };

type Signer = { header: [string, string]; pair: CryptoKeyPair } | null;

async function call(signer: Signer, method: string, path: string, body?: unknown, extra: Record<string, string> = {}) {
  const raw = body === undefined ? "" : JSON.stringify(body);
  const timestamp = String(Math.floor(t / 1000));
  const headers: Record<string, string> = { ...extra };
  if (signer) {
    const message = signingString(method, path.split("?")[0], timestamp, await sha256Hex(raw));
    const signature = b64urlEncode(new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, signer.pair.privateKey, new TextEncoder().encode(message))));
    headers[signer.header[0]] = signer.header[1];
    headers["x-timestamp"] = timestamp;
    headers["x-signature"] = signature;
  }
  const response = await handleMailboxes(new Request(`https://relay.test${path}`, { method, body: raw === "" ? undefined : raw, headers }), env, limited, t);
  return { status: response!.status, body: await response!.json() as Record<string, any> };
}

const id = (n: number) => n.toString(16).padStart(32, "0");

async function newLocation(n: number): Promise<Signer & { id: string }> {
  const { pair, publicKey } = await keyPair();
  await env.DB.prepare("INSERT INTO locations (id, name, public_key) VALUES (?, ?, ?)").bind(id(n), `Location ${n}`, publicKey).run();
  return { id: id(n), header: ["x-location", id(n)], pair };
}

/** A member's mailbox at `location`, a device that redeemed its invitation. */
async function member(location: Signer & { id: string }) {
  const made = await call(location, "POST", `/locations/${location.id}/members`, {});
  expect(made.status).toBe(201);
  const { pair, publicKey } = await keyPair();
  const redeemed = await call({ header: ["x-unused", ""], pair }, "POST", "/mailbox-invitations/redeem", { token: made.body.token, public_key: publicKey });
  expect(redeemed.status).toBe(201);
  const device: Signer & { id: string } = { id: redeemed.body.device_id, header: ["x-device", redeemed.body.device_id], pair };
  return { mailbox: made.body.mailbox_id as string, device, token: made.body.token as string, invitation: made.body };
}

const record = (bytes = "hello", extra: Record<string, unknown> = {}) => ({
  envelope_version: 1, game_mode: "X01", deleted: false, ciphertext: b64urlEncode(new TextEncoder().encode(bytes)), ...extra,
});

beforeEach(() => {
  t = NOW;
  limitedCalls = [];
  refuseLimit = false;
  env = { DB: new FakeD1(), RECORDS: new FakeR2() } as never;
});

describe("members and invitations", () => {
  it("a location creates a mailbox for a member with a single-use invitation", async () => {
    const home = await newLocation(1);
    const made = await call(home, "POST", `/locations/${home.id}/members`, {});
    expect(made.status).toBe(201);
    expect(made.body.mailbox_id).toMatch(/^[0-9a-f]{32}$/);
    expect(made.body.token).toHaveLength(32);
    expect(made.body.expires_at).toBe(NOW + MAILBOX_LIMITS.INVITATION_TTL_MS);
    expect(JSON.stringify(env.DB.db.prepare("SELECT * FROM mailbox_invitations").all())).not.toContain(made.body.token);   // only the hash
  });

  it("only the location itself, and only with a good signature", async () => {
    const home = await newLocation(1);
    const club = await newLocation(2);
    expect((await call(club, "POST", `/locations/${home.id}/members`, {})).status).toBe(403);
    expect((await call(null, "POST", `/locations/${home.id}/members`, {})).status).toBe(401);
    const stranger = { header: ["x-location", home.id] as [string, string], pair: (await keyPair()).pair };
    expect((await call(stranger, "POST", `/locations/${home.id}/members`, {})).status).toBe(401);
  });

  it("a device registers its key with the invitation, once", async () => {
    const home = await newLocation(1);
    const { mailbox, token, device } = await member(home);
    expect(device.id).toMatch(/^[0-9a-f]{32}$/);
    const again = await keyPair();
    const second = await call({ header: ["x-unused", ""], pair: again.pair }, "POST", "/mailbox-invitations/redeem", { token, public_key: again.publicKey });
    expect(second.status).toBe(404);
    expect(env.DB.db.prepare("SELECT COUNT(*) AS n FROM devices WHERE mailbox_id = ?").get(mailbox)).toMatchObject({ n: 1 });
  });

  it("redeems only with a signature of the key it registers", async () => {
    const home = await newLocation(1);
    const made = await call(home, "POST", `/locations/${home.id}/members`, {});
    const mine = await keyPair();
    const other = await keyPair();
    const bad = await call({ header: ["x-unused", ""], pair: other.pair }, "POST", "/mailbox-invitations/redeem", { token: made.body.token, public_key: mine.publicKey });
    expect(bad.status).toBe(401);
    const good = await call({ header: ["x-unused", ""], pair: mine.pair }, "POST", "/mailbox-invitations/redeem", { token: made.body.token, public_key: mine.publicKey });
    expect(good.body).toMatchObject({ mailbox_id: made.body.mailbox_id, up: false, location: { id: home.id, name: "Location 1" } });
  });

  it("refuses an expired or unknown invitation and too many devices", async () => {
    const home = await newLocation(1);
    const made = await call(home, "POST", `/locations/${home.id}/members`, {});
    const k = await keyPair();
    const redeem = (token: string) => call({ header: ["x-unused", ""], pair: k.pair }, "POST", "/mailbox-invitations/redeem", { token, public_key: k.publicKey });
    expect((await redeem("a".repeat(32))).status).toBe(404);
    t += MAILBOX_LIMITS.INVITATION_TTL_MS + 1000;
    expect((await redeem(made.body.token)).status).toBe(404);
    t = NOW;
    for (let i = 0; i < MAILBOX_LIMITS.DEVICES_PER_MAILBOX; i++) {
      const again = await call(home, "POST", `/mailboxes/${made.body.mailbox_id}/invitations`, {});
      if (i === 0) {
        expect((await redeem(made.body.token)).status).toBe(201);
        continue;
      }
      expect((await redeem(again.body.token)).status).toBe(201);
      await env.DB.prepare("DELETE FROM mailbox_invitations WHERE mailbox_id = ?").bind(made.body.mailbox_id).run();
    }
    const last = await call(home, "POST", `/mailboxes/${made.body.mailbox_id}/invitations`, {});
    expect((await redeem(last.body.token)).status).toBe(429);
  });

  it("a lost invitation is replaced by a new one for the same mailbox, with a limit of open ones", async () => {
    const home = await newLocation(1);
    const made = await call(home, "POST", `/locations/${home.id}/members`, {});
    for (let i = 1; i < MAILBOX_LIMITS.PENDING_INVITATIONS_PER_MAILBOX; i++) {
      expect((await call(home, "POST", `/mailboxes/${made.body.mailbox_id}/invitations`, {})).status).toBe(201);
    }
    expect((await call(home, "POST", `/mailboxes/${made.body.mailbox_id}/invitations`, {})).status).toBe(429);
  });

  it("rate limits are asked for", async () => {
    const home = await newLocation(1);
    refuseLimit = true;
    expect((await call(home, "POST", `/locations/${home.id}/members`, {})).status).toBe(429);
    expect(limitedCalls).toContain("mbx-invite");
  });
});

describe("records", () => {
  it("the location puts a record into `down`, the member lists it with a cursor and fetches it", async () => {
    const home = await newLocation(1);
    const { mailbox, device } = await member(home);
    const put = await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("one"));
    expect(put.status).toBe(201);
    expect(put.body).toMatchObject({ size: 3, seq: 1 });
    await call(home, "PUT", `/mailboxes/${mailbox}/down/m-2/1`, record("two", { game_mode: "Elimination" }));
    const list = await call(device, "GET", `/mailboxes/${mailbox}/down?since=0`);
    expect(list.body.records.map((r: any) => [r.match_id, r.revision, r.game_mode, r.deleted])).toEqual([["m-1", 1, "X01", false], ["m-2", 1, "Elimination", false]]);
    expect(list.body.next).toBe(2);
    const more = await call(device, "GET", `/mailboxes/${mailbox}/down?since=1`);
    expect(more.body.records.map((r: any) => r.match_id)).toEqual(["m-2"]);
    expect((await call(device, "GET", `/mailboxes/${mailbox}/down?since=2`)).body).toEqual({ records: [], next: 2 });
    const fetched = await call(device, "GET", `/mailboxes/${mailbox}/down/m-1/1`);
    expect(fetched.body).toMatchObject({ match_id: "m-1", revision: 1, game_mode: "X01", deleted: false, size: 3, envelope_version: 1 });
    expect(new TextDecoder().decode(Uint8Array.from(atob(fetched.body.ciphertext.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0)))).toBe("one");
    expect(fetched.body.hash).toBe(put.body.hash);
  });

  it("the channels are one way: the location writes down and reads up, the member the other way round", async () => {
    const home = await newLocation(1);
    const { mailbox, device } = await member(home);
    expect((await call(device, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record())).status).toBe(403);
    expect((await call(home, "GET", `/mailboxes/${mailbox}/down`)).status).toBe(403);
    expect((await call(device, "PUT", `/mailboxes/${mailbox}/up/m-1/1`, record())).status).toBe(403);   // up is off at first
    expect((await call(home, "PATCH", `/mailboxes/${mailbox}`, { up: true })).body).toEqual({ ok: true, up: true });
    expect((await call(device, "PUT", `/mailboxes/${mailbox}/up/m-1/1`, record("from the member"))).status).toBe(201);
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/up/m-2/1`, record())).status).toBe(403);
    const list = await call(home, "GET", `/mailboxes/${mailbox}/up`);
    expect(list.body.records.map((r: any) => r.match_id)).toEqual(["m-1"]);
    expect((await call(home, "GET", `/mailboxes/${mailbox}/up/m-1/1`)).status).toBe(200);
    expect((await call(device, "PATCH", `/mailboxes/${mailbox}`, { up: false })).status).toBe(403);
    expect((await call(home, "PATCH", `/mailboxes/${mailbox}`, { up: "yes" })).status).toBe(400);
  });

  it("nobody else sees or touches a mailbox, and nobody learns which ones exist", async () => {
    const home = await newLocation(1);
    const club = await newLocation(2);
    const mine = await member(home);
    const theirs = await member(club);
    for (const [who, path, method] of [
      [club, `/mailboxes/${mine.mailbox}/down`, "GET"], [theirs.device, `/mailboxes/${mine.mailbox}/down`, "GET"],
      [club, `/mailboxes/${mine.mailbox}`, "DELETE"], [club, `/mailboxes/${mine.mailbox}/invitations`, "POST"],
    ] as const) {
      const r = await call(who, method, path, method === "GET" ? undefined : {});
      expect(r.status).toBe(404);
    }
    expect((await call(home, "GET", `/mailboxes/${id(99)}/down`)).status).toBe(404);
  });

  it("the same record again changes nothing, another content for the same revision is refused", async () => {
    const home = await newLocation(1);
    const { mailbox } = await member(home);
    const a = await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("one"));
    const b = await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("one"));
    expect(b.status).toBe(200);
    expect(b.body.seq).toBe(a.body.seq);
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("other"))).status).toBe(409);
    expect(env.DB.db.prepare("SELECT COUNT(*) AS n FROM records").get()).toMatchObject({ n: 1 });
  });

  it("a newer revision replaces the older one, an older one is refused", async () => {
    const home = await newLocation(1);
    const { mailbox, device } = await member(home);
    await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("one"));
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/2`, record("two"))).status).toBe(201);
    expect([...env.RECORDS.objects.keys()]).toEqual([`${mailbox}/down/m-1/2`]);
    expect((await call(device, "GET", `/mailboxes/${mailbox}/down`)).body.records.map((r: any) => r.revision)).toEqual([2]);
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("one"))).status).toBe(409);
  });

  it("a deletion carries no ciphertext and takes the older revisions away", async () => {
    const home = await newLocation(1);
    const { mailbox, device } = await member(home);
    await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record("one"));
    const gone = await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/2`, { envelope_version: 1, game_mode: "X01", deleted: true });
    expect(gone.status).toBe(201);
    expect(env.RECORDS.objects.size).toBe(0);
    const fetched = await call(device, "GET", `/mailboxes/${mailbox}/down/m-1/2`);
    expect(fetched.body).toMatchObject({ deleted: true, ciphertext: null, size: 0 });
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-2/1`, { envelope_version: 1, game_mode: "X01", deleted: true, ciphertext: "AAAA" })).status).toBe(400);
  });

  it("refuses what is not a record", async () => {
    const home = await newLocation(1);
    const { mailbox } = await member(home);
    const put = (body: unknown, path = `/mailboxes/${mailbox}/down/m-1/1`) => call(home, "PUT", path, body);
    expect((await put(record("x", { game_mode: "Cricket" }))).status).toBe(400);
    expect((await put(record("x", { envelope_version: 0 }))).status).toBe(400);
    expect((await put(record("x", { deleted: "no" }))).status).toBe(400);
    expect((await put(record("x", { ciphertext: "not base64!" }))).status).toBe(400);
    expect((await put(record("x", { ciphertext: "" }))).status).toBe(400);
    expect((await put(record(), `/mailboxes/${mailbox}/down/bad%20id/1`)).status).toBe(400);
    expect((await put(record(), `/mailboxes/${mailbox}/down/m-1/0`)).status).toBe(400);
    expect((await call(home, "GET", `/mailboxes/${mailbox}/down/m-9/1`)).status).toBe(403);
  });

  it("limits the size of a record, the records of a writer per day and the contents of a mailbox", async () => {
    const home = await newLocation(1);
    const { mailbox, device } = await member(home);
    const big = "x".repeat(MAILBOX_LIMITS.RECORD_BYTES + 1);
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/big/1`, record(big))).status).toBe(413);
    const saved = { ...MAILBOX_LIMITS };
    try {
      MAILBOX_LIMITS.RECORDS_PER_WRITER_DAY = 3;
      for (let i = 1; i <= 3; i++) expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-${i}/1`, record(String(i)))).status).toBe(201);
      expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-4/1`, record("4"))).status).toBe(429);
      t += 25 * 3_600_000;
      expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-4/1`, record("4"))).status).toBe(201);
      MAILBOX_LIMITS.RECORDS_PER_WRITER_DAY = saved.RECORDS_PER_WRITER_DAY;
      MAILBOX_LIMITS.RECORDS_PER_MAILBOX = 4;
      expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-5/1`, record("5"))).status).toBe(413);
      MAILBOX_LIMITS.RECORDS_PER_MAILBOX = saved.RECORDS_PER_MAILBOX;
      MAILBOX_LIMITS.BYTES_PER_MAILBOX = 5;
      expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-5/1`, record("123456"))).status).toBe(413);
      expect((await call(device, "GET", `/mailboxes/${mailbox}/down`)).status).toBe(200);
    } finally {
      Object.assign(MAILBOX_LIMITS, saved);
    }
  });

  it("asks for the rate limits", async () => {
    const home = await newLocation(1);
    const { mailbox, device } = await member(home);
    limitedCalls = [];
    await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, record());
    await call(device, "GET", `/mailboxes/${mailbox}/down`);
    expect(limitedCalls).toEqual(["mbx-write", "mbx-read"]);
    refuseLimit = true;
    expect((await call(device, "GET", `/mailboxes/${mailbox}/down`)).status).toBe(429);
  });
});

describe("deleting", () => {
  it("removing a mailbox deletes its rows and its ciphertext at once, the device loses access", async () => {
    const home = await newLocation(1);
    const a = await member(home);
    const b = await member(home);
    await call(home, "PUT", `/mailboxes/${a.mailbox}/down/m-1/1`, record("a"));
    await call(home, "PUT", `/mailboxes/${b.mailbox}/down/m-1/1`, record("b"));
    expect((await call(home, "DELETE", `/mailboxes/${a.mailbox}`)).body).toEqual({ ok: true });
    expect([...env.RECORDS.objects.keys()]).toEqual([`${b.mailbox}/down/m-1/1`]);
    for (const table of ["mailboxes", "devices", "records", "mailbox_invitations"]) {
      const column = table === "mailboxes" ? "id" : "mailbox_id";
      expect(env.DB.db.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE ${column} = ?`).get(a.mailbox)).toMatchObject({ n: 0 });
    }
    expect((await call(a.device, "GET", `/mailboxes/${a.mailbox}/down`)).status).toBe(401);     // its device is gone with it
    expect((await call(b.device, "GET", `/mailboxes/${b.mailbox}/down`)).status).toBe(200);
  });

  it("signing a location off deletes all its mailboxes", async () => {
    const home = await newLocation(1);
    const club = await newLocation(2);
    const a = await member(home);
    const b = await member(club);
    await call(home, "PUT", `/mailboxes/${a.mailbox}/down/m-1/1`, record("a"));
    await call(club, "PUT", `/mailboxes/${b.mailbox}/down/m-1/1`, record("b"));
    await dropMailboxesOf(env, home.id);
    expect(env.DB.db.prepare("SELECT COUNT(*) AS n FROM mailboxes").get()).toMatchObject({ n: 1 });
    expect([...env.RECORDS.objects.keys()]).toEqual([`${b.mailbox}/down/m-1/1`]);
  });
});

describe("switching off", () => {
  afterEach(() => undefined);

  it("answers 503 while sharing is off and where there is no bucket, and none of its business for other routes", async () => {
    const home = await newLocation(1);
    env.SHARING = "off";
    expect((await call(home, "POST", `/locations/${home.id}/members`, {})).status).toBe(503);
    env.SHARING = undefined;
    const saved = env.RECORDS;
    (env as { RECORDS?: FakeR2 }).RECORDS = undefined;
    expect((await call(home, "POST", `/locations/${home.id}/members`, {})).status).toBe(503);
    env.RECORDS = saved;
    expect(await handleMailboxes(new Request("https://relay.test/locations"), env, limited, t)).toBeNull();
  });

  it("limits the size of the body", async () => {
    const home = await newLocation(1);
    const { mailbox } = await member(home);
    const huge = record("x".repeat(MAILBOX_LIMITS.BODY_BYTES));
    expect((await call(home, "PUT", `/mailboxes/${mailbox}/down/m-1/1`, huge)).status).toBe(413);
  });
});
