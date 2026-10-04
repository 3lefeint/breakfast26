# Breakfast

*Works with [Autodarts](https://autodarts.io).*

Self-hosted darts companion for Autodarts: live scoreboard, elimination game
mode, board control, built-in voice caller with custom voice-pack creation,
lifetime statistics, and one-click self-update — with optional MQTT output
for LED/display control.

---

## Architecture

```
Autodarts cloud
      │  email/password auth
      │  cloud WebSocket
      │
    Breakfast   ← local board WebSocket
      │
      ├────────────┬───────────────┐
      │            │               │
   Web UI        MQTT         (recorder)
  (browser)   (broker)
      │            │
   Tablet /   ESPHome /
   Mobile     LED strips
```

Connects straight to the Autodarts cloud — no darts-caller required.

---

## Features

- Real-time scoreboard in the browser (score per dart, remaining, all players)
- **Voice caller** (X01): built-in match calling — per-dart field calls, turn
  totals, "you require" checkout calls, bust, leg/match won. Playback happens
  in a browser tab (`/audio`), so Breakfast itself needs no OS audio and
  runs identically native or in Docker, on Linux or Windows. No external
  darts-caller dependency for calling.
- **Voice packs**: use your own sound files, optionally switch to a
  downloadable voice profile (`voicepack` subcommand) with your own files as
  per-key fallback
- **Voice Pack editor** (Settings tab): add, test-listen (unsaved preview),
  save, browse, and delete individual voice-pack entries — any key (a
  player name, a phrase, or a number) with one or more randomized-pronunciation
  variants — straight from the browser, no manual TOML editing or CLI
  generator run needed for a single change
- **TV / kiosk mode** (`/tv`): full-screen live view for wall-mounted displays and tablets, no navigation — X01 scoreboard (remaining score, checkout hint, dart boxes) or the live Elimination game, whichever is active
- **Live dart positions** (`/tv`): a dartboard under the scores shows where each dart of the current turn landed, as numbered markers, in X01 and Elimination, and on the idle screen (dart boxes above the board) while no match is running. Needs the local Autodarts board connection (`board_ws_url`); without it the board stays hidden
- **Checkout suggestions**: standard X01 checkout path shown below the remaining score, with a distinct "Bogey — no checkout" badge for the handful of remaining scores that are in checkout range but have no valid 3-dart finish (169, 168, 166, 165, 163, 162, 159)
- **Live session stats**: 3-dart average, 180s, checkout % shown next to each player during a match
- **Lifetime statistics tab**: per-player averages, 180 / 140+ / 100+ counts, checkout rate across all sessions; per-player reset with double confirmation
- **Leaderboards**: top-10 by average, 180s, checkout % in the Stats tab
- **Leg tracking**: legs won per player recorded per match; shown live in the scoreboard and in match history
- **MQTT auto-reconnect**: reconnects with exponential backoff when the broker drops mid-session
- **Elimination** game mode with unlimited players, life management, turn correction
- **Target Battle**: one or more players throw at the same target number each round, and only a dart on it scores. A wheel (a needle turning around the dartboard) picks a random target at the start of every round, or you set a fixed order; scoring is single 1, double 2, triple 3, or only one of them as a training profile, with an optional tiebreak. The TV shows the darts of the whole round on the board in the color of each player (set in the profile)
  and undo (repeatable, walks back any completed turn — including reopening an
  already-finished match if the winning turn itself gets undone), optional
  random turn order for a new game, and a win-count crown for the current leader
- **Board control** (direct mode): Undo throw, Next Player, Next Leg, Reset Board, Correct Throw — all on the `/tv` live view
- **Freeplay**: casual throws outside a match still get a miss comment per dart and
  the turn total announced (with `[audio]` configured), plus live MQTT/LED output
- MQTT output for ESPHome / LED strips (works without Home Assistant); fully
  optional — Elimination, the scoreboard, and the voice caller all work with it off
- **Self-update** (Docker deployments): check for a newer release and install it
  with one confirmation click from Settings — pulls, rebuilds, and restarts
  automatically, with an automatic rollback if the new build doesn't come up
  healthy
- Session recording and replay — develop without throwing darts
- Config file — no long CLI commands needed in production
- Colored, leveled log output (DEBUG/INFO/WARNING/ERROR/CRITICAL), opt out via `NO_COLOR`
- **Settings tab**: edit all `config.toml` settings from the browser without touching the file, organized into General / MQTT / Autodarts Source / Voice & Caller categories (the voice-pack profile is picked from a dropdown of the installed profiles)
- **About page**: the ℹ️ button in the footer opens the running version, its release time (UTC), a joke of the day (icanhazdadjoke.com, cached per day, a built-in joke if the request fails; `[web] joke_of_the_day = false` turns it off and makes no outbound call) and the changelog
- **Online Elimination**: play one Elimination match with Breakfast installations elsewhere. One site hosts and gets a join code, the others join with the code and a shared match password, each adds its own players, the host sets lives and order, and after a match the host can start a rematch without a new lobby (the first eliminated starts, the winner is last; players can change). The darts of every player appear live on every TV, the calls play locally, and every site stores the whole match in its own `stats.db`. Needs a relay (`relay/`, a Cloudflare Worker) and `[online] relay_url`; without it online play stays off
- **X01 win tracking**: alongside Elimination wins, the Players tab shows each player's X01 match win count too
- **Per-player stats** (Stats tab, X01 and Elimination chips): activity and records, and for X01 a score histogram, board heatmap (by field, or where every dart landed), bust rate, win/loss, average and checkout % per match, doubles and the Top 10 legs (by starting score) and checkouts
- **Achievements and player profile**: players earn achievements for what they do in matches (34 so far, from Bullseye, Shanghai and 180! to the checkout achievements, a perfect nine-dart leg, Last at the Table and the Target Battle scores, some with tiers and six secret ones), and the profile, opened from the Players tab, shows them as badges with the progress to the next tier and how many players have each. An unlock banner on `/tv` announces every achievement when the match is over, one after the other, and plays a sound from `<audio dir>/achievements/` (`achievement_<id>.mp3`, else `achievement.mp3`; see `VOICE_PACKS.md`). Only matches played after the feature came count, and an achievement is taken back when an undo or correction reopens the match. Hidden players do not earn any achievements.
- **Modern Web UI**: Svelte 5 + Vite frontend (built to static assets, no client-side framework runtime overhead), dark-mode with swappable accent colors

---

## Requirements

- Python 3.11+
- Node.js 22+ and npm — only needed to build the Web UI from source (bare-metal
  setup below); the Docker image builds it automatically in a separate stage,
  Node itself never ends up in the final image or running process
- Autodarts account + board
- MQTT broker, e.g. Mosquitto (optional — Breakfast runs without it)

---

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url> breakfast26
cd breakfast26
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Build the Web UI

The Web UI (`/`, `/tv`, `/audio`) is a Svelte + Vite frontend that must be
built to static files before `main.py` can serve it — `frontend/dist/` (the
build output) is gitignored, so this step is required once after cloning
(and again after pulling frontend changes):

```bash
cd frontend
npm ci
npm run build
cd ..
```

This produces `breakfast/web/dist/`, which `server.py` serves directly. The
Docker image (see **Production setup (Docker)** below) runs this same build
in a separate stage automatically — skip this step entirely if you only
plan to run Breakfast via `docker compose`.

### 3. Create config file

```bash
cp config.toml.example config.toml
```

Edit `config.toml` with your credentials and settings.
For this bare-metal setup, the file lives in the **project root** next to
`main.py` — `config.py` resolves the default `config.toml` path relative to
the current working directory, and `main.py` is meant to be run from the
project root (as above). This is *not* where Docker or systemd look — see
**Production setup (Docker)** (`data/config.toml`) and **Production setup
(Linux / systemd)** (`WorkingDirectory`) further down for those paths.
`config.toml` is listed in `.gitignore` so credentials are never committed.

---

## Configuration (`config.toml`)

```toml
mode = "direct"

[direct]
email    = "user@example.com"
password = "your-password"
board_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Fully optional — Elimination, the scoreboard, and the voice caller all work
# with no [mqtt] section at all. This only feeds Home Assistant sensors and
# ESPHome/LED displays over MQTT.
[mqtt]
enabled  = true    # explicit on/off switch, independent of leaving host blank
host     = "192.168.1.10"
port     = 1883
username = "mqtt"
password = "mqtt"

[web]
port = 8080
# joke_of_the_day = true   # About page fetches a joke from icanhazdadjoke.com; false = no outbound call

# [online]
# relay_url = "wss://breakfast-relay.example.workers.dev"   # relay for online Elimination, see relay/README.md
# site_name = "Home"                                       # how this installation shows up to the others

# [stats]
# db = "stats.db"       # SQLite file for per-turn data; "none" to disable
# timezone = "UTC"      # IANA name such as "Europe/Zurich"; local days and hours for achievements

[logging]
level = "INFO"          # DEBUG, INFO, WARNING, ERROR
events = false          # true: log each game event (dart-thrown etc.) at INFO level
# file = "/var/log/breakfast.log"   # optional file output in addition to stderr

# [audio]
# dir = "/path/to/sounds"   # enables the voice caller + elimination audio
# profile = "en-US-Joey-Male"  # optional voice pack under <dir>/profiles/

# [caller]                # all optional, defaults shown in config.toml.example
# enabled = true
# per_dart = true
# checkout_limit = 1

# [dev]
# enabled = true   # exposes a Settings "Dev" tab to simulate a full X01/Elimination match — see "Dev mode" below
```

Terminal / `docker logs` output is colored by level (DEBUG blue, INFO green, WARNING
yellow, ERROR orange, CRITICAL red) — set the `NO_COLOR` environment variable to any
value to opt out. Applies to the main app and the `updater` service (below) alike; the
updater's own log level is set separately via its `LOG_LEVEL` env var (default `INFO`),
since it's a distinct process from `main.py`.

All settings can be overridden on the command line — CLI args always win over the config file.

Useful CLI overrides:

```bash
python main.py --log-level DEBUG          # verbose output for development
python main.py --log-events               # log every incoming event at INFO
python main.py --stats-db none            # disable statistics this run
python main.py --web-port 9090            # override web port
python main.py --config /other/path.toml  # use a different config file
```

---

## Running (development)

With `config.toml` in the project root, just run:

```bash
# Activate the virtual environment first (once per terminal session)
source .venv/bin/activate

# Start Breakfast — reads everything from config.toml
python main.py
```

All options come from the config file.

To stop Breakfast: **Ctrl-C**.

### Without a config file (pure CLI)

```bash
python main.py direct \
  --email user@example.com \
  --password secret \
  --board-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  --mqtt-host 192.168.1.10 \
  --web-port 8080
```

### Frontend development (Web UI changes only)

Editing `frontend/`? Skip rebuilding on every change — run the Vite dev
server instead, which hot-reloads and proxies `/api` + `/ws` to a real
`python main.py` instance already running on port 8080:

```bash
cd frontend
npm run dev   # http://localhost:5173, proxies to localhost:8080
```

`npm run build` (from the Setup step above) is still what produces the
`breakfast/web/dist` that `main.py` actually serves in normal use — the dev
server is only for iterating on the frontend itself.

### Running tests

The Python test suite (`tests/`, pytest) covers the backend — game state,
stats DB, elimination, caller/voice logic, etc. Not part of the base
`requirements.txt`:

```bash
pip install -r requirements-dev.txt
pytest
```

There's no frontend test suite — Svelte changes are verified by running
the app (`npm run dev` above) against real or replayed data.

---

## Web UI

Open `http://<host>:8080` in a browser — a card-based hub landing page
(**Games**, **Target Battle**, **TV**, **Board**, **Players**, **Stats**, **Settings**), each a
deep-linkable view (`/#elimination`, `/#target-battle`, `/#players`, `/#stats`, `/#settings`).
The live scoreboard itself (X01, Elimination and Target Battle) lives on the separate
`/tv` page, not on the hub — see below.

| View | What it shows |
|------|--------------|
| **Home** (`/`) | Hub landing page: Games (Elimination setup/rematch), Target Battle (setup, result and rematch), TV, Board (jump-off link to the local Autodarts board manager, if configured), Players, Stats, Settings |
| **TV** (`/tv`) | Full live view: X01 scoreboard with dart boxes/checkout suggestion/board+match controls, the live Elimination game (lives, turn order, tap-to-correct darts, clickable dartboard) or the live Target Battle (a large board with the wheel and the darts of the round, the players with their darts, a table of every round, tap-to-correct darts) — whichever is active; idle screen otherwise. Both show a read-only dartboard with the darts of the current turn; with no match running and the board connected, the idle screen shows the dart boxes and the dartboard instead of "Waiting for match…" |
| **Players** | Known players list — name (opens the player's profile), Elimination win count, X01 win count, missing-audio indicator, hide/unhide |
| **Profile** (`#profile/<name>`) | A color picker for the player (games use it for the player's darts, none set means a random one per game), and the player's achievements as badges, in sections by game mode, each split into earned and still to earn (with the progress to the next tier); secret ones that are not earned yet come last as a question mark |
| **Stats** | Three chips at the top pick the game mode: **X01**, **Elimination** and **Target Battle**. **X01** shows totals and records, the players compared as bars (average, turns of 100 or more, checkout %), collapsible recent matches (expandable per-match detail) and a per-player section (activity and performance tiles, a histogram of the turn scores, a heatmap of the dartboard (how often each field was hit, misses per sector in a ring, or switched to where every dart landed, with a density overlay from 30 darts on), the bust rate by remaining score, win/loss as a donut, the average and the checkout % per match as lines, doubles, Top 10 Legs/Checkouts). **Elimination** shows overview tiles with the records (highest score, and the highest score that still lost a life; both from turns recorded with a score, also per player in the activity section), a placement bar per player compared with the wins expected by chance, the form of the last 15 games with win streaks, a head-to-head matrix of how often each player finished ahead of each other player, the game length by lives setting, collapsible recent matches and per-player activity with the positions of the player's darts on the board. **Target Battle** has a chip row for the scoring profile (standard, singles, doubles, triples; the numbers only count games of that profile) and shows overview tiles with the best game and the best turn, wins and placements against the expected wins, the form of the last 15 games, head to head, per player the points per round, the share of darts on the target, perfect turns and the best turn, how often each target number is hit, and recent matches with a table of every round. Wins, form and head to head come from games with at least two players, the throwing numbers also from games played alone |
| **Settings** | Edit all `config.toml` settings from the browser, organized into General / MQTT / Autodarts Source / Voice & Caller tabs (plus a Dev tab if `[dev] enabled = true`); `log_level` applies immediately, everything else is saved to disk and needs a restart. Also has an Updates panel (Docker deployments with the `updater` sidecar set up, see **Self-update** below), and a **Voice Pack** tab (see below) with its own independent save flow, separate from the `config.toml` form |

All connected clients update in real time via WebSocket.

### Voice caller (`/audio`)

With `[audio] dir` set, Breakfast announces X01 matches itself: match/leg
start, every dart by field name (*triple 20*, *double 16*), turn totals,
checkout calls (*you require ...*), bust, leg and match won. Sound plays in
the browser: open `http://<host>:8080/audio` on the device wired to the
room's speakers, click **Enable sound** once (browser autoplay policy), and
leave the tab open. Only tabs on `/audio` play sound — phones or tablets
showing the scoreboard stay silent. The tab keeps one audio stream open
between calls, so the volume mixer shows a permanent entry for the browser;
that is what keeps the start of a call from being cut off.

Sound files are plain `key.mp3` files (`matchon.mp3`, `t20.mp3`, `180.mp3`,
`you_require.mp3`, ...; `key+1.mp3` etc. for random variants). Checkout
numbers use a separate calm-toned `require_{n}.mp3` namespace — if those
recordings don't exist, the whole checkout call is skipped rather than
reusing the euphoric score file. Fine-tuning lives in the `[caller]` config section /
Settings tab; `--no-caller` disables calls for one run.

See **[VOICE_PACKS.md](VOICE_PACKS.md)** for the full call-key reference
(which sound plays for which trigger) and a walkthrough for recording your
own voice pack.

Optional downloadable voice profiles (third-party CDN, explicit opt-in):

```bash
python main.py voicepack --list                     # catalog
python main.py voicepack --install en-US-Joey-Male  # into <audio dir>/profiles/
# then: [audio] profile = "en-US-Joey-Male" — own files stay as fallback
```

Adding/tuning one key (a name, a phrase, or a number) doesn't need any of
this — Settings → **Voice Pack** tab: pick a group, type the key and one
or more variant texts, preview how each sounds (synthesized on the fly,
not saved), then save — writes the .mp3 file(s) and updates
`tools/voicepack_leni.toml` (comment-preserving), immediately usable
without a restart. The same tab also browses/plays/deletes what's already
generated; deleting a variant renumbers the remaining ones so none of
them go silently unreachable.

### TV / kiosk mode (`/tv`)

Open `http://<host>:8080/tv` on a wall-mounted display or tablet mounted
next to the board. Full-screen, no navigation — shows whichever game is
currently active:

- **X01**: large remaining score, checkout hint, dart boxes, compact
  all-player table, and the board/match control buttons below
- **Elimination**: lives per player, turn order, tap-to-correct darts, a
  win-count crown for whoever currently has the most Elimination wins, an
  Undo control (walks back the last completed turn — repeatable, and works
  even from the finished/winner screen to reopen a match), and the
  Stop/rematch/finished-match flow
- **Target Battle**: a large board with the wheel that picks a random target
  and every dart of the round in the color of its player (a ring around the
  marker tells apart players with the same or a very similar color), the
  round and its target, the players with their darts of the round and their
  total, a table of every round with its target and each player's points,
  tap-to-correct darts, Undo and Stop, and a result screen with the placements, the table of every round and a rematch

The header glows green/yellow/red in real time to reflect the board's
current status (ready / mid-takeout-or-calibration / stopped-or-disconnected),
sourced from both the cloud and local board connections so it works during
X01, Freeplay, and Elimination alike. It uses the same WebSocket connection
as the rest of the app and reconnects automatically.

A dartboard marks where each dart of the current turn landed: below the dart boxes in
Elimination, in its own column on the right (about 40% of the width) in X01. The positions come from the local board connection
(`board_ws_url`), so they show in every mode; the markers clear when the darts
are taken out. A dart corrected in Breakfast moves to the center of the new field.
Without that connection the board is hidden.

#### Board controls (direct mode only)

| Button | Description |
|--------|-------------|
| ↩ Undo | Remove last detected throw |
| ⏭ Next Player | Skip to next player |
| ▶▶ Next Leg | Start next leg/set |
| ⟳ Reset Board | Hard-reset the local board |
| ✓ Correct | Correct a misdetected throw (select dart 1/2/3, enter field e.g. `T20`); tapping a dart box on the scoreboard opens the same correction dialog as the 🎯 Board button |
| 🎯 Board | Same correction by clicking the spot on a dartboard (or picking a multiplier and number on the pad below it) |

This is the X01 board-level undo (removes the last *detected throw*).
Elimination has its own, separate Undo (removes the last *completed turn*,
see above) — the two aren't interchangeable since Elimination isn't scored
through the same board-control pipeline.

---

## Statistics

Per-turn data (score, remaining, bust/checkout flag, all three dart fields + remaining after each dart) is stored in a local SQLite file (`stats.db` by default). Elimination turns are stored with their dart count, score, the score they had to beat, whether it was a freipass and whether the turn passed, plus the player's lives going in (turns from before this was added only have the dart count). The position of every dart (`x`, `y` as Autodarts delivers it, unit = outer edge of the double ring) is stored in `dart_positions` for X01 and Elimination; darts from before this was added have none, and a dart set by a correction is flagged so it stays out of the heatmap. Stats are derived from this:

- **Session stats** (live, in-game): 3-dart average, 180 count, checkout % per player — updated after every turn with no database query
- **Lifetime stats** (Stats tab): same plus 140+, 100+ across all sessions
- **Leaderboards** (Stats tab): top-10 players by Best Average, Most 180s, Best CO%
- **Win counts** (Players tab): Elimination wins and X01 match wins, tracked separately per player. Solo (single-player/practice) X01 sessions don't count here — a session with no opponent isn't a competitive win — though their per-dart stats (average, 180s, checkout %) are still tracked normally
- **Checkout % tracking**: the remaining score is stored per individual dart, so the query can determine exactly which dart was thrown at a score a double can finish (even up to 40, or 50) and whether it was hit. Checkout % is hits over those darts, the way Autodarts counts it
- **Per-player stats** (Stats tab, per player): activity (darts/playtime/distance) and records for Elimination; for X01 also performance (best average/leg 501/checkout, total 180s), score histogram, board heatmap, bust rate by remaining score, win/loss, average and checkout % per match, doubles hit rate by number, Top 10 legs (fewest darts to win, per starting score, since a 301 leg and a 701 leg aren't comparable on darts alone) and Top 10 checkouts

Reset all stats for a player: Stats tab → ✕ button → two confirmation dialogs.

To disable stats collection: `--stats-db none` or `[stats] db = "none"` in config.

Every turn stores the time it was played (UTC). `[stats] timezone` (an IANA name such as `Europe/Zurich`, default `UTC`) sets the zone used for local days and hours, also under Settings → Statistics, which suggests the zone of your browser while none is set.

### Accessing the database directly

SQLite is built into Linux — no extra tool needed:

```bash
sqlite3 stats.db
```

Useful queries:

```sql
-- Recent matches (with data)
SELECT match_id, started_at, game_mode, players
FROM matches
WHERE EXISTS (SELECT 1 FROM turns WHERE turns.match_id = matches.match_id)
ORDER BY started_at DESC LIMIT 10;

-- All turns for a player
SELECT match_id, leg, turn, remaining_before, score, is_bust, is_checkout
FROM turns WHERE player = 'alice' ORDER BY match_id, leg, turn;

-- Remove empty/abandoned match entries
DELETE FROM matches
WHERE NOT EXISTS (SELECT 1 FROM turns WHERE turns.match_id = matches.match_id);

-- Schema overview
.schema
```

Exit with `.quit`. For a GUI, [DB Browser for SQLite](https://sqlitebrowser.org/) opens `stats.db` directly.

---

## Monitoring

The `/api/health` endpoint returns service uptime, MQTT and Autodarts WebSocket connection state, and whether stats collection is enabled:

```bash
curl http://localhost:8080/api/health
```

```json
{
  "version": "0.3.0",
  "release_date": "2026-08-18T10:00:00Z",
  "uptime_s": 3742,
  "mqtt": { "connected": true },
  "autodarts": {
    "connected": true,
    "match_active": false,
    "match_id": null,
    "match_started_at": null,
    "seconds_since_activity": null
  },
  "stats_db": { "enabled": true }
}
```

The Web UI footer shows two coloured dots (MQTT and Autodarts) that poll `/api/health` every 30 seconds — green = connected, red = disconnected — alongside the app version and an ℹ️ button that opens the About page.

Useful for a systemd `ExecStartPost` health check:

```bash
ExecStartPost=/bin/sh -c 'until curl -sf http://localhost:8080/api/health; do sleep 2; done'
```

---

## MQTT Topics

All topics are relative to `base_topic` (default: `autodarts`).

### Active player

| Topic | Value |
|-------|-------|
| `autodarts/current/player_name` | Name of the active player |
| `autodarts/current/remaining` | Remaining score |
| `autodarts/current/turn_score` | Points scored this turn |
| `autodarts/current/throw1_raw` | First dart field (e.g. `T20`) |
| `autodarts/current/throw2_raw` | Second dart field |
| `autodarts/current/throw3_raw` | Third dart field |
| `autodarts/current/last_is_miss` | `True` / `False` |
| `autodarts/current/is_bust` | `True` / `False` |

### Match / board

| Topic | Value |
|-------|-------|
| `autodarts/match/started` | `True` / `False` |
| `autodarts/match/game_mode` | e.g. `X01` |
| `autodarts/match/points_start` | e.g. `501` |
| `autodarts/board/status` | Board status string |

### Per player

| Topic | Value |
|-------|-------|
| `autodarts/players/<index>/remaining` | Remaining score |
| `autodarts/players/<index>/turn_score` | Current turn total |

### Elimination

| Topic | Value |
|-------|-------|
| `autodarts/elimination/active` | `true` / `false` |
| `autodarts/elimination/state` | Full Elimination game state as JSON (retained) |
| `autodarts/elimination/current_number` | Current player's seat number |
| `autodarts/elimination/current_lives` | Current player's remaining lives |
| `autodarts/elimination/lives_max` | Lives each player started with |
| `autodarts/elimination/target` | Score the current player must beat |
| `autodarts/elimination/freipass` | `true` / `false` — first-turn-of-life exemption |
| `autodarts/elimination/current/dart{1,2,3}`, `.../current/total` | The turn in progress |
| `autodarts/elimination/last_turn/dart{1,2,3}`, `.../last_turn/total` | The most recently finished turn |
| `autodarts/elimination/events/{event_type}` | Non-retained event (`turn_pass`, `life_lost`, `eliminated`, `game_won`) |
| `autodarts/elimination/command` | **Subscribed**, not published — JSON `{"action": ...}` (`start`, `stop`, `correct_turn`, `undo`, `add_player`, `remove_player`); every action also has a REST equivalent (see **REST API** below) |

### Target Battle

| Topic | Value |
|-------|-------|
| `autodarts/target_battle/active` | `true` / `false` |
| `autodarts/target_battle/state` | Full game state as JSON (retained): round, target, scoring, order, scores, winners |
| `autodarts/target_battle/round`, `.../rounds` | Current round and number of rounds |
| `autodarts/target_battle/target` | The target number of the current round |
| `autodarts/target_battle/current/dart{1,2,3}`, `.../current/total` | The turn in progress, in points |
| `autodarts/target_battle/last_turn/dart{1,2,3}`, `.../last_turn/total` | The most recently finished turn |
| `autodarts/target_battle/events/{event_type}` | Non-retained event (`turn_end`, `round_start`, `game_won`) |
| `autodarts/target_battle/command` | **Subscribed**, not published — JSON `{"action": ...}` (`start` with `players`, `rounds`, `targets`, `scoring`, `tiebreak`; `stop`, `correct_turn`, `undo`, `add_player`, `remove_player`) |

### Freeplay

Published whenever darts land with no match active — lets an ESPHome
display react to casual throws too, not just real matches.

| Topic | Value |
|-------|-------|
| `autodarts/freeplay/count` | Darts thrown so far this turn (0-3) |
| `autodarts/freeplay/throw{1,2,3}_name` | Field name of each dart (e.g. `T20`) |
| `autodarts/freeplay/total` | Turn total so far |
| `autodarts/events/freeplay_dart` | Non-retained event, fired per dart |

### Debug / full state

| Topic | Value |
|-------|-------|
| `autodarts/state/json` | Full game state as JSON |
| `autodarts/players/json` | All players as JSON |

---

## Session recording and replay

```bash
# Record a real session to a file
python main.py direct --record sessions/test.jsonl

# Replay it later (5× speed, no darts required)
python main.py replay --file sessions/test.jsonl --speed 5

# Replay with the Web UI and audio page attached — waits until a browser
# is connected on /audio before starting, so you don't miss the first calls
python main.py replay --file sessions/test.jsonl --speed 1 \
  --web-port 8080 --audio-dir sounds --wait-audio
```

Useful for developing MQTT automations or testing the Web UI and voice
calls without playing. With `--web-port`, the web server keeps running
after the replay ends (Ctrl-C to exit).

### Dev mode (simulate a match at runtime)

Session replay (above) is a separate process mode you start from the CLI.
Dev mode is the runtime equivalent for a normal `direct`-mode instance
that's already running (e.g. developing away from the physical board):
set `[dev] enabled = true` in `config.toml` and restart, then open
**Settings → Dev** and click **Simulate X01 leg** or **Simulate Elimination
match**. Watch it play out live on `/tv`, exactly as if it were a real
match — same WebSocket state pushes, same voice calls if `[audio]` is
configured. The X01 demo replays the bundled `data/sessions/test.jsonl`
fixture; the Elimination demo runs a short scripted match. Either one
refuses to start while a real match is already in progress. Off by
default — `[dev]` is not meant to be enabled on a shared/production
instance.

Don't want to edit `config.toml`/restart just to try it once? Tap the
version number in the Home footer 5 times in a row — same Android-style
gesture as unlocking Developer options — to reveal the Dev tab for the
current run only (`POST /api/dev/unlock`, in-memory, never written to
`config.toml`). Gone again on the next restart.

---

## Production setup (Docker)

Autodarts runs natively on the host (as it does today), only
Breakfast is containerized. `docker-compose.yml` has full setup
instructions in its header comments (the `board_ws_url` value `config.toml`
needs, and how to migrate an older per-file volume layout). All app
config/data (`config.toml`, `stats.db`, `sessions/`, `sounds/`) lives under
one bind-mounted `data/` directory. The image builds the Web UI itself (a
`node:22-slim` builder stage runs `npm run build`, then only its static
output is copied into the final Python image — Node never ends up in the
running container), so there's no separate frontend-build step here unlike
the bare-metal setups below. Quick start:

```bash
mkdir -p data/sessions data/sounds
cp config.toml.example data/config.toml   # fill in your values

docker compose up -d
```

Deliberately not using a third-party Autodarts container image (e.g.
community images like `michvllni/autodarts`) — running someone else's image
with camera/hardware device access is a supply-chain decision that needs an
explicit, separate call. If Autodarts gets containerized later, that means
writing and controlling our own image for it, not adopting one from an
outside maintainer.

### Self-update (optional)

`docker-compose.yml` also defines an `updater` sidecar service — a small
FastAPI app with the Docker socket and the repo checkout mounted, giving
Settings → Updates a "check for update" / "install" button that pulls the
newest `vX.Y.Z` tag from `origin/master`, rebuilds and restarts `breakfast`,
health-checks the result, and automatically rolls back if the new build
doesn't come up healthy. It never takes a shell string from the caller —
every git/docker command it runs is a fixed, hardcoded argv list — and it's
reachable only from the `breakfast` container over the compose-internal
network, never exposed to the host or the wider network.

Since this repo is private, the updater needs its own read-only SSH deploy
key to fetch from GitHub — one-time setup documented in `docker-compose.yml`'s
own header comments for the `updater` service (generate a dedicated
`ssh-keygen` keypair, register it via `gh repo deploy-key add`, the private
half goes to `data/updater_deploy_key`, gitignored). Skip this setup
entirely if self-update isn't wanted — the rest of Breakfast is unaffected
either way, only the Settings → Updates button won't do anything useful.

### Testing the image manually (build, run, cleanup)

Quick smoke test without a board, credentials, or MQTT — replays a recorded
session through the container:

```bash
# Build the image
docker build -t breakfast:test .

# Replay a recorded session (prints STATE blocks until the match ends)
docker run --rm -v "$(pwd)/sessions:/app/sessions:ro" breakfast:test \
  replay --file sessions/test.jsonl --speed 100

# Check argument validation (should error: --email is required)
docker run --rm breakfast:test direct

# Same replay through compose, with the documented volume mounts
docker compose run --rm breakfast replay --file sessions/test.jsonl --speed 100
```

Cleanup afterwards:

```bash
# Stop and remove the compose stack (containers + network)
docker compose down

# Remove the built images; the compose image name derives from the
# project directory name — list leftovers with: docker images
docker rmi breakfast:test
docker rmi $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -- '-breakfast$')
```

---

## Production setup (Linux / systemd)

Bare-metal like this needs the Web UI built once beforehand (see **Setup**
above, step 2: `cd frontend && npm ci && npm run build`) — there's no
separate build stage here like the Docker image has.

### 1. Copy the service file

```bash
sudo cp systemd/breakfast.service /etc/systemd/system/
```

### 2. Edit it

```bash
sudo nano /etc/systemd/system/breakfast.service
```

Replace `YOUR_USER` with the Linux user that should run the service, and update
`WorkingDirectory` / `ExecStart` to match the actual install path.
The service reads `config.toml` from `WorkingDirectory` automatically.

### 3. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now breakfast
```

### Useful commands

```bash
# View live log output
journalctl -u breakfast -f

# Restart after config change
sudo systemctl restart breakfast

# Stop
sudo systemctl stop breakfast
```

---

## REST API

The web server exposes a REST API alongside the WebSocket.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/state` | Full app state snapshot (same payload pushed over `/ws`) |
| `GET` | `/api/health` | Service health (uptime, MQTT/WS state, stats-db enabled) |
| `GET` | `/api/online` | Whether a relay is configured, this site's name, and the open online match (if any) |
| `POST` | `/api/online/create` | Host an online Elimination match: `{password, site?}` returns `{code}` |
| `POST` | `/api/online/join` | Join one: `{code, password, site?}` |
| `POST` | `/api/online/players` | The players of this site in the lobby: `{players}` |
| `POST` | `/api/online/start` | Host only: `{lives, order}` starts the match |
| `POST` | `/api/online/decision` | Host only, after a site did not come back: `{choice: "continue" \| "abort"}` |
| `POST` | `/api/online/rematch` | Host only, after a finished match: back to the lobby with the same sites and players |
| `POST` | `/api/online/leave` | Leave the online match |
| `GET` | `/api/changelog` | `CHANGELOG.md` as versions with their sections, for the About page; `[Unreleased]` only if it has entries |
| `GET` | `/api/joke` | Joke of the day (cached per day, built-in fallback); `{"enabled": false}` and no outbound call if `[web] joke_of_the_day = false` |
| `GET` | `/api/board-address` | Local Autodarts board manager URL, for the Home hub's Board card |
| `GET` | `/api/sound/{filename}` | Serves one voice-pack sound file (used by `/audio`) |

**Board / match control** (direct mode only):

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/control/undo` | Undo last detected throw |
| `POST` | `/api/control/next-player` | Skip to next player |
| `POST` | `/api/control/next-game` | Start next leg/set |
| `POST` | `/api/control/reset-board` | Hard-reset the local board |
| `POST` | `/api/control/force-clear-match` | Manually unblock a match Autodarts never reported as finished |
| `POST` | `/api/control/correct-throw` | Correct a misdetected throw (`dart`: 1/2/3, `field`: e.g. `T20`) |
| `POST` | `/api/control/restart` | Restart the whole process (relies on a supervisor — Docker/systemd — to bring it back up) |

**Elimination**:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/elimination/start` | Start a new game (`players`, `lives`) |
| `POST` | `/api/elimination/stop` | Stop the current game |
| `POST` | `/api/elimination/correct` | Correct the last turn's total |
| `POST` | `/api/elimination/correct-dart` | Correct one dart of the current turn |
| `POST` | `/api/elimination/undo` | Undo the most recently completed turn — repeatable; reopens the match if the undone turn had finished it |
| `POST` | `/api/target-battle/start` | Start a Target Battle (`players`, `rounds` default 10, `targets` one number per round or none for random, `scoring` `standard`/`singles`/`doubles`/`triples`, `tiebreak`); one player is enough |
| `POST` | `/api/target-battle/stop` | Stop the current game |
| `POST` | `/api/target-battle/correct` | Correct the last turn's points (`total`) |
| `POST` | `/api/target-battle/correct-dart` | Correct one dart of the current turn |
| `POST` | `/api/target-battle/undo` | Undo the most recently completed turn — repeatable; reopens the game if the undone turn had finished it |

**Stats**:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stats/players` | Lifetime stats for all players |
| `GET` | `/api/stats/player/{name}` | Lifetime stats for one player |
| `GET` | `/api/achievements/{name}` | Every achievement with the player's state (`tier`, `progress`, `next`, `earned_at`, `percent` = share of players with the shown tier); the name, description and `percent` of a secret one stay `null` until it is earned |
| `DELETE` | `/api/stats/player/{name}` | Delete all stats for a player (double-confirmed in the UI) |
| `GET` | `/api/stats/matches?mode=x01` | Recent matches (up to 20); `mode` (`x01`, `elimination` or `target_battle`) limits the list to one game mode, without it all are mixed |
| `GET` | `/api/stats/target-battle/overview?scoring=standard` | Target Battle statistics of one scoring profile (`standard`, `singles`, `doubles`, `triples`): `summary`, `records` (best game and turn), `players` (placements, expected wins, form, points per round, share of darts on the target, perfect turns, best turn, hits per target number) and `head_to_head` |
| `GET` | `/api/stats/x01/overview` | X01 overview: `summary` (matches, legs, darts, playtime) and `records` (highest turn, highest checkout, best leg for the most played starting score, best match average) |
| `GET` | `/api/stats/elimination/overview` | Elimination overview: `summary` (finished games, total/average/longest minutes) and `head_to_head` (per pair of players: shared games and how often each finished ahead), `game_lengths` (each finished game's lives setting, minutes, players and winner), `records` (the highest score and the highest score that still lost a life, from turns recorded with a score; the per-player dashboard carries the same as `elimination_records`), `players` (games, wins, win rate, placement spread, wins expected by chance, and `form`: the last 15 finished games with date, placement and opponents, plus the current and best win streak) |
| `GET` | `/api/stats/match/{match_id}` | Per-player stats for one match; for an Elimination match, each player's placement, lives left, turns, and average darts per turn instead |
| `GET` | `/api/stats/dashboard/{name}?points_start=501&mode=x01` | Advanced per-player dashboard (one bundled fetch); `points_start` picks the Top 10 Legs mode, defaults to 501 or the lowest played mode; `mode` (`x01` or `elimination`) limits the activity and win/loss numbers to one game mode, default is both |
| `GET` | `/api/leaderboard?metric=avg3&limit=10` | Top-N players by metric (`avg3`, `s180`, `co_pct`, `total_score`) |

**Players**:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/players` | Known (non-hidden) players list |
| `POST` | `/api/players` | Add a known player |
| `PATCH` | `/api/players/{name}/color` | Set a player's color (`{"color": "#rrggbb"}`) or clear it (`{"color": null}`); games use it to draw the player's darts |
| `PATCH` | `/api/players/{name}/hidden` | Hide/unhide a player (from the Players tab and leaderboards — reversible, unlike deleting stats) |
| `GET` | `/api/players/hidden` | Hidden players list |

**Config / voice pack**:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Current config (credentials masked) |
| `PATCH` | `/api/config` | Update config.toml; runtime fields (e.g. log level) apply immediately, the rest need a restart |
| `GET` | `/api/voice-packs` | Voice-pack profiles installed under `[audio] dir` (feeds the profile dropdown in Settings → Voice & Caller) |
| `POST` | `/api/voicepack/generate` | Regenerate the voice pack (`force`: true re-generates every key, false only fills in missing ones) |

**Voice Pack editor** (Settings → Voice Pack tab):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/voicepack/groups` | List the plan's `[[group]]` names (`name`, `is_range`) |
| `GET` | `/api/voicepack/entries?group=<name>` | Every key currently defined in that group, with each variant's text and whether its `.mp3` has actually been generated |
| `POST` | `/api/voicepack/preview` | Synthesize `text` on the fly with `group`'s voice/rate/pitch/volume — returns audio bytes directly, nothing is saved |
| `POST` | `/api/voicepack/entries` | Add/replace a key's variants (`group`, `key`, `variants`) — synthesizes every file and updates the plan |
| `DELETE` | `/api/voicepack/entries` | Remove one variant (`group`, `key`, `variant_index`) — renumbers the remaining files and updates the plan |
| `GET` | `/api/voicepack/file/{filename}` | Serves an already-generated variant file straight from the plan's own profile directory |

**Updates** (Docker deployments with the `updater` sidecar set up, see **Self-update** above):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/updates/check` | Fetch tags, compare against the running version — `{current, latest, update_available}` |
| `POST` | `/api/updates/apply` | Pull, rebuild, restart, health-check, automatic rollback on failure |
| `GET` | `/api/updates/status` | Last-known outcome (`done` / `rolled_back: <reason>` / `in_progress`) |

**Dev demo** (direct mode only, requires `[dev] enabled = true` or the version-tap unlock):

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/dev/demo/x01` | Simulate a full X01 leg at runtime (see "Dev mode" above) |
| `POST` | `/api/dev/demo/elimination` | Simulate a full Elimination match at runtime |
| `POST` | `/api/dev/unlock` | Runtime-only Dev-tab unlock (in-memory, resets on restart) — normally triggered by the version-tap gesture, not called directly |

---

## Project structure

```
breakfast26/
├── main.py                        # Entry point, argument parsing, mode dispatch
├── config.toml.example            # Config template — copy to config.toml
├── requirements.txt                # Runtime dependencies
├── requirements-dev.txt            # + pytest, for the test suite (see Running tests)
├── pytest.ini                      # pytest config
├── Dockerfile                      # Multi-stage: Node builder (frontend) + Python runtime
├── docker-compose.yml              # Compose services — see its header comments for full setup notes
├── .dockerignore
├── updater/                        # Self-update sidecar service (optional, see "Self-update" above)
│   ├── app.py                     # FastAPI app: check/apply/status, fixed git+docker command sequences only
│   └── Dockerfile                 # Debian + docker-ce-cli + docker-compose-plugin
├── relay/                          # Relay for online Elimination: Cloudflare Worker + Durable Object (own package, see relay/README.md)
├── systemd/
│   └── breakfast.service          # Systemd unit template
├── ESPHome/                       # ESPHome configs for LED strips
│   ├── esp.yaml                   # Main ESP32 config
│   ├── autodarts-led.yaml         # Autodarts-specific LED package
│   └── mqtt/                      # MQTT entity definitions
├── tools/
│   ├── generate_voicepack.py      # TTS voice-pack generator (CLI + Settings-tab regenerate)
│   └── voicepack_leni.toml        # Voice-pack plan: keys, phrases, number overrides, variants
├── tests/                         # pytest suite — one file per breakfast/ module, roughly
├── frontend/                      # Svelte 5 + Vite source for the Web UI (see Setup step 2)
│   ├── index.html                 # Home app entry point
│   ├── tv.html                    # TV app entry point
│   ├── audio.html                 # Audio page entry point
│   ├── vite.config.js             # Multi-page build config + dev-server API proxy
│   └── src/
│       ├── home/                  # Home app: hub, Elimination, Players, Stats, Settings
│       ├── tv/                    # TV app: X01 view, Elimination live/finished, dart-correct modal (clickable dartboard + number pad)
│       ├── audio/                 # Minimal audio-unlock page
│       └── lib/                   # Shared components, stores, API/router/theme helpers
└── breakfast/
    ├── config.py                  # Config file loader / arg merger
    ├── autodarts_client.py        # Autodarts auth + cloud WebSocket client
    ├── source_direct.py           # Direct mode entry point
    ├── source_replay.py           # Replay mode entry point
    ├── state.py                   # Game state machine
    ├── stats.py                   # SQLite stats DB + event-driven tracker
    ├── elimination.py             # Elimination game controller
    ├── turn_game.py               # What board games share: darts of a turn, corrections, undo, MQTT output
    ├── target_battle.py           # Target Battle game and controller
    ├── online.py                  # Online Elimination: this site's side of the relay protocol, drives the local game
    ├── dartboard.py               # Dartboard geometry and the center of every field
    ├── changelog.py               # CHANGELOG.md parser for the About page
    ├── joke.py                    # Joke of the day for the About page
    ├── caller.py                  # Voice caller: shared lifecycle calls + mode dispatch
    ├── caller_x01.py              # X01 call logic (per-dart, totals, checkout calls)
    ├── voicepack.py               # Sound directory resolution + voice-pack installer
    ├── voicepack_editor.py        # Per-key plan read/write (tomlkit, comment-preserving) + synth for the Settings Voice Pack tab
    ├── mqtt_output.py             # MQTT publisher with auto-reconnect
    ├── audio_engine.py            # Browser-based audio: play instructions over WebSocket
    ├── recorder.py                # Session recorder
    ├── board_status.py            # Board-status resolution shared by the cloud and local board connections
    ├── board_darts.py             # Darts currently on the board (positions from the local board stream)
    ├── dev_demo.py                # Runtime-triggered X01/Elimination demo runs for the Settings Dev tab
    ├── output_console.py          # Console state printer
    ├── known_players.py           # Player roster/win-count helpers (thin wrapper over StatsDB)
    └── web/
        ├── server.py              # FastAPI + WebSocket server
        ├── static/                # Favicons, manifest, header image
        └── dist/                  # Built Web UI (from frontend/, gitignored — see Setup step 2)
```

## Acknowledgements

- The calling behavior, the call keys and the voice-pack format are modeled on the darts-caller project, so its voice packs work unchanged.
- The packs offered by `main.py voicepack --install` come from that project's sound catalog, hosted by a third party with no published license. Nothing is bundled, and nothing is downloaded unless you ask for it.
- Breakfast is an independent project and not affiliated with or endorsed by Autodarts. It talks to the Autodarts cloud with your own account; check Autodarts' terms of use for your setup.

## License

MIT, see [LICENSE](LICENSE).
