import { describe, expect, it } from "vitest";
import { iceServers, validateVoiceFrame } from "../src/voice";

const peer = "0123456789abcdef";

describe("voice frames", () => {
  it("accepts the frames of the room", () => {
    expect(validateVoiceFrame({ type: "join", site: "Home", ticket: "abc" })).toBeNull();
    expect(validateVoiceFrame({ type: "signal", to: peer, data: { description: { type: "offer", sdp: "v=0" } } })).toBeNull();
    expect(validateVoiceFrame({ type: "signal", to: peer, data: { candidate: { candidate: "candidate:1" } } })).toBeNull();
    expect(validateVoiceFrame({ type: "mute", muted: true })).toBeNull();
  });

  it("refuses everything else", () => {
    expect(validateVoiceFrame("join")).not.toBeNull();
    expect(validateVoiceFrame({ type: "join", site: " Home", ticket: "abc" })).not.toBeNull();
    expect(validateVoiceFrame({ type: "join", site: "Home" })).not.toBeNull();
    expect(validateVoiceFrame({ type: "join", site: "Home", ticket: "x".repeat(129) })).not.toBeNull();
    expect(validateVoiceFrame({ type: "signal", to: "nobody", data: { candidate: {} } })).not.toBeNull();
    expect(validateVoiceFrame({ type: "signal", to: peer, data: {} })).not.toBeNull();
    expect(validateVoiceFrame({ type: "signal", to: peer, data: "offer" })).not.toBeNull();
    expect(validateVoiceFrame({ type: "mute", muted: "yes" })).not.toBeNull();
    expect(validateVoiceFrame({ type: "shout" })).not.toBeNull();
  });
});

describe("ice servers", () => {
  const stun = [{ urls: ["stun:stun.cloudflare.com:3478"] }];

  it("is STUN only without a TURN key", async () => {
    expect(await iceServers({})).toEqual(stun);
    expect(await iceServers({ TURN_KEY_ID: "id" })).toEqual(stun);
  });

  it("asks Cloudflare for short-lived credentials with the key and drops the port that browsers block", async () => {
    let seen: { url: string; init: RequestInit } | null = null;
    const fake = (async (url: string, init: RequestInit) => {
      seen = { url, init };
      return new Response(JSON.stringify({ iceServers: [
        { urls: ["stun:stun.cloudflare.com:3478"] },
        { urls: ["turn:turn.cloudflare.com:3478?transport=udp", "turn:turn.cloudflare.com:53?transport=udp", "turns:turn.cloudflare.com:443?transport=tcp"], username: "u", credential: "c" },
      ] }), { status: 201 });
    }) as unknown as typeof fetch;
    const servers = await iceServers({ TURN_KEY_ID: "key id", TURN_KEY_API_TOKEN: "secret" }, fake);
    expect(seen!.url).toBe("https://rtc.live.cloudflare.com/v1/turn/keys/key%20id/credentials/generate-ice-servers");
    expect((seen!.init.headers as Record<string, string>).authorization).toBe("Bearer secret");
    expect(JSON.parse(seen!.init.body as string)).toEqual({ ttl: 86400 });
    expect(servers[1]).toEqual({ urls: ["turn:turn.cloudflare.com:3478?transport=udp", "turns:turn.cloudflare.com:443?transport=tcp"], username: "u", credential: "c" });
  });

  it("falls back to STUN when Cloudflare says no or is not reached", async () => {
    const refuse = (async () => new Response("no", { status: 403 })) as unknown as typeof fetch;
    const broken = (async () => { throw new Error("down"); }) as unknown as typeof fetch;
    expect(await iceServers({ TURN_KEY_ID: "id", TURN_KEY_API_TOKEN: "t" }, refuse)).toEqual(stun);
    expect(await iceServers({ TURN_KEY_ID: "id", TURN_KEY_API_TOKEN: "t" }, broken)).toEqual(stun);
  });
});
