# Relay protocol, version 4

How Breakfast installations ("sites") play one Elimination match over the relay.
Design decisions: `DESIGN.md`. Both sides are tested against the examples in
`protocol-tests/messages.json`.

## Transport

- `POST /api/matches` with `{"protocol_version": 4}` reserves a **join code** and answers
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
| `lobby_set_ready` | `ready` (bool) | the sender is ready to start; passed on in `lobby`, the relay does not hold the start back (Breakfast does not use it any more) |
| `lobby_set_rules` | `game` (`elimination` \| `x01`, default `elimination`), `lives` (1 to 10) for Elimination, `rules` for X01 | host only, in the lobby: the other sites see the rules in the `lobby` frame |
| `lobby_start` | `game`, `lives` or `rules` as in `lobby_set_rules`, `order` (all lobby players once) | host only; at least 2 players, at most 12 players and 6 sites |
| `dart` | `seq`, `player`, `throws` | live darts of the turn in progress, informational, relayed as is |
| `turn` | `seq`, `player`, `throws`, `next_player`, `eliminated`, `winner`, optional `order`, `rematch_order` | the finished turn, authoritative |
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

**X01.** `game: "x01"` plays an X01 match. `rules` are `{start (2 to 1501), in_mode, out_mode (straight, double or master), legs (1 to 25),
bull_off (bool), max_rounds (null or 1 to 99)}`; the host sets them in the lobby and the other sites only see them. Nobody is eliminated
(`eliminated` is always empty), `next_player` is any player of the match, `winner` is the player who won the last leg. The bull-off is
played as turns of one dart each; the turn that ends it carries `order`, the play order from there on (a permutation of the players), and the
turn that ends the match carries `rematch_order`, the order a rematch starts with (the relay proposes it in the lobby). An `undo` or a
corrected turn also takes back or replaces the `order` it set. The relay does not follow the scores; the sites do, and the `ack` hashes
show a site that does not. The placements of an ended match are the winner first and the others in the play order. The players of a lost
site cannot be dropped from an X01 match: after `decision_needed` only `abort` is accepted.

## Relay to client

| type | fields | notes |
|------|--------|-------|
| `welcome` | `code`, `site`, `token`, `host` (bool), `state`, `epoch` | answer to a valid `hello`; the `token` authenticates a later `rejoin` |
| `lobby` | `host`, `sites` (list of `{site, players, connected, ready}`), `lives`, `order`, `game`, `rules` (X01 only, else `null`) | sent on every lobby change; the host always counts as ready |
| `started` | `match_id`, `game`, `lives` (Elimination) or `rules` (X01), `order`, `owners` (player -> site) | the match begins; `current_player` is `order[0]` |
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
| `ended` | `reason` (`finished` \| `aborted` \| `desync`), `placements` (list of `{player, placement}`) | the result; placements come only from the relay. Breakfast closes the match at the site at once on `aborted` (the host ended or left it, or the code ran out) |
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
| `GET /locations/<id>/open-matches` | that location | `{matches: [{code, location: {id, name}, site, game, sites, players}]}` (`game` is `elimination` or `x01`): the matches in the lobby that locations linked to it opened (at most 20) |
| `POST /locations/<id>/join-ticket` `{code}` | that location | a one-time ticket (valid 2 minutes, at most 10 open per match) to join that open match with `hello.ticket` instead of the password; 404 unless the match belongs to a linked location |

Only the hash of a token is stored. An unknown, used or expired token answers 404 without telling which. Registering,
inviting, redeeming and reading are limited per IP address or per location. Links have a `kind` (`play` for now).

## Circle

How the installations of a group of friends share their matches (sharing, #26): plain HTTP routes, the index and the rules in D1
(`migrations/0004_circle.sql`), the records as plain JSON in R2 (binding `RECORDS`, object `circle/<match id>`, the newest revision of a
match only). The relay can read the records (decided for now: simple and debuggable). The model, in short: a **site** is a registered
location (see "Locations") that the admin approved; a **circle player** is a person of the circle; a **mapping** says which player of
a site (by his lower-case name) is which circle player; a **rule** lists the sites that get the matches of a circle player. A finished
match goes to every site in the rule of a circle player who took part, wherever it was played, and never back to the site it was
played at. A site signs as in "Locations"; the times are epoch milliseconds.

| Route | Signed by | Purpose |
|---|---|---|
| `PUT /circle/state` `{version?, players, state?}` | any registered location | report the lower-case names of the local players, the version and a small state (at most 4 KB, for the admin's debugging); answers `{approved}`; this is the only circle route an unapproved site may use |
| `GET /circle/config` | an approved site | `{approved, refetch, circle_players: [{id, name, sites: [{id, name}]}], mappings: [{local_name, player_id}], site_mappings: [{location_id, location_name, local_name, player_id}], profiles: [{player_id, field, value, at}]}` (`profiles` are the fields of the profiles of the circle players this site maps, `field` is `color` or `voice:<pack>`, `value` is `null` once cleared and `at` the time the relay took the change in; `refetch` is a counter the admin raises to make this site fetch all its records again: a site that has seen another value than its own starts again at cursor 0 and skips what it has; `mappings` are those of this site, `site_mappings` those of every site: a site needs them to tell which of its players is a name in a record of another site) |
| `PUT /circle/profile` `{players: [{name, color?, voice?}]}` | an approved site | set fields of the profile of circle players: `name` is a lower-case local name that the admin mapped (an unmapped one is ignored), `color` is `#rrggbb` or `null`, `voice` maps a voice pack name to an entry `{variants: [1 to 8 texts of at most 100 characters]}` or `null`; at most 50 players; answers `{updated}`, the number of fields whose value changed. The latest change wins: a field keeps the time of the change that is stored, setting the same value again changes nothing |
| `PUT /circle/records/<match id>/<revision>` `{game_mode, deleted, participants, record}` | the site that played the match | store the record (a JSON object of at most 256 KB whose `match_id`, `revision`, `deleted` and `game_mode` equal the address and the body, see the match record in the app); `participants` is a list of `{name, origin?}`: a local player by name, a guest of another site with `origin` = the name of that site; the circle players are found through the mappings; 422 when none is in the circle |
| `GET /circle/records?since=<cursor>&limit=<n>` | an approved site | `{records: [{seq, match_id, revision, game_mode, deleted, size, hash, created_at, origin: {id, name}}], next}`: the records meant for this site after the cursor (at most 100) |
| `GET /circle/records/<match id>` | an approved site | the same with the `record`, 404 unless it is meant for this site |

A new revision replaces the record and gets a new place in the order, so a site that follows the cursor sees the change; the same
record again changes nothing, another content for the same revision and an older revision are 409, a match of another site is 403.
A deletion record (`deleted: true`) is stored like any other. Limits: 500 records per site and day, 20,000 records and 2 GB in all;
the routes answer 503 when the `RECORDS` bucket is missing or the variable `SHARING` is `off`. A location that signs off loses its
place in the circle; the records it sent stay.

## Admin

JSON routes under `/admin` for the admin page in Breakfast (there is no web page on the relay). The page runs in a browser on any
installation, so the routes allow any origin (`access-control-allow-origin: *`, `OPTIONS` answers 204); there are no cookies.
`POST /admin/login` `{password}` answers `{token, expires_at}` (the token lasts one hour); every other route takes it as
`Authorization: Bearer <token>`. The password is stored only as a salted hash in the Worker secret `ADMIN_PASSWORD_HASH`
(`sha256$<salt>$<hash>`, written by `npm run admin-password`), the token is signed with the secret `ADMIN_TOKEN_KEY`; 5 failed
login tries per 15 minutes per address (a successful login does not count). Without the secrets the routes answer 503.

| Route | Purpose |
|---|---|
| `GET /admin/sites` | every registered location with what it reported: `{id, name, registered_at, approved, approved_at, last_seen, version, refetch, players, state}` |
| `POST /admin/sites/<id>/approve` and `/remove` | put a site into the circle or take it out (its mappings and rules stay) |
| `POST /admin/sites/<id>/refetch` | raise the `refetch` counter of an approved site (409 when it is not approved): it fetches all the records meant for it again, after a rule or a mapping changed |
| `GET /admin/players`, `POST /admin/players` `{name}`, `DELETE /admin/players/<id>` | the circle players with their mappings and the sites of their rule; delete takes mappings and rules with it |
| `PUT /admin/mappings` `{location_id, local_name, player_id}` | map a player of a site to a circle player (`player_id: null` removes the mapping) |
| `PUT /admin/rules` `{player_id, location_ids}` | replace the sites that get the matches of a player |
| `GET /admin/voice`, `POST /admin/voice/channels` `{name}`, `PUT /admin/voice/channels/<id>` `{name}`, `DELETE /admin/voice/channels/<id>` | the voice chat channels (`{id, name, created_at, sites}`, `sites` are the ids of the sites that see the channel) and the approved sites; make a channel (at most 20, a name once, 409 otherwise); rename one; delete one with its ticks (everybody in it is sent out) |
| `PUT /admin/voice/channels/<id>/sites/<site id>` `{visible}` | tick or untick a site for a channel (the site must be approved); a site that is unticked is sent out of the channel at once |
| `GET /admin/sync` | per approved site: last seen, version, its state and how many records it sent; the totals |
| `GET /admin/records` | the newest records without their content: match, origin, mode, the circle players in it, size |
| `GET /admin/usage` | the usage of the free plan from the GraphQL Analytics API (`readUsage` in `src/usage.ts`): `{configured, generated_at, day, month, limits, workers, d1, d1_size, r2_operations, r2_storage}`; `workers` is today's requests, errors, subrequests and the CPU time quantiles `cpu_p50` and `cpu_p99` (as the API gives them, its unit is not documented), `d1` today's queries and rows read and written, `d1_size` the database size, `r2_operations` this month's operations by `class_a`, `class_b`, `free` and `other` with `by_action`, `r2_storage` bytes and objects of the bucket. Every part is `{data}` or `{error}`, so a figure the API refuses does not hide the others; `{configured: false, limits}` without the secrets `CF_ACCOUNT_ID` and `ANALYTICS_API_TOKEN` |
| `GET /admin/reports?days=<n>` | the usage reports of the last days (30 by default): counts by type, installations, versions, platforms and the newest events |

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
| relay | `error` | `code`, `message` | followed by the close (4400 bad frame, 4401 not allowed, 4403 taken out of a channel, 4409 replaced or full) |

At most 6 peers, frames up to 16 KB.

### Voice channels

A voice chat without a match: the admin makes channels and ticks which approved sites see which (`/admin/voice`, above). The
requests of a site are signed like the other circle routes and need an approved site.

- `GET /circle/voice`: `{channels: [{id, name}]}`, the channels this site is ticked for.
- `POST /circle/voice/<channel id>/ticket`: `{ticket, site, channel: {id, name}}` (404 for a channel the site does not see). A
  new ticket replaces the older one of that site; it lasts a day.
- `GET /voice/channel/<channel id>`: WebSocket to the signaling room of the channel (a Durable Object per channel), with the same
  frames as the room of a match. `join` takes the site name of the ticket and the ticket; the site must still be ticked for the
  channel. When the admin unticks a site, deletes the channel or takes the site out of the circle, the relay sends the sites that may
  not be there any more an `error` with the code 4403 and closes their connection (the others get `peer-left`). One place per site,
  6 peers.
- The voice page takes `channel` and `name` instead of `code` in its address after the `#`. `ice` is STUN (`stun.cloudflare.com`); with the Worker secrets `TURN_KEY_ID` and
`TURN_KEY_API_TOKEN` of a Cloudflare TURN key it also carries TURN servers with credentials that run out after a day.
