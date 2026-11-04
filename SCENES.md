# Scenes: technical reference

A **scene** makes something happen at a moment of a game: it plays a sound, makes a call of the voice pack, shows an effect on the
TV view, waits. A scene is a small flow chart, a **graph** of nodes and the edges between them, and it can be made in the editor
(Settings → Audio & Voice → Scenes) or through the REST API of Breakfast. This document describes both so that someone else can
create scenes without reading the code.

The tables of triggers, limits and standard scenes are generated from the code (`python tools/scenes_reference.py`, a test checks
that they are current). The scene examples further down are checked by a test too.

## Contents

1. [A first scene](#a-first-scene)
2. [The graph](#the-graph)
3. [How a flow runs](#how-a-flow-runs)
4. [Triggers and facts](#triggers-and-facts)
5. [Conditions](#conditions)
6. [Actions](#actions)
7. [Limits and cleaning](#limits-and-cleaning)
8. [REST API](#rest-api)
9. [Testing a scene](#testing-a-scene)
10. [Standard scenes](#standard-scenes)
11. [Examples](#examples)

## A first scene

A scene that plays a sound with a chance of 5 % at the start of a turn, 10 seconds later (the sound `o-curva.mp3` must be in
the sound library, Settings → Audio & Voice → Sounds):

```bash
curl -s -X POST http://localhost:8080/api/scenes -H 'Content-Type: application/json' -d '{
  "name": "Random sound",
  "enabled": true,
  "graph": {
    "nodes": [
      {"id": "t", "type": "trigger", "event": "x01.turn_start", "x": 40, "y": 40},
      {"id": "c", "type": "condition", "kind": "chance", "percent": 5, "x": 40, "y": 160},
      {"id": "w", "type": "action", "kind": "delay", "seconds": 10, "x": 40, "y": 280},
      {"id": "s", "type": "action", "kind": "sound", "files": [{"file": "o-curva.mp3", "weight": 1}],
       "volume": 1, "replace": false, "channel": "ambient", "x": 40, "y": 400}
    ],
    "edges": [
      {"from": "t", "to": "c"},
      {"from": "c", "to": "w"},
      {"from": "w", "to": "s"}
    ]
  }
}'
```

The answer is `{"ok": true, "id": 7}`. The scene is in the editor at once and runs from the next turn on. The chance node has two
outputs, yes and no; an edge without `branch` leaves it at **yes**, and nothing hangs at **no**, so the flow simply ends there.

## The graph

A scene is `{"name", "enabled", "graph"}`, and `graph` is `{"nodes": [...], "edges": [...]}`.

### Nodes

Every node has:

| Field | Meaning |
|---|---|
| `id` | A name that is unique in the scene: letters, digits, `_` and `-`, 1 to 24 characters. |
| `type` | `trigger`, `condition` or `action`. |
| `kind` | The kind of a condition or an action (see below). A trigger has an `event` instead. |
| `x`, `y` | The place in the editor, whole numbers from -5000 to 5000 (0 when left out). The flow does not depend on them; a flow that does not run from top to bottom is laid out again when the editor opens it. |

### Edges

An edge is `{"from": "<node id>", "to": "<node id>"}` and may carry more:

| Field | Meaning |
|---|---|
| `from` | The `id` of the node the flow leaves. |
| `to` | The `id` of the node it goes on at. |
| `branch` | `"no"` for the **no** output of a condition. Left out, the edge leaves at **yes** (and every other node type has one output). |
| `match` | On the edges that leave a `switch`: the `id` of the output, or `"else"` for "otherwise". A switch edge needs it, one without a known output is dropped. |
| `weight` | On the edges that leave a `pick`: how likely the edge is, 1 to 100 (1 when left out). |

Never connect something to a trigger: a trigger only starts a flow. A pair of nodes can be connected once, and a node cannot
be connected to itself.

## How a flow runs

When a moment of the game happens (a trigger event), every **enabled** scene with a trigger for that event starts at that trigger.
Then:

- The flow follows the edges. When an output has several edges, all of them are followed, one after the other.
- A **condition** answers yes or no; the flow goes on along the edges of that answer. A `pick` takes one edge by its weight, a
  `switch` takes one of its outputs.
- A node that cannot answer, because a fact is missing (a `compare` on a fact the trigger does not give), answers **no** (a
  `switch` takes `else`).
- A node that is reached on two ways runs once for each way. A flow never goes through a node that is already on its way (no
  endless loops).
- An **action** that cannot run (no file in the library, no audio output, no voice-pack sound for the call) is skipped, and the
  flow goes on behind it.
- A `delay` stops that part of the flow for its seconds and then goes on, on a timer of its own. The game and the other scenes
  do not wait for it. Steps behind it run after the moment is over; they cannot replace a call and they never take part in the
  voice rule below.
- The scenes of the user run in the order of the list in the editor (`POST /api/scenes/order`), then the standard scenes (see
  [Standard scenes](#standard-scenes)).

## Triggers and facts

A trigger is `{"type": "trigger", "event": "<id>"}`. The facts of the moment are what conditions and switches can look at, and
what the placeholders of a call or an overlay text fill in. Besides the facts of each trigger below there are two for all of
them: `player` (the name of the player the moment is about; the comparisons of a `player` condition and of a `switch` ignore case) and `fun` (1 when the fun mode of the caller
settings is on, else 0). A fact that is a yes or no is 1 or 0: compare it with `== 1` or `== 0`. These are `announce`,
`change`, `total`, `miss`, `fun`, `secret`, `first`, `freipass`, `preview`, `close` and `last`.

<!-- generated:events -->
### `x01.match_start`: Match starts (X01)

- `announce`: Player calls on

### `x01.leg_start`: Leg starts (X01)

- `announce`: Player calls on

### `x01.dart`: Dart thrown (X01)

- `number`: Number (25 is the bull)
- `multiplier`: Multiplier (0 miss, 1 single, 2 double, 3 triple)
- `points`: Points
- `dart`: Dart of the turn
- `miss`: Missed
- `remaining`: Remaining
- `turn_points`: Turn points so far
- `dart1_points`: Points of dart 1
- `dart2_points`: Points of dart 2

### `x01.turn_start`: Turn starts (X01)

- `remaining`: Remaining
- `checkout`: Checkout (1 call, 2 bogey number, 3 call limit reached)
- `change`: Player change calls on

### `x01.turn_scored`: Turn scored (X01)

- `score`: Turn score
- `remaining`: Remaining
- `total`: Turn total calls on

### `x01.bust`: Bust (X01)

No facts of its own besides `player` and `fun`.

### `x01.leg_won`: Leg won (X01)

- `score`: Finishing turn score
- `leg`: Leg
- `announce`: Player calls on

### `x01.match_won`: Match won (X01)

- `score`: Finishing turn score
- `announce`: Player calls on

### `elim.match_start`: Match starts (Elimination)

No facts of its own besides `player` and `fun`.

### `elim.dart_missed`: Missed dart (Elimination)

No facts of its own besides `player` and `fun`.

### `elim.turn_start`: Turn starts (Elimination)

- `target`: Target
- `lives`: Lives
- `freipass`: Free pass
- `next`: Score to pass

### `elim.turn_counted`: Score read late (Elimination)

- `score`: Turn score

### `elim.passed`: Turn passed (Elimination)

- `score`: Turn score
- `target`: Target
- `margin`: Over twice the target
- `preview`: Read after the 3rd dart

### `elim.life_lost`: Life lost (Elimination)

- `score`: Turn score
- `lives`: Lives left
- `close`: Close
- `preview`: Read after the 3rd dart
- `last`: Ends the match

### `elim.eliminated`: Player eliminated (Elimination)

- `score`: Turn score
- `close`: Close
- `preview`: Read after the 3rd dart
- `last`: Ends the match

### `elim.match_won`: Match won (Elimination)

- `score`: Turn score

### `achievement.earned`: Achievement earned (Achievements)

- `id`: Achievement
- `tier`: Tier (1 for an achievement without tiers)
- `difficulty`: Difficulty (1 easy to 5 extreme, 0 off the ladder)
- `secret`: Secret
- `first`: Earned for the first time
<!-- /generated:events -->

## Conditions

A condition is `{"type": "condition", "kind": "<kind>", ...}`. All kinds except `pick` and `switch` have two outputs: yes (an edge
without `branch`) and no (`"branch": "no"`).

| Kind | Fields | Answers yes when |
|---|---|---|
| `compare` | `field` (a fact, up to 24 characters, `score` when left out), `op` (`>=`, `>`, `==`, `<=`, `<`, `!=`; `>=` when left out), `value` (a number from -100000 to 100000, 0 when left out) | the fact is a number and `fact op value` holds. A fact that is missing or not a number never holds, also not with `!=`. |
| `chance` | `percent` (0 to 100, fractions allowed, 10 when left out) | a random draw is below the percent. It is drawn again every time the flow gets there. |
| `player` | `names` (a list of up to 20 names, or one text separated by commas) | the player of the moment is one of the names, in any case. An empty list means any player. |
| `once` | `scope` (`match` or `leg`, `match` when left out), `per_player` (true or false) | this is the first time the flow gets there in this match (or leg); after that no, until the next match (or leg). With `per_player` each player has his own first time. A test of a scene does not use it up. |
| `achievement` | `achievement` (the id of an achievement, up to 60 characters), `tier` (1 to 20, 1 when left out) | the player of the moment has earned that achievement before, from that tier on. What is earned in the very turn of the moment is not stored yet and does not count. The ids are in `achievements` of `GET /api/scenes`. |
| `combine` | `mode` (`all`, `any` or `none`; `all` when left out), `checks` (a list of up to 6 checks) | all, at least one or none of the checks hold. A check is a `compare`, `chance`, `player` or `achievement` written as `{"kind": "compare", "field": ..., "op": ..., "value": ...}` with the fields of that kind. No `once` and no `combine` inside a `combine`. The editor makes 2 to 6 checks. |
| `pick` | none | one of the edges that leave it is taken by chance, by the `weight` of the edge. It has no yes or no. |
| `switch` | `field` (a fact, `player` when left out), `mode` (`values` or `bands`), `outputs` | exactly one output is taken (see below). It has no yes or no. |

### switch

A switch reads one fact and takes one of its outputs, or `else`. Every edge that leaves it carries `match`, the `id` of an output
or `"else"`. An output with no edge does nothing.

- `mode` `values`: `outputs` is `[{"id": "o1", "values": ["anna", "ben"]}, ...]`. The first output that names the value of the fact
  wins (case does not matter, numbers count as text, a value sits on one output only, up to 20 values of 40 characters).
- `mode` `bands`: `outputs` is `[{"id": "o1", "limit": 30}, ...]`, kept in ascending order of `limit`. The first output with
  `value <= limit` wins, so a band starts where the one before it ends. A fact that is not a number takes `else`.
- The output ids follow the rule of the node ids; `else` is taken. A fact that is missing takes `else`.

## Actions

An action is `{"type": "action", "kind": "<kind>", ...}`.

| Kind | Fields | Does |
|---|---|---|
| `sound` | `files` (a list of `{"file": "x.mp3", "weight": 1}`), `volume` (0 to 1.2, 1 when left out), `replace` (true or false), `channel` (`voice` or `ambient`, `ambient` when left out) | plays one file of the sound library, picked by weight (a file of weight 2 is twice as likely as one of weight 1). A file that is not in the library is left out and the others share its weight. Up to 20 different files; a file named twice counts once with the weights added. |
| `call` | `key` (up to 160 characters), `channel` (`voice` or `ambient`, `voice` when left out) | plays a sound of the **voice pack** by its key, see below. |
| `overlay` | `animation` (`confetti`, `flash` or `banner`), `text` (up to 60 characters, `{player}` and `{score}` are filled in), `seconds` (1 to 15, 4 when left out) | shows an effect on the connected TV views. |
| `delay` | `seconds` (0 to 30, 1 when left out) | waits, then the flow goes on behind it. |

### The sound library and the voice pack

- The **sound library** holds the files your own sounds are played from (mp3 files in the folder `scenes/` of the sound
  directory). A `sound` step names a file of it. List the files with `GET /api/scenes/sounds`, upload them with
  `POST /api/scenes/sounds/upload`.
- The **voice pack** holds the sounds of the caller, by key (`life_lost`, `bull`, a number, ...). A `call` step plays a key of
  it; whether there is a sound for it depends on the voice pack that is set up. The keys the standard scenes use are in
  `call_keys` of `GET /api/scenes`.

### The key of a call

- `{player}` plays the name of the player (his name sound, or `unknown_player` when there is none), `{score}` the score of the
  turn and `{next}` the score that passes (Elimination), each as a spoken number.
- Inside a longer key any fact stands in braces: `require_{remaining}` is `require_40` when 40 is left. A fact that is missing
  makes that key fail.
- `a|b` tries `a` and, when there is no sound for it, `b`. `a+b` plays `a`, then `b`. `|` binds weaker than `+`.
- A key that starts with `ambient_` plays on the ambient channel by itself, at the ambient volume of the caller settings (0 switches
  these calls off).

### Channels, the voice rule and `replace`

- The **voice** channel is a queue: a sound waits until the one before it has ended. The **ambient** channel plays beside it,
  never waits and never interrupts the voice. A sound that must not disturb anything belongs on ambient.
- **Voice rule:** of the scenes of the user only the first one in the list that plays something on the voice channel at a moment
  speaks. The voice steps of the scenes after it are skipped; ambient sounds, overlays and everything behind a `delay` are
  never skipped. `POST /api/scenes/voice-check` tells which earlier scene can take the voice before a scene.
- `replace` on a `sound` that played keeps the **standard call** of that moment (the call the game makes by itself) from
  playing. For the trigger `achievement.earned` it keeps the assigned sound of the achievement out.

## Limits and cleaning

<!-- generated:limits -->
| Limit | Value |
|---|---|
| Nodes in a scene | 60 |
| Edges in a scene | 240 |
| Characters of a scene name | 80 |
| Characters of an overlay text | 60 |
| Seconds of a `delay` | 30 |
| Seconds of an `overlay` | 15 |
| Files in one `sound` step | 20 |
| Highest `weight` of a file or an edge | 100 |
| Highest `volume` of a `sound` (1 is the level of the library) | 1.2 |
| Outputs of a `switch` besides `else` | 18 |
| Values on one output of a `switch` | 20 |
| Checks in a `combine` | 6 |
<!-- /generated:limits -->

When a scene is saved the server **cleans** the graph and answers with what is left, without saying what it dropped. It keeps only
the fields a node knows, puts values that are out of range at the nearest limit or at the default, and drops a node with an
unknown `kind`, a trigger with an unknown `event`, a node with an invalid or doubled `id`, an edge to a node that does not exist
and a `switch` edge without a known `match`. Check what was stored with `GET /api/scenes`.

## REST API

All routes are on the web port of Breakfast (`[web] port` in `config.toml`, 8080 in the example config; the examples use `http://localhost:8080`).

- **Authentication:** there is none. The routes are meant for a trusted network.
- **Errors:** the scene routes answer `{"error": "<text>"}` with the HTTP status 200, so look at the body, not at the status.
- **Machine-readable description:** `/openapi.json` lists every route of the app, and `/docs` is the interactive Swagger UI, with the routes in groups; the scene
  routes are the group *Scenes* (it loads its scripts from a CDN, so the browser needs internet access). The body of a scene is described there as a plain
  `graph` object; this document defines what it holds.

### Scenes

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/scenes` | Everything the editor needs: `scenes`, `events` (id → label, game, facts), `operators`, `animations`, `call_keys`, `achievements` (id, name, tiers) and `sounds` (the library: name, size, scenes that play it); `available` is false without a scene engine. |
| `POST` | `/api/scenes` | Make a scene. Body: `{"name", "enabled", "graph", "shared"}` (`shared` is optional: true shares the scene with the circle of friends). Answers `{"ok": true, "id": <number>}`. |
| `PUT` | `/api/scenes/{ref}` | Replace a scene with the same body. `ref` is the number of a scene or the id of a standard scene. Without `shared` the sharing stays as it is. |
| `DELETE` | `/api/scenes/{ref}` | Delete a scene. For a standard scene this takes your edited copy away, the original works again. |
| `POST` | `/api/scenes/order` | Body `{"ids": [3, 1, 2]}`: put these scenes of the user in this order (the others keep theirs). The order decides who gets the voice rule above. |
| `POST` | `/api/scenes/{ref}/copy` | Make a scene of your own from this one: the name plus " (copy)", switched off, not shared. Answers `{"ok": true, "id": <number>}`. |
| `POST` | `/api/scenes/{ref}/test` | Run the scene, see [Testing a scene](#testing-a-scene). |
| `POST` | `/api/scenes/voice-check` | Body `{"id": <number or null>, "graph": {...}}`: the earlier scenes of the user that can take the voice before this graph, `{"overridden_by": [{"scene", "name", "event", "level"}]}`; `level` is `warning` when that scene always takes it and `note` when it can. |
| `GET` | `/api/scenes/audio-clients` | `{"count": n}`: the audio pages that are connected (the `/audio` page and the TV views with sound). Sounds only play on those. |

A scene in the answer of `GET /api/scenes` is `{"id", "name", "enabled", "graph", "default", "customized", "shared", "share_id",
"source", ...}`. `id` is a number, or a text for a standard scene. `shared` says it is shared with the circle. A scene with a
`source` is a read-only copy of a scene another installation shares: `PUT` changes only its `enabled`, and `copy` makes your own
from it.

### Sounds

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/scenes/sounds` | The sound library alone, without scenes: `{"sounds": [{"name": "boom.mp3", "size": 31420, "used_by": ["Cheer"]}]}`, sorted by name; `used_by` are the names of the scenes that play the file. These are the names a `sound` step can use. The same list is `sounds` in `GET /api/scenes`. |
| `POST` | `/api/scenes/sounds/upload?name=x.mp3` | Add an mp3 to the library. The request body is the file (up to 3 MB); the name is letters, digits and `. _ + -` and ends in `.mp3`. |
| `POST` | `/api/scenes/sounds/{name}/rename` | Body `{"name": "new.mp3"}`: rename a file; the sound steps of the scenes that play it follow. |
| `DELETE` | `/api/scenes/sounds/{name}` | Delete a file; a scene that plays it plays nothing for that step. |
| `POST` | `/api/scenes/sounds/edit?name=x.mp3&start=&end=&fade_in=&fade_out=` | Cut, fade and level a sound with ffmpeg and store it in the library. The source is the request body (any audio file, up to 20 MB) or `source`, a file of the library. More parameters (`trim`, `curve_in`, `curve_out`, `low_cut`, `noise`, `compress`, `overwrite`) are in `/openapi.json`. |
| `POST` | `/api/scenes/sounds/preview?...` | The same edit to listen to: the first 15 seconds as `audio/mpeg`, nothing is stored. |
| `POST` | `/api/scenes/sounds/speech` | Body `{"text", "pack", "rate", "pitch", "name", "overwrite"}`: speak a text (up to 200 characters) with a voice of a voice pack plan and store it as `name`. Needs the internet. |
| `POST` | `/api/scenes/sounds/speech/preview` | The same without `name`: the spoken text as `audio/mpeg`, nothing is stored. |

## Testing a scene

`POST /api/scenes/{ref}/test` runs the scene once for each of its triggers with sample values (a score of 180, 100 left, the dart
the first of the turn, ...), whether the scene is on or not. It is heard and seen on the connected views, and it really waits for
a `delay`. The answer is `{"ok": true, "trace": [...]}`, one entry for each step the flow reached:

| Field | Meaning |
|---|---|
| `node` | The id of the node. |
| `result` | `done` (an action ran), `skipped` (it could not run), `pass` (a condition answered yes or a switch took an output with an edge), `stop` (a condition answered no, or a switch took an output with no edge), `wait` (a `delay`), `pick` (a `pick`). |
| `output` | For a condition: `yes` or `no`; for a `switch`: the output taken. |
| `chosen` | For a `pick`: the id of the node it took. |
| `why` | Why a step was skipped or a switch took `else`: `no_audio`, `no_file`, `file_missing`, `no_key`, `no_sound`, `ambient_muted`, `no_display`, `voice_slot_taken`, `missing_fact:<names>`, `not_a_number` or `no_output`. |
| `file`, `missing` | For a `sound`: the file it played and the files it left out. |

A trigger is not in the trace. The editor draws the trace on the canvas after the Test button: what ran is green, where the
flow stopped is red.

## Standard scenes

The calls a game makes by itself (the call of the player at a turn, the score read after a turn, ...) are **standard scenes**: one
for each moment, listed under the title of their game in the editor. They exist always, they are not created through the API,
and they run after the scenes of the user. `PUT` on one stores your edited copy under the same id (its name stays), `DELETE`
takes the copy away so the original works again, and a standard scene cannot be shared.

<!-- generated:standard -->
| Id (the `ref` of the routes) | Moment | Game |
|---|---|---|
| `x01-match-start` | Match starts | X01 |
| `x01-leg-start` | Leg starts | X01 |
| `x01-turn-start` | Turn starts | X01 |
| `x01-turn-scored` | Turn scored | X01 |
| `x01-bust` | Bust | X01 |
| `x01-leg-won` | Leg won | X01 |
| `x01-match-won` | Match won | X01 |
| `elimination-match-start` | Match starts | Elimination |
| `elimination-missed-dart` | Missed dart | Elimination |
| `elimination-turn-passed` | Turn passed | Elimination |
| `elimination-turn-counted` | Score read late | Elimination |
| `elimination-life-lost` | Life lost | Elimination |
| `elimination-eliminated` | Player eliminated | Elimination |
| `elimination-match-won` | Match won | Elimination |
| `elimination-turn-start` | Turn starts | Elimination |
<!-- /generated:standard -->

## Examples

Each example is the `graph` of a scene (put it into the body of `POST /api/scenes` with a `name` and `"enabled": true`).

### A random sound at the start of a turn

The scene of [A first scene](#a-first-scene): 5 % per turn, after 10 seconds, on the ambient channel.

```json scene
{"nodes": [
  {"id": "t", "type": "trigger", "event": "x01.turn_start", "x": 40, "y": 40},
  {"id": "c", "type": "condition", "kind": "chance", "percent": 5, "x": 40, "y": 160},
  {"id": "w", "type": "action", "kind": "delay", "seconds": 10, "x": 40, "y": 280},
  {"id": "s", "type": "action", "kind": "sound", "files": [{"file": "o-curva.mp3", "weight": 1}],
   "volume": 1, "replace": false, "channel": "ambient", "x": 40, "y": 400}],
 "edges": [{"from": "t", "to": "c"}, {"from": "c", "to": "w"}, {"from": "w", "to": "s"}]}
```

### A 180 built up in three steps

The first dart of 60 plays one sound, a second dart that brings the turn to 120 the next, and a turn of 180 the third. The two
checks of the first two steps are a `combine` that needs both. Because `x01.dart` knows the points of the turn so far, the
second step does not play after a first dart that missed.

```json scene
{"nodes": [
  {"id": "t1", "type": "trigger", "event": "x01.dart", "x": 40, "y": 40},
  {"id": "k1", "type": "condition", "kind": "combine", "mode": "all", "checks": [
    {"kind": "compare", "field": "dart", "op": "==", "value": 1},
    {"kind": "compare", "field": "points", "op": "==", "value": 60}], "x": 40, "y": 160},
  {"id": "s1", "type": "action", "kind": "sound", "files": [{"file": "kame.mp3", "weight": 1}], "x": 40, "y": 280},
  {"id": "k2", "type": "condition", "kind": "combine", "mode": "all", "checks": [
    {"kind": "compare", "field": "dart", "op": "==", "value": 2},
    {"kind": "compare", "field": "turn_points", "op": "==", "value": 120}], "x": 320, "y": 160},
  {"id": "s2", "type": "action", "kind": "sound", "files": [{"file": "hame.mp3", "weight": 1}], "x": 320, "y": 280},
  {"id": "t2", "type": "trigger", "event": "x01.turn_scored", "x": 600, "y": 40},
  {"id": "c3", "type": "condition", "kind": "compare", "field": "score", "op": "==", "value": 180, "x": 600, "y": 160},
  {"id": "s3", "type": "action", "kind": "sound", "files": [{"file": "haaa.mp3", "weight": 1}], "x": 600, "y": 280}],
 "edges": [
  {"from": "t1", "to": "k1"}, {"from": "k1", "to": "s1"},
  {"from": "t1", "to": "k2"}, {"from": "k2", "to": "s2"},
  {"from": "t2", "to": "c3"}, {"from": "c3", "to": "s3"}]}
```

### A sound for the size of a turn

A `switch` on the score of a turn in bands: up to 30, up to 100, and everything above (`else`).

```json scene
{"nodes": [
  {"id": "t", "type": "trigger", "event": "x01.turn_scored", "x": 40, "y": 40},
  {"id": "sw", "type": "condition", "kind": "switch", "field": "score", "mode": "bands", "outputs": [
    {"id": "low", "limit": 30}, {"id": "mid", "limit": 100}], "x": 40, "y": 160},
  {"id": "a", "type": "action", "kind": "sound", "files": [{"file": "weak.mp3", "weight": 1}], "x": 40, "y": 300},
  {"id": "b", "type": "action", "kind": "sound", "files": [{"file": "ok.mp3", "weight": 1}], "x": 260, "y": 300},
  {"id": "c", "type": "action", "kind": "overlay", "animation": "confetti", "text": "{player}: {score}", "seconds": 4, "x": 480, "y": 300}],
 "edges": [
  {"from": "t", "to": "sw"},
  {"from": "sw", "to": "a", "match": "low"}, {"from": "sw", "to": "b", "match": "mid"}, {"from": "sw", "to": "c", "match": "else"}]}
```

### A call, only in the fun mode

At a bust: in the fun mode a call of the voice pack and a sound on top of the standard call, otherwise nothing.

```json scene
{"nodes": [
  {"id": "t", "type": "trigger", "event": "x01.bust", "x": 40, "y": 40},
  {"id": "f", "type": "condition", "kind": "compare", "field": "fun", "op": "==", "value": 1, "x": 40, "y": 160},
  {"id": "c", "type": "action", "kind": "call", "key": "ambient_noscore", "channel": "ambient", "x": 40, "y": 280},
  {"id": "s", "type": "action", "kind": "sound", "files": [{"file": "oops.mp3", "weight": 3}, {"file": "ouch.mp3", "weight": 1}],
   "channel": "ambient", "x": 260, "y": 280}],
 "edges": [{"from": "t", "to": "f"}, {"from": "f", "to": "c"}, {"from": "f", "to": "s"}]}
```
