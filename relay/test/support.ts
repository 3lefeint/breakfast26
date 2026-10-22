// A D1 over node:sqlite with the real migrations, an R2 in memory and signing helpers for the tests of the routes.
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { b64urlEncode, sha256Hex, signingString } from "../src/locations";

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

export class FakeD1 {
  db = new DatabaseSync(":memory:");
  constructor() {
    for (const file of readdirSync("migrations").sort()) this.db.exec(readFileSync(`migrations/${file}`, "utf8"));
  }
  prepare(sql: string) { return new Statement(this.db, sql); }
  async batch(statements: Statement[]) {
    const results = [];
    for (const s of statements) results.push(await s.run());
    return results;
  }
  count(sql: string, ...params: unknown[]): number {
    return Number((this.db.prepare(sql).get(...(params as never[])) as { n: number }).n);
  }
}

export class FakeR2 {
  objects = new Map<string, string>();
  async put(key: string, value: string | Uint8Array) { this.objects.set(key, typeof value === "string" ? value : new TextDecoder().decode(value)); }
  async get(key: string) {
    const v = this.objects.get(key);
    return v === undefined ? null : { text: async () => v, arrayBuffer: async () => new TextEncoder().encode(v).buffer };
  }
  async delete(keys: string | string[]) { for (const k of Array.isArray(keys) ? keys : [keys]) this.objects.delete(k); }
  async list({ prefix = "" }: { prefix?: string }) {
    return { objects: [...this.objects.keys()].filter((k) => k.startsWith(prefix)).map((key) => ({ key })), truncated: false, cursor: undefined };
  }
}

export async function keyPair() {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey) as ArrayBuffer);
  return { pair, publicKey: b64urlEncode(raw) };
}

export const id = (n: number) => n.toString(16).padStart(32, "0");

export interface Site { id: string; pair: CryptoKeyPair }

/** Register a location straight in the database. */
export async function newLocation(db: FakeD1, n: number, name = `Site ${n}`): Promise<Site> {
  const { pair, publicKey } = await keyPair();
  await db.prepare("INSERT INTO locations (id, name, public_key) VALUES (?, ?, ?)").bind(id(n), name, publicKey).run();
  return { id: id(n), pair };
}

/** A request signed by a location. */
export async function signed(site: Site | null, method: string, path: string, now: number, body?: unknown): Promise<Request> {
  const raw = body === undefined ? "" : JSON.stringify(body);
  const headers: Record<string, string> = {};
  if (site) {
    const timestamp = String(Math.floor(now / 1000));
    const message = signingString(method, path.split("?")[0], timestamp, await sha256Hex(raw));
    headers["x-location"] = site.id;
    headers["x-timestamp"] = timestamp;
    headers["x-signature"] = b64urlEncode(new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, site.pair.privateKey, new TextEncoder().encode(message))));
  }
  return new Request(`https://relay.test${path}`, { method, body: raw === "" ? undefined : raw, headers });
}
