# Online Elimination relay — design decisions

Working record for GitHub issue #10, decided step by step with pmo on the
`online-elimination` branch. Each entry: the question, the decision, why.

## 1. Where the relay lives and what it is written in

- **Decision:** a top-level `relay/` folder in this repository, on the branch
  `online-elimination` for now; written as a **Cloudflare Worker in TypeScript**
  from the start, run locally with wrangler/miniflare.
- **Why:** the relay must not import anything from `breakfast/`, so it can move to
  its own repository later (`git filter-repo --subdirectory-filter relay`). Building
  the real target from the start avoids a port. The Python side (the client in
  `breakfast/`) and the Worker agree through a written protocol and shared test vectors.

## 2. Version skew

- **Decision:** strict. The join handshake carries an integer `protocol_version`;
  the relay accepts only versions it knows and otherwise closes the connection with
  a dedicated close code and a message telling the user to upgrade.
- **Why:** a mismatch must fail loudly instead of corrupting the match state; no
  negotiation code to maintain per version.

## 3. Pairing

- **Decision:** a short join code per match. The host creates the match at the relay and
  gets the code (about 6 characters, no look-alike letters), valid 10 minutes or until the
  match starts. Every other site enters the same code. Failed attempts are limited per
  sender and the relay rate-limits joins.
- **Why:** easy to say over the phone, expires on its own, no long-lived secret to revoke.

## 4. Where the rules run and how turns are gated

- **Decision:** the relay is an ordered protocol, the rules stay in the client. The relay
  numbers and distributes the turns, checks order and sender, and compares a state hash
  of the sites after every turn. The rules run only once, in Python (`elimination.py`).
  A site evaluates its own board only on its own player's turn; remote turns arrive from
  the relay.
- **Why:** no second implementation of the Elimination rules (undo, corrections, freipass)
  to keep in sync; a diverging site is detected by the hash instead of silently playing on.

## 5. Remote turns: audio and TV

- **Decision:** darts of a remote player are relayed live and shown on the local TV like
  local ones (with the board markers). The calls at the end of the turn (score, life lost,
  name, target) play locally as usual. Between turns the TV shows who it is waiting for.
  Only the per-dart miss comment is dropped for remote players.
- **Why:** the same experience at every site, at the cost of three small live messages
  per turn. The live darts are informational; the authoritative event is the turn end.

## 6. Disconnects

- **Decision:** pause, rejoin, then a decision. The match pauses for everybody ("waiting for
  <site>"). The site can come back within 3 minutes with its session and continues exactly
  where it was. After that the host decides: play on without it (its players are eliminated)
  or abort the match.
- **Why:** a short network drop must not decide a match, and nobody waits forever.

## 7. Scope: lobby, order, limits

- **Decision:** a lobby. Every site adds its local players. The host chooses lives and the
  order (random or by hand) and starts. A name can be in the lobby only once (see 8: a name is
  the identity of a player, so the lobby refuses a name that is already taken). Limits: up to 6 sites and 12 players in total. Several local players per site work
  as in local Elimination.
- **Why:** one global order is needed by the rules; the host decides it like at a real table.

## 8. Statistics

- **Decision:** every site stores everything of the match in its own `stats.db`: the turns,
  darts and positions of all players, with the `match_id` assigned by the relay. The
  placements come from the relay as the single source of truth, so all sites store the same
  result.
- **Remote players are treated exactly like local ones:** a name is the identity of a player.
  The same people may already have played X01 together on Autodarts, so they can exist in the
  players table already. No hidden flag, no site label, no extra column.
- **Consequence:** the lobby must refuse a name that is already in it (two sites cannot both
  have "anna" in one match).

## 9. Security

- **Decision:** join codes expire and work once per match; the relay rate-limits join
  attempts per IP and per code; every site gets a random session token after joining, which
  authenticates each message and is used to rejoin. On top of the code the host sets a
  shared match password that every site must know. The relay stores only a salted hash of
  it and counts failed attempts. No accounts.
- **Why:** the relay is reachable from the internet; a guessed or forwarded code alone must
  not be enough to get into a match. Accounts would be a project of their own and are
  too much for a circle of friends.

## 10. Testing

- **Decision:** shared protocol test cases (JSON) used by both the Worker (vitest with
  miniflare) and the Python client (against a fake relay), a documented manual smoke test
  with two Breakfast instances against `wrangler dev`, and an automated end-to-end test in
  which two real Python clients play a whole match against a locally started Worker.
- **Why:** differences between the two sides show up in the tests, not in a live match;
  the end-to-end test is the closest to real use and needs wrangler in the test environment.
