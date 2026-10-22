# Relay protocol, version 3

How Breakfast installations ("sites") play one Elimination match over the relay.
Design decisions: `DESIGN.md`. Both sides are tested against the examples in
`protocol-tests/messages.json`.

## Transport

- `POST /api/matches` with `{"protocol_version": 3}` reserves a **join code** and answers
  `{"code": "K7M2QX", "expires_in_s": 600}`. The code has 6 characters from
  `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` and is valid 10 minutes, or until the match starts. A registered location
  signs the request (headers as under "Locations") and may add `site` (its name in the match): the match is then
  listed for the locations linked to it.
- `GET /ws/<code>` upgrades to a WebSocket (one Durable Object per code). Every frame is one
  JSON object with a string field `type`. The first frame from the client must be `hello`
  within 10 seconds.
- Anything the relay does not like closes the connection with a close code (below) after an
  `error` frame.

## Close codes

| Code | Meaning |
|------|---------|
| 4400 | Malformed frame, unknown type, or not allowed in the current state |
| 4401 | Wrong password or session token |
| 4404 | Unknown or expired code |
| 4409 | Conflict: name already in the lobby, match already started, not the host |
| 4410 | The match is over (finished, aborted, or the code expired) |
| 4426 | Protocol version not supported: please upgrade Breakfast |
| 4429 | Too many attempts, try again later |

## Match states

`reserved` -> `lobby` -> `playing` -> `finished` | `aborted`. While `playing` a site that drops
puts the match into `paused` until it rejoins or the host decides. A `finished` match goes back to
`lobby` when the host asks for a rematch.

## Client to relay

| type | fields | notes |
|------|--------|-------|
| `hello` | `protocol_version`, `mode` (`create` \| `join` \| `rejoin`), `site`; `password` for `create` and `join`, or `ticket` instead of the password for `join`; for `rejoin` also `token`, `last_seq` and `epoch` (the last `epoch` the site knows, see `undone`) | `create` only on a reserved code and makes the sender the host; the password is set here |
| `lobby_set_players` | `players` (list of names) | the sender's local players, replaces its earlier list (and takes back the site's `ready`); names are unique across the lobby |
| `lobby_set_ready` | `ready` (bool) | the sender is ready to start; passed on in `lobby`, the relay does not hold the start back |
| `lobby_start` | `lives` (1 to 10), `order` (all lobby players once) | host only; at least 2 players, at most 12 players and 6 sites |
| `dart` | `seq`, `player`, `throws` | live darts of the turn in progress, informational, relayed as is |
| `turn` | `seq`, `player`, `throws`, `next_player`, `eliminated`, `winner` | the finished turn, authoritative |
| `turn_corrected` | `seq`, `player`, `throws`, `next_player`, `eliminated`, `winner`, optional `total` | the site that threw the last turn replaces it (other darts, or with `total` another total for the same darts, 0 to 180), also the turn that ended the match; checked like a turn against the state before it; refused while paused and after sites were dropped |
| `undo` | `seq` | take the last turn back (`seq` is that turn); only the site that threw it may, also after the turn that ended the match; refused while paused and after sites were dropped |
| `ack` | `seq`, `hash` | the sender applied turn `seq` and its game state has this hash |
| `decision` | `choice` (`continue` \| `abort`) | host only, after `decision_needed` |
| `rematch` | | host only, once the match is `finished`: back to the lobby with the same sites and players |
| `leave` | | leaves for good |

A **throw** is `{"number": 20, "multiplier": 3, "name": "T20"}` (`number` 0 to 20 or 25) plus optionally `x`, `y`
(Autodarts coordinates) and `entry`. `seq` counts the finished turns, starting at 1; a `dart`
carries the `seq` of the turn it belongs to.

`turn.next_player` is the player up next as the sender's rules computed it (`null` when the
match is over), `turn.eliminated` the players that lost their last life with this turn, and
`turn.winner` the winner if this turn ended the match.

## Relay to client

| type | fields | notes |
|------|--------|-------|
| `welcome` | `code`, `site`, `token`, `host` (bool), `state`, `epoch` | answer to a valid `hello`; the `token` authenticates a later `rejoin` |
| `lobby` | `host`, `sites` (list of `{site, players, connected, ready}`), `lives`, `order` | sent on every lobby change; the host always counts as ready |
| `started` | `match_id`, `lives`, `order`, `owners` (player -> site) | the match begins; `current_player` is `order[0]` |
| `rematch` | | the host asked for a rematch; followed by a `lobby` whose `order` is that of a local rematch (the first eliminated starts, the winner is last), without sites that are gone |
| `dart` | as received, plus `site` | forwarded to the other sites |
| `turn` | as received, plus `site` | forwarded to the other sites, in `seq` order |
| `turn_ok` | `seq`, `epoch` (only after a correction) | to the sender: its turn or correction was accepted |
| `turn_rejected` | `seq`, `reason` | not the sender's player, not that player's turn, or a wrong `seq` |
| `rejected` | `for` (the frame type), `reason` | a lobby frame was refused (name taken, not the host, ...); the connection stays open |
| `turn_corrected` | as received, plus `site` and `epoch` | forwarded to the other sites: the last turn was replaced, they play it again; a match that was finished is `playing` again unless the corrected turn ends it, in which case `ended` follows. A turn with a corrected total comes again as `turn` (with `total`) in a replay after `resync` |
| `undone` | `seq`, `player`, `site`, `epoch` | to every site, the sender included: turn `seq` was taken back, `player` is up again and every site walks its game back (a match that was finished is `playing` again); `epoch` counts the take-backs of the match |
| `undo_rejected` | `seq`, `reason` | to the sender: not the last turn, not its turn, paused, not being played, or sites were dropped after that turn |
| `resync` | | to a site that rejoins with an old `epoch`: it missed a take-back, so it starts the match again from the log that follows (`started`, then every turn) |
| `paused` | `reason` (`disconnect`), `site`, `rejoin_until` (epoch ms) | a site dropped |
| `resumed` | `site` | it came back |
| `decision_needed` | `sites` (list of `{site, players}`) | to the host: the rejoin window (3 minutes) is over |
| `site_dropped` | `sites` (list of `{site, players}`), `next_player` | the host chose to continue: those players are eliminated now, in this order; `next_player` is who is up (`null` if the match is over) |
| `desync` | `seq`, `hashes` (site -> hash) | the sites disagree about the game state; the match is aborted |
| `ended` | `reason` (`finished` \| `aborted` \| `desync`), `placements` (list of `{player, placement}`) | the result; placements come only from the relay |
| `error` | `code`, `message` | followed by the close |

## Rules the relay enforces

- Only the host sends `lobby_start` and `decision`.
- A `turn` is accepted if its sender owns `player`, `player` is the current player, and `seq` is
  the next number. The relay then sets the current player to `next_player` (must be an active
  player), removes `eliminated` from the active players and records their order. When `winner` is
  set the match ends and `ended` carries the placements: the winner first, then the eliminated
  players in reverse order of elimination.
- When every connected site has acked a `seq`, their hashes must be equal, otherwise `desync`.
- Failed `hello`s (wrong password or token) are counted per code; after 8 the code is locked for
  5 minutes. Creating codes and joining are also limited per IP address.
- The relay stores the ordered turn log; `rejoin` with `last_seq` gets the missed `turn` frames
  again before `resumed`.
- A site that drops is rejoinable with its `token` for 3 minutes. After that the host gets
  `decision_needed`: `continue` eliminates the site's players (`site_dropped`), `abort` ends the
  match with `ended` (`aborted`) and no placements.

## Locations

Separate from the match protocol: plain HTTP routes, stored in D1 (`migrations/0002_locations.sql`). A location is an
installation registered with an Ed25519 public key (32 raw bytes, base64url). Requests other than the registration carry
`x-location` (its id), `x-timestamp` (unix seconds, at most 5 minutes off) and `x-signature` (base64url Ed25519 signature
of `METHOD\nPATH\nTIMESTAMP\nSHA256-HEX(BODY)`; the body is empty for `GET` and `DELETE`).

| Route | Signed by | Purpose |
|---|---|---|
| `POST /locations` `{name, public_key}` | the new key itself (`x-timestamp`, `x-signature` only) | register; returns `{id}`; registering the same key again returns the same id |
| `POST /locations/<id>/invitations` | that location | a one-time invitation; returns `{token, expires_at}` (valid 7 days, at most 5 open) |
| `POST /invitations/redeem` `{token}` | the redeeming location | link the two locations; returns `{link_id, peer: {id, name}}` |
| `GET /locations/<id>/links` | that location | `{links: [{link_id, kind, created_at, peer}]}` |
| `DELETE /links/<id>` | either side of the link | remove the link |
| `PATCH /locations/<id>` `{name}` | that location | rename it; the id and the links stay |
| `DELETE /locations/<id>` | that location | delete it with its links, open invitations and open matches |
| `GET /locations/<id>/open-matches` | that location | `{matches: [{code, location: {id, name}, site, sites, players}]}`: the matches in the lobby that locations linked to it opened (at most 20) |
| `POST /locations/<id>/join-ticket` `{code}` | that location | a one-time ticket (valid 2 minutes, at most 10 open per match) to join that open match with `hello.ticket` instead of the password; 404 unless the match belongs to a linked location |

Only the hash of a token is stored. An unknown, used or expired token answers 404 without telling which. Registering,
inviting, redeeming and reading are limited per IP address or per location. Links have a `kind` (`play` for now).

## Mailboxes

Where the match records of a member travel (sharing, #26): plain HTTP routes, the index in D1 (`migrations/0004_mailboxes.sql`),
the ciphertext in R2 (binding `RECORDS`, object `<mailbox>/<channel>/<match id>/<revision>`). The relay sees ciphertext and a
small clear envelope (`envelope_version`, `game_mode`, `match_id`, `revision`, `deleted`, `size`, `hash` of the ciphertext,
`created_at`), never the content. A mailbox belongs to one member at one location and has two channels: `down` (the location
writes, the member's devices read) and `up` (a device writes, the location reads; off until the location switches it on).

A location signs as in "Locations". A member device signs the same way with its own Ed25519 key and sends `x-device` (its
id) instead of `x-location`; the signature covers the path, not the query. Times are epoch milliseconds.

| Route | Signed by | Purpose |
|---|---|---|
| `POST /locations/<id>/members` | that location | a mailbox with a one-time invitation for a member; returns `{mailbox_id, token, expires_at}` (valid 7 days, at most 200 mailboxes per location) |
| `POST /mailboxes/<id>/invitations` | the location of the mailbox | a new invitation for the same mailbox (a lost link), at most 3 open |
| `POST /mailbox-invitations/redeem` `{token, public_key}` | the new key itself (`x-timestamp`, `x-signature` only) | a device registers its key; returns `{mailbox_id, device_id, up, location: {id, name}}`, at most 5 devices per mailbox |
| `PATCH /mailboxes/<id>` `{up}` | the location | switch the `up` channel on or off |
| `DELETE /mailboxes/<id>` | the location | delete the mailbox with its devices, invitations, records and ciphertext at once |
| `PUT /mailboxes/<id>/<down\|up>/<match id>/<revision>` `{envelope_version, game_mode, deleted, ciphertext}` | the location (`down`), a device (`up`) | put a record (`ciphertext` base64url, at most 256 KB; a deletion has `deleted: true` and no ciphertext); the same record again changes nothing, another content for the same revision is 409, an older revision than the newest is 409; older revisions of the match are removed |
| `GET /mailboxes/<id>/<down\|up>?since=<cursor>&limit=<n>` | a device (`down`), the location (`up`) | `{records: [{seq, match_id, revision, game_mode, deleted, size, hash, envelope_version, created_at}], next}` after the cursor (at most 100) |
| `GET /mailboxes/<id>/<down\|up>/<match id>/<revision>` | the same | the record with its `ciphertext` (null for a deletion) |

Limits: a record 256 KB, 200 records per writer and day, 1000 records and 20 MB per mailbox (413 or 429). Only the hash of an
invitation token is stored, an unknown, used or expired one answers 404. A mailbox of someone else and an unknown mailbox
both answer 404. The routes answer 503 when the `RECORDS` bucket is missing or the variable `SHARING` is `off`; signing a
location off deletes its mailboxes.

## Voice chat

Browsers of the sites talk to each other directly (WebRTC, Opus); the relay serves the page and passes on the
signaling. The audio never goes through it.

- `GET /voice` and `GET /voice.js`: the voice chat page (no external libraries, strict content security policy). It reads
  `code`, `site`, `ticket` and `lang` from the part of its address after `#`, which never reaches a server. It lives here
  because a browser gives the microphone only to a secure page.
- `POST /api/matches/<code>/voice-ticket` `{site, token}`: `token` is the match token of the site from `welcome`. Answers
  `{ticket}` (401 for a wrong token; wrong tries count towards the lock of the code). A new ticket replaces the old one; it
  lasts as long as the match.
- `GET /voice/<code>`: WebSocket to the signaling room of the match (a Durable Object per code). The first frame must be
  `join` within 10 seconds.

| Direction | type | fields | notes |
|-----------|------|--------|-------|
| client | `join` | `site`, `ticket` | refused with 4401 unless the ticket is the current one of that site; the same site joining again replaces its older connection (4409) |
| client | `signal` | `to` (peer), `data` (`{description}` or `{candidate}`) | passed on to that peer |
| client | `mute` | `muted` (bool) | passed on to the others |
| relay | `joined` | `peer`, `peers` (list of `{peer, site, muted}`), `ice` (ICE servers) | the new peer then sends the offers |
| relay | `peer-joined` / `peer-left` | `peer` (and `site`) | |
| relay | `signal` | `from`, `data` | |
| relay | `mute` | `peer`, `muted` | |
| relay | `error` | `code`, `message` | followed by the close (4400 bad frame, 4401 not allowed, 4409 replaced or full) |

At most 6 peers, frames up to 16 KB. `ice` is STUN (`stun.cloudflare.com`); with the Worker secrets `TURN_KEY_ID` and
`TURN_KEY_API_TOKEN` of a Cloudflare TURN key it also carries TURN servers with credentials that run out after a day.
