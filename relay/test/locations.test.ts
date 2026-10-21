import { describe, expect, it } from "vitest";
import { b64urlDecode, b64urlEncode, freshTimestamp, sha256Hex, signingString, validName, validPublicKey, validToken, verifySignature } from "../src/locations";

async function keyPair() {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey) as ArrayBuffer);
  return { pair, publicKey: b64urlEncode(raw) };
}

async function sign(pair: CryptoKeyPair, message: string) {
  return b64urlEncode(new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, pair.privateKey, new TextEncoder().encode(message))));
}

describe("signed requests", () => {
  it("verifies a signature of the request and refuses any change to it", async () => {
    const { pair, publicKey } = await keyPair();
    const message = signingString("POST", "/invitations/redeem", "1760000000", await sha256Hex('{"token":"x"}'));
    const signature = await sign(pair, message);
    expect(await verifySignature(publicKey, message, signature)).toBe(true);
    expect(await verifySignature(publicKey, message.replace("POST", "GET"), signature)).toBe(false);
    expect(await verifySignature(publicKey, message.replace("redeem", "other"), signature)).toBe(false);
    expect(await verifySignature(publicKey, signingString("POST", "/invitations/redeem", "1760000001", await sha256Hex('{"token":"x"}')), signature)).toBe(false);
  });

  it("refuses a signature of another key and malformed input", async () => {
    const a = await keyPair();
    const b = await keyPair();
    const signature = await sign(a.pair, "m");
    expect(await verifySignature(b.publicKey, "m", signature)).toBe(false);
    expect(await verifySignature("short", "m", signature)).toBe(false);
    expect(await verifySignature(a.publicKey, "m", "short")).toBe(false);
    expect(await verifySignature(a.publicKey, "m", "A".repeat(86))).toBe(false);
  });

  it("accepts a timestamp only within the clock skew", () => {
    const now = 1_760_000_000_000;
    expect(freshTimestamp("1760000000", now)).toBe(true);
    expect(freshTimestamp(String(1_760_000_000 - 299), now)).toBe(true);
    expect(freshTimestamp(String(1_760_000_000 + 301), now)).toBe(false);
    expect(freshTimestamp(String(1_760_000_000 - 301), now)).toBe(false);
    expect(freshTimestamp(null, now)).toBe(false);
    expect(freshTimestamp("1.5e9", now)).toBe(false);
  });
});

describe("values", () => {
  it("round-trips base64url", () => {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    expect(b64urlDecode(b64urlEncode(bytes))).toEqual(bytes);
  });

  it("checks names, keys and tokens", () => {
    expect(validName("Home")).toBe(true);
    expect(validName("Dart club 1")).toBe(true);
    expect(validName("")).toBe(false);
    expect(validName("   ")).toBe(false);
    expect(validName("x".repeat(25))).toBe(false);
    expect(validName("bad\nname")).toBe(false);
    expect(validPublicKey("A".repeat(43))).toBe(true);
    expect(validPublicKey("A".repeat(44))).toBe(false);
    expect(validToken("a".repeat(32))).toBe(true);
    expect(validToken("a".repeat(31))).toBe(false);
    expect(validToken(5)).toBe(false);
  });
});
