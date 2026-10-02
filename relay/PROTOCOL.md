# Relay protocol, version 1

How Breakfast installations ("sites") play one Elimination match over the relay.
Design decisions: `DESIGN.md`. Both sides are tested against the examples in
`protocol-tests/messages.json`.

## Transport

- `POST /api/matches` with `{"protocol_version": 1}` reserves a **join code** and answers
  `{"code": "K7M2QX", "expires_in_s": 600}`. The code has 6 characters from
  `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` and is valid 10 minutes, or until the match starts.
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
| `hello` | `protocol_version`, `mode` (`create` \| `join` \| `rejoin`), `site`, `password`; for `rejoin` also `token`, `last_seq` | `create` only on a reserved code and makes the sender the host; the password is set here |
| `lobby_set_players` | `players` (list of names) | the sender's local players, replaces its earlier list; names are unique across the lobby |
| `lobby_start` | `lives` (1 to 10), `order` (all lobby players once) | host only; at least 2 players, at most 12 players and 6 sites |
| `dart` | `seq`, `player`, `throws` | live darts of the turn in progress, informational, relayed as is |
| `turn` | `seq`, `player`, `throws`, `next_player`, `eliminated`, `winner` | the finished turn, authoritative |
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
| `welcome` | `code`, `site`, `token`, `host` (bool), `state` | answer to a valid `hello`; the `token` authenticates a later `rejoin` |
| `lobby` | `host`, `sites` (list of `{site, players, connected}`), `lives`, `order` | sent on every lobby change |
| `started` | `match_id`, `lives`, `order`, `owners` (player -> site) | the match begins; `current_player` is `order[0]` |
| `rematch` | | the host asked for a rematch; followed by a `lobby` whose `order` is that of a local rematch (the first eliminated starts, the winner is last), without sites that are gone |
| `dart` | as received, plus `site` | forwarded to the other sites |
| `turn` | as received, plus `site` | forwarded to the other sites, in `seq` order |
| `turn_ok` | `seq` | to the sender: its turn was accepted |
| `turn_rejected` | `seq`, `reason` | not the sender's player, not that player's turn, or a wrong `seq` |
| `rejected` | `for` (the frame type), `reason` | a lobby frame was refused (name taken, not the host, ...); the connection stays open |
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
