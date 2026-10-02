import { beforeEach, describe, expect, it } from "vitest";
import { MatchCore, Out } from "../src/core";
import { CLOSE, Frame, LIMITS } from "../src/protocol";

class Room {
  now = 1_000_000;
  n = 0;
  core: MatchCore;
  inbox: Record<string, Frame[]> = {};
  closed: Record<string, number> = {};
  private seen = new Set<string>();

  constructor() {
    this.core = MatchCore.reserve("K7M2QX", {
      now: () => this.now,
      randomHex: (bytes) => (++this.n).toString(16).padStart(bytes * 2, "0"),
      uuid: () => "00000000-0000-4000-8000-000000000001",
    });
  }

  apply(outs: Out[]): Out[] {
    for (const o of outs) {
      if (o.frame) (this.inbox[o.to] ??= []).push(o.frame);
      if (o.close !== undefined) this.closed[o.to] = o.close;
    }
    return outs;
  }

  async send(conn: string, frame: Frame): Promise<Out[]> {
    if (!this.seen.has(conn)) {
      this.seen.add(conn);
      this.core.connect(conn);
    }
    return this.apply(await this.core.frame(conn, frame));
  }

  async hello(conn: string, mode: string, site: string, extra: Record<string, unknown> = {}) {
    return this.send(conn, { type: "hello", protocol_version: 1, mode, site, password: "pw", ...extra });
  }

  frames(conn: string, type: string): Frame[] { return (this.inbox[conn] ?? []).filter((f) => f.type === type); }
  last(conn: string, type: string): Frame { const f = this.frames(conn, type); return f[f.length - 1]; }
  token(conn: string): string { return this.last(conn, "welcome").token as string; }

  advance(ms: number) { this.now += ms; return this.apply(this.core.tick()); }
  drop(conn: string) { return this.apply(this.core.disconnect(conn)); }
}

const T20 = { number: 20, multiplier: 3, name: "T20" };
const S1 = { number: 1, multiplier: 1, name: "S1" };

let r: Room;
beforeEach(() => { r = new Room(); });

/** Home (host, players anna + ben) and Club (carl), match started with lives 3. */
async function startedMatch() {
  await r.hello("h", "create", "Home");
  await r.hello("c", "join", "Club");
  await r.send("h", { type: "lobby_set_players", players: ["anna", "ben"] });
  await r.send("c", { type: "lobby_set_players", players: ["carl"] });
  await r.send("h", { type: "lobby_start", lives: 3, order: ["anna", "carl", "ben"] });
}

const turn = (seq: number, player: string, next: string | null, extra: Record<string, unknown> = {}): Frame => ({
  type: "turn", seq, player, throws: [T20], next_player: next, eliminated: [], winner: null, ...extra,
});

describe("lobby", () => {
  it("the creator becomes the host and gets a token", async () => {
    await r.hello("h", "create", "Home");
    const w = r.last("h", "welcome");
    expect(w).toMatchObject({ code: "K7M2QX", site: "Home", host: true, state: "lobby" });
    expect(w.token).toBeTruthy();
    expect(r.last("h", "lobby")).toMatchObject({ host: "Home" });
  });

  it("never keeps the password in the clear", async () => {
    await r.hello("h", "create", "Home", { password: "correct horse" });
    expect(JSON.stringify(r.core.s)).not.toContain("correct horse");
    expect(r.core.s.passwordHash).toHaveLength(64);
  });

  it("refuses another protocol version loudly", async () => {
    await r.hello("h", "create", "Home", { protocol_version: 2 });
    expect(r.closed.h).toBe(CLOSE.UPGRADE);
    expect((r.last("h", "error").message as string)).toContain("upgrade");
  });

  it("joining needs the right password and an unused site name", async () => {
    await r.hello("h", "create", "Home");
    await r.hello("x", "join", "Club", { password: "nope" });
    expect(r.closed.x).toBe(CLOSE.UNAUTHORIZED);
    await r.hello("y", "join", "Home");
    expect(r.closed.y).toBe(CLOSE.CONFLICT);
    await r.hello("c", "join", "Club");
    expect(r.last("c", "welcome")).toMatchObject({ host: false });
    expect(r.last("h", "lobby").sites).toHaveLength(2);
  });

  it("joining a code nobody created is unknown", async () => {
    await r.hello("c", "join", "Club");
    expect(r.closed.c).toBe(CLOSE.UNKNOWN_CODE);
  });

  it("locks the code after too many wrong passwords", async () => {
    await r.hello("h", "create", "Home");
    for (let i = 0; i < LIMITS.MAX_FAILED_HELLOS; i++) await r.hello(`x${i}`, "join", "Club", { password: "nope" });
    await r.hello("c", "join", "Club");
    expect(r.closed.c).toBe(CLOSE.RATE_LIMITED);
    r.advance(LIMITS.LOCK_MS + 1);
    await r.hello("d", "join", "Club");
    expect(r.last("d", "welcome")).toBeTruthy();
  });

  it("a name is in the lobby only once", async () => {
    await r.hello("h", "create", "Home");
    await r.hello("c", "join", "Club");
    await r.send("h", { type: "lobby_set_players", players: ["anna"] });
    await r.send("c", { type: "lobby_set_players", players: ["anna"] });
    expect(r.last("c", "rejected")).toMatchObject({ for: "lobby_set_players" });
    expect(r.last("h", "lobby").sites).toEqual([
      { site: "Home", players: ["anna"], connected: true }, { site: "Club", players: [], connected: true }]);
  });

  it("caps the number of players", async () => {
    await r.hello("h", "create", "Home");
    const many = Array.from({ length: LIMITS.MAX_PLAYERS + 1 }, (_, i) => `p${i}`);
    await r.send("h", { type: "lobby_set_players", players: many });
    expect(r.last("h", "rejected")).toBeTruthy();
  });

  it("only the host starts, with every player once", async () => {
    await r.hello("h", "create", "Home");
    await r.hello("c", "join", "Club");
    await r.send("h", { type: "lobby_set_players", players: ["anna"] });
    await r.send("c", { type: "lobby_set_players", players: ["carl"] });
    await r.send("c", { type: "lobby_start", lives: 3, order: ["anna", "carl"] });
    expect(r.last("c", "rejected").reason).toContain("host");
    await r.send("h", { type: "lobby_start", lives: 3, order: ["anna", "ghost"] });
    expect(r.last("h", "rejected")).toBeTruthy();
    await r.send("h", { type: "lobby_start", lives: 3, order: ["anna", "carl"] });
    expect(r.last("c", "started")).toMatchObject({
      match_id: "00000000-0000-4000-8000-000000000001", lives: 3, order: ["anna", "carl"], owners: { anna: "Home", carl: "Club" } });
    expect(r.core.phase).toBe("playing");
  });

  it("a site that leaves the lobby is removed, the host leaving ends it", async () => {
    await r.hello("h", "create", "Home");
    await r.hello("c", "join", "Club");
    await r.send("c", { type: "leave" });
    expect(r.last("h", "lobby").sites).toHaveLength(1);
    await r.send("h", { type: "leave" });
    expect(r.core.phase).toBe("aborted");
  });

  it("the code expires after ten minutes", async () => {
    await r.hello("h", "create", "Home");
    r.advance(LIMITS.CODE_TTL_MS);
    expect(r.core.phase).toBe("aborted");
    expect(r.last("h", "ended")).toMatchObject({ reason: "aborted" });
  });

  it("a connection that never says hello is closed", async () => {
    r.core.connect("idle");
    r.advance(LIMITS.HELLO_TIMEOUT_MS);
    expect(r.closed.idle).toBe(CLOSE.BAD_REQUEST);
  });

  it("anything but hello first is refused", async () => {
    await r.send("x", { type: "leave" });
    expect(r.closed.x).toBe(CLOSE.BAD_REQUEST);
  });
});

describe("turns", () => {
  it("accepts the turn of the current player and forwards it", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl"));
    expect(r.last("h", "turn_ok")).toMatchObject({ seq: 1 });
    expect(r.last("c", "turn")).toMatchObject({ seq: 1, player: "anna", site: "Home", next_player: "carl" });
    expect(r.frames("h", "turn")).toHaveLength(0);
  });

  it("rejects a player the sender does not own, the wrong turn and a wrong seq", async () => {
    await startedMatch();
    await r.send("c", turn(1, "anna", "carl"));
    expect(r.last("c", "turn_rejected").reason).toContain("not yours");
    await r.send("h", turn(1, "ben", "carl"));
    expect(r.last("h", "turn_rejected").reason).toContain("not that player's turn");
    await r.send("h", turn(2, "anna", "carl"));
    expect(r.last("h", "turn_rejected").reason).toContain("expected seq 1");
    expect(r.core.s.seq).toBe(0);
  });

  it("next_player must be an active player", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "nobody"));
    expect(r.last("h", "turn_rejected").reason).toContain("next_player");
    await r.send("h", turn(1, "anna", null));
    expect(r.last("h", "turn_rejected")).toBeTruthy();
  });

  it("passes the turn on to the named player", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl"));
    await r.send("c", turn(2, "carl", "ben"));
    expect(r.last("c", "turn_ok")).toMatchObject({ seq: 2 });
    await r.send("c", turn(3, "carl", "anna"));
    expect(r.last("c", "turn_rejected")).toBeTruthy();
  });

  it("forwards the live darts of the current player only", async () => {
    await startedMatch();
    await r.send("h", { type: "dart", seq: 1, player: "anna", throws: [T20] });
    expect(r.last("c", "dart")).toMatchObject({ player: "anna", site: "Home" });
    await r.send("c", { type: "dart", seq: 1, player: "carl", throws: [S1] });
    expect(r.frames("h", "dart")).toHaveLength(0);
  });

  it("ends the match with placements when a winner is named", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl"));
    await r.send("c", turn(2, "carl", "ben", { eliminated: ["carl"] }));
    await r.send("h", turn(3, "ben", null, { eliminated: [], winner: null }));
    expect(r.last("h", "turn_rejected")).toBeTruthy();
    await r.send("h", turn(3, "ben", null, { winner: "ben", eliminated: ["anna"] }));
    const ended = r.last("c", "ended");
    expect(ended).toMatchObject({ reason: "finished" });
    expect(ended.placements).toEqual([
      { player: "ben", placement: 1 }, { player: "anna", placement: 2 }, { player: "carl", placement: 3 }]);
    expect(r.core.phase).toBe("finished");
  });

  it("refuses to eliminate a player who is not active", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl", { eliminated: ["ghost"] }));
    expect(r.last("h", "turn_rejected").reason).toContain("eliminated");
  });
});

/** startedMatch played to the end: ben wins, anna is second, carl third. */
async function finishedMatch() {
  await startedMatch();
  await r.send("h", turn(1, "anna", "carl"));
  await r.send("c", turn(2, "carl", "ben", { eliminated: ["carl"] }));
  await r.send("h", turn(3, "ben", "anna", { eliminated: [] }));
  await r.send("h", turn(4, "anna", null, { eliminated: ["anna"], winner: "ben" }));
}

describe("rematch", () => {
  it("opens the lobby again like a local rematch: the first eliminated starts, the winner is last", async () => {
    await finishedMatch();
    expect(r.core.phase).toBe("finished");
    await r.send("h", { type: "rematch" });
    expect(r.core.phase).toBe("lobby");
    expect(r.last("c", "rematch")).toBeTruthy();
    const lobby = r.last("c", "lobby");
    expect(lobby.order).toEqual(["carl", "anna", "ben"]);
    expect(lobby.sites).toEqual([
      { site: "Home", players: ["anna", "ben"], connected: true },
      { site: "Club", players: ["carl"], connected: true },
    ]);
  });

  it("starts a fresh match from there", async () => {
    await finishedMatch();
    await r.send("h", { type: "rematch" });
    await r.send("c", { type: "lobby_set_players", players: ["carl", "tom"] });
    await r.send("h", { type: "lobby_start", lives: 2, order: ["ben", "anna", "carl", "tom"] });
    expect(r.last("c", "started")).toMatchObject({ lives: 2, order: ["ben", "anna", "carl", "tom"] });
    await r.send("h", turn(1, "ben", "anna"));
    expect(r.last("c", "turn")).toMatchObject({ seq: 1, player: "ben" });
    expect(r.frames("h", "turn_rejected")).toHaveLength(0);
  });

  it("is refused while the match is still running", async () => {
    await startedMatch();
    await r.send("h", { type: "rematch" });
    expect(r.last("h", "rejected")).toMatchObject({ for: "rematch", reason: "the match is not finished" });
    expect(r.core.phase).toBe("playing");
  });

  it("is refused for a site that is not the host", async () => {
    await finishedMatch();
    await r.send("c", { type: "rematch" });
    expect(r.last("c", "rejected")).toMatchObject({ for: "rematch", reason: "only the host can start a rematch" });
    expect(r.core.phase).toBe("finished");
  });

  it("an aborted match has no rematch", async () => {
    await startedMatch();
    await r.send("h", { type: "leave" });
    expect(r.core.phase).toBe("aborted");
    await r.send("c", { type: "rematch" });
    expect(r.core.phase).toBe("aborted");
  });

  it("a site that is gone is dropped from the lobby and can join again", async () => {
    await finishedMatch();
    r.drop("c");
    await r.send("h", { type: "rematch" });
    const lobby = r.last("h", "lobby");
    expect(lobby.sites).toEqual([{ site: "Home", players: ["anna", "ben"], connected: true }]);
    expect(lobby.order).toEqual(["anna", "ben"]);
    await r.hello("c2", "join", "Club");
    await r.send("c2", { type: "lobby_set_players", players: ["carl"] });
    await r.send("h", { type: "lobby_start", lives: 3, order: ["carl", "ben", "anna"] });
    expect(r.last("c2", "started")).toBeTruthy();
  });

  it("the lobby expires ten minutes after the rematch, not with the old code", async () => {
    await finishedMatch();
    r.advance(30 * 60 * 1000);
    await r.send("h", { type: "rematch" });
    r.advance(9 * 60 * 1000);
    expect(r.core.phase).toBe("lobby");
    r.advance(2 * 60 * 1000);
    expect(r.core.phase).toBe("aborted");
  });
});

describe("state hashes", () => {
  it("equal hashes pass, differing hashes abort the match", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl"));
    await r.send("h", { type: "ack", seq: 1, hash: "aa" });
    await r.send("c", { type: "ack", seq: 1, hash: "aa" });
    expect(r.core.phase).toBe("playing");
    await r.send("c", turn(2, "carl", "ben"));
    await r.send("h", { type: "ack", seq: 2, hash: "aa" });
    await r.send("c", { type: "ack", seq: 2, hash: "bb" });
    expect(r.last("h", "desync")).toMatchObject({ seq: 2, hashes: { Home: "aa", Club: "bb" } });
    expect(r.last("h", "ended")).toMatchObject({ reason: "desync" });
    expect(r.core.phase).toBe("aborted");
  });
});

describe("disconnects", () => {
  it("pauses, then resumes when the site rejoins and replays missed turns", async () => {
    await startedMatch();
    const token = r.token("c");
    r.drop("c");
    expect(r.core.phase).toBe("paused");
    expect(r.last("h", "paused")).toMatchObject({ site: "Club", reason: "disconnect" });
    await r.send("h", turn(2, "anna", "carl"));
    expect(r.last("h", "turn_rejected").reason).toContain("paused");
    await r.hello("c2", "rejoin", "Club", { token, last_seq: 0 });
    expect(r.last("c2", "welcome")).toMatchObject({ site: "Club", host: false });
    expect(r.last("c2", "started")).toBeTruthy();
    expect(r.last("h", "resumed")).toMatchObject({ site: "Club" });
    expect(r.core.phase).toBe("playing");
  });

  it("replays the turns the site missed", async () => {
    await startedMatch();
    const token = r.token("c");
    await r.send("h", turn(1, "anna", "carl"));
    r.drop("c");
    await r.hello("c2", "rejoin", "Club", { token, last_seq: 0 });
    expect(r.frames("c2", "turn")).toHaveLength(1);
    expect(r.last("c2", "turn")).toMatchObject({ seq: 1, player: "anna" });
  });

  it("refuses a rejoin with the wrong token", async () => {
    await startedMatch();
    r.drop("c");
    await r.hello("c2", "rejoin", "Club", { token: "wrong", last_seq: 0 });
    expect(r.closed.c2).toBe(CLOSE.UNAUTHORIZED);
  });

  it("asks the host after the window and continues without the site", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl"));
    r.drop("c");
    r.advance(LIMITS.REJOIN_WINDOW_MS);
    expect(r.last("h", "decision_needed")).toMatchObject({ sites: [{ site: "Club", players: ["carl"] }] });
    await r.send("h", { type: "decision", choice: "continue" });
    expect(r.last("h", "site_dropped")).toMatchObject({ next_player: "ben", sites: [{ site: "Club", players: ["carl"] }] });
    expect(r.core.phase).toBe("playing");
    await r.send("h", turn(2, "ben", "anna"));
    expect(r.last("h", "turn_ok")).toBeTruthy();
  });

  it("the match ends when the dropped site's players were all but one", async () => {
    await r.hello("h", "create", "Home");
    await r.hello("c", "join", "Club");
    await r.send("h", { type: "lobby_set_players", players: ["anna"] });
    await r.send("c", { type: "lobby_set_players", players: ["carl"] });
    await r.send("h", { type: "lobby_start", lives: 3, order: ["anna", "carl"] });
    r.drop("c");
    r.advance(LIMITS.REJOIN_WINDOW_MS);
    await r.send("h", { type: "decision", choice: "continue" });
    expect(r.last("h", "ended")).toMatchObject({ reason: "finished", placements: [{ player: "anna", placement: 1 }, { player: "carl", placement: 2 }] });
  });

  it("the host can abort instead", async () => {
    await startedMatch();
    r.drop("c");
    r.advance(LIMITS.REJOIN_WINDOW_MS);
    await r.send("h", { type: "decision", choice: "abort" });
    expect(r.last("h", "ended")).toMatchObject({ reason: "aborted", placements: [] });
    expect(r.core.phase).toBe("aborted");
  });

  it("only the host decides", async () => {
    await r.hello("h", "create", "Home");
    await r.hello("c", "join", "Club");
    await r.hello("d", "join", "Third");
    await r.send("h", { type: "lobby_set_players", players: ["anna"] });
    await r.send("c", { type: "lobby_set_players", players: ["carl"] });
    await r.send("d", { type: "lobby_set_players", players: ["ben"] });
    await r.send("h", { type: "lobby_start", lives: 3, order: ["anna", "carl", "ben"] });
    r.drop("c");
    r.advance(LIMITS.REJOIN_WINDOW_MS);
    await r.send("d", { type: "decision", choice: "continue" });
    expect(r.last("d", "rejected")).toBeTruthy();
  });

  it("a dropped host ends the match once the window is over", async () => {
    await startedMatch();
    r.drop("h");
    r.advance(LIMITS.REJOIN_WINDOW_MS);
    expect(r.core.phase).toBe("aborted");
  });

  it("a site that leaves is dropped without waiting for the window", async () => {
    await startedMatch();
    await r.send("c", { type: "leave" });
    r.advance(0);
    expect(r.last("h", "decision_needed")).toBeTruthy();
  });
});

describe("persistence", () => {
  it("a restored state behaves the same", async () => {
    await startedMatch();
    await r.send("h", turn(1, "anna", "carl"));
    const restored = new MatchCore(JSON.parse(JSON.stringify(r.core.s)), (r.core as unknown as { deps: never }).deps);
    r.core = restored;
    await r.send("c", turn(2, "carl", "ben"));
    expect(r.last("c", "turn_ok")).toMatchObject({ seq: 2 });
  });
});
