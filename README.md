# Breakfast

*Works with [Autodarts](https://autodarts.io).*

Self-hosted darts companion for Autodarts: live scoreboard, elimination game
mode, board control, built-in voice caller with custom voice-pack creation,
and lifetime statistics — with optional MQTT output for LED/display
control.

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
- **TV / kiosk mode** (`/tv`): full-screen live view for wall-mounted displays and tablets, no navigation — X01 scoreboard (remaining score, checkout hint, dart boxes) or the live Elimination game, whichever is active
- **Checkout suggestions**: standard X01 checkout path shown below the remaining score
- **Live session stats**: 3-dart average, 180s, checkout % shown next to each player during a match
- **Lifetime statistics tab**: per-player averages, 180 / 140+ / 100+ counts, checkout & double-hit rates across all sessions; per-player reset with double confirmation
- **Leaderboards**: top-10 by average, 180s, checkout %, double % in the Stats tab
- **Leg tracking**: legs won per player recorded per match; shown live in the scoreboard and in match history
- **MQTT auto-reconnect**: reconnects with exponential backoff when the broker drops mid-session
- **Elimination** game mode with unlimited players, life management, turn correction,
  optional random turn order for a new game, and a win-count crown for the current leader
- **Board control** (direct mode): Undo throw, Next Player, Next Leg, Reset Board, Correct Throw — all on the `/tv` live view
- MQTT output for ESPHome / LED strips (works without Home Assistant)
- Session recording and replay — develop without throwing darts
- Config file — no long CLI commands needed in production
- **Settings tab**: edit all `config.toml` settings from the browser without touching the file, organized into General / MQTT / Autodarts Source / Voice & Caller categories
- **X01 win tracking**: alongside Elimination wins, the Players tab shows each player's X01 match win count too
- **Advanced per-player dashboard** (Stats tab): activity/performance charts, scoring buckets, average & checkout-% over time, win/loss and game-type ratio, doubles hit rate, and Top 10 Legs (filterable by starting score, e.g. 301/501) / Top 10 Checkouts
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

[mqtt]
host     = "192.168.1.10"
port     = 1883
username = "mqtt"
password = "mqtt"

[web]
port = 8080

# [stats]
# db = "stats.db"       # SQLite file for per-turn data; "none" to disable

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
(**Games**, **TV**, **Board**, **Players**, **Stats**, **Settings**), each a
deep-linkable view (`/#elimination`, `/#players`, `/#stats`, `/#settings`).
The live scoreboard itself (X01 and Elimination) lives on the separate
`/tv` page, not on the hub — see below.

| View | What it shows |
|------|--------------|
| **Home** (`/`) | Hub landing page: Games (Elimination setup/rematch), TV, Board (jump-off link to the local Autodarts board manager, if configured), Players, Stats, Settings |
| **TV** (`/tv`) | Full live view: X01 scoreboard with dart boxes/checkout suggestion/board+match controls, or the live Elimination game (lives, turn order, tap-to-correct darts) — whichever is active; idle screen otherwise |
| **Players** | Known players list — name, Elimination win count, X01 win count, missing-audio indicator, hide/unhide |
| **Stats** | Lifetime per-player stats table, collapsible recent matches (expandable per-match detail), leaderboards, and the Advanced dashboard (per-player charts, Top 10 Legs/Checkouts) |
| **Settings** | Edit all `config.toml` settings from the browser, organized into General / MQTT / Autodarts Source / Voice & Caller tabs (plus a Dev tab if `[dev] enabled = true`); `log_level` applies immediately, everything else is saved to disk and needs a restart |

All connected clients update in real time via WebSocket.

### Voice caller (`/audio`)

With `[audio] dir` set, Breakfast announces X01 matches itself: match/leg
start, every dart by field name (*triple 20*, *double 16*), turn totals,
checkout calls (*you require ...*), bust, leg and match won. Sound plays in
the browser: open `http://<host>:8080/audio` on the device wired to the
room's speakers, click **Enable sound** once (browser autoplay policy), and
leave the tab open. Only tabs on `/audio` play sound — phones or tablets
showing the scoreboard stay silent.

Sound files are plain `key.mp3` files (`matchon.mp3`, `t20.mp3`, `180.mp3`,
`you_require.mp3`, ...; `key+1.mp3` etc. for random variants). Checkout
numbers use a separate calm-toned `require_{n}.mp3` namespace — if those
recordings don't exist, the number is skipped rather than reusing the
euphoric score file. Fine-tuning lives in the `[caller]` config section /
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

### TV / kiosk mode (`/tv`)

Open `http://<host>:8080/tv` on a wall-mounted display or tablet mounted
next to the board. Full-screen, no navigation — shows whichever game is
currently active:

- **X01**: large remaining score, checkout hint, dart boxes, compact
  all-player table, and the board/match control buttons below
- **Elimination**: lives per player, turn order, tap-to-correct darts, a
  win-count crown for whoever currently has the most Elimination wins, and
  the Stop/rematch/finished-match flow

It uses the same WebSocket connection as the rest of the app and reconnects automatically.

#### Board controls (direct mode only)

| Button | Description |
|--------|-------------|
| ↩ Undo | Remove last detected throw |
| ⏭ Next Player | Skip to next player |
| ▶▶ Next Leg | Start next leg/set |
| ⟳ Reset Board | Hard-reset the local board |
| ✓ Correct | Correct a misdetected throw (select dart 1/2/3, enter field e.g. `T20`) |

---

## Statistics

Per-turn data (score, remaining, bust/checkout flag, all three dart fields + remaining after each dart) is stored in a local SQLite file (`stats.db` by default). Stats are derived from this:

- **Session stats** (live, in-game): 3-dart average, 180 count, checkout % per player — updated after every turn with no database query
- **Lifetime stats** (Stats tab): same plus 140+, 100+, double-hit rate across all sessions
- **Leaderboards** (Stats tab): top-10 players by Best Average, Most 180s, Best CO%, Best Double %
- **Win counts** (Players tab): Elimination wins and X01 match wins, tracked separately per player
- **Double-hit tracking**: the remaining score is stored per individual dart, so the query can determine exactly which dart was thrown at a double (remaining ≤ 40 or = 50) and whether it was hit
- **Advanced dashboard** (Stats tab, per player): activity (darts/games/playtime), performance summary (best average/leg/checkout, total 180s), scoring buckets, average/checkout-% over time, win/loss and game-type ratio, doubles hit rate by number, Top 10 Legs (fewest darts to win — filterable by starting score, since a 301 leg and a 701 leg aren't comparable on darts alone) and Top 10 Checkouts

Reset all stats for a player: Stats tab → ✕ button → two confirmation dialogs.

To disable stats collection: `--stats-db none` or `[stats] db = "none"` in config.

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
  "version": "0.1.0",
  "release_date": "2026-07-08",
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

The Web UI footer shows two coloured dots (MQTT and Autodarts) that poll `/api/health` every 30 seconds — green = connected, red = disconnected — alongside the app version and release date.

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
version number in the Home footer 7 times in a row — same Android-style
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

**Stats**:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stats/players` | Lifetime stats for all players |
| `GET` | `/api/stats/player/{name}` | Lifetime stats for one player |
| `DELETE` | `/api/stats/player/{name}` | Delete all stats for a player (double-confirmed in the UI) |
| `GET` | `/api/stats/matches` | Recent matches (up to 20) |
| `GET` | `/api/stats/match/{id}` | Per-player stats for one match |
| `GET` | `/api/stats/dashboard/{name}?points_start=501` | Advanced per-player dashboard (one bundled fetch); `points_start` picks the Top 10 Legs mode, defaults to 501 or the lowest played mode |
| `GET` | `/api/leaderboard?metric=avg3&limit=10` | Top-N players by metric (`avg3`, `s180`, `co_pct`, `dbl_pct`, `total_score`) |

**Players**:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/players` | Known (non-hidden) players list |
| `POST` | `/api/players` | Add a known player |
| `PATCH` | `/api/players/{name}/hidden` | Hide/unhide a player (from the Players tab and leaderboards — reversible, unlike deleting stats) |
| `GET` | `/api/players/hidden` | Hidden players list |

**Config / voice pack**:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Current config (credentials masked) |
| `PATCH` | `/api/config` | Update config.toml; runtime fields (e.g. log level) apply immediately, the rest need a restart |
| `POST` | `/api/voicepack/generate` | Regenerate the voice pack (`force`: true re-generates every key, false only fills in missing ones) |

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
├── docker-compose.yml              # Compose service — see its header comments for full setup notes
├── .dockerignore
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
│       ├── tv/                    # TV app: X01 view, Elimination live/finished, dart-correct modal
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
    ├── caller.py                  # Voice caller: shared lifecycle calls + mode dispatch
    ├── caller_x01.py              # X01 call logic (per-dart, totals, checkout calls)
    ├── voicepack.py               # Sound directory resolution + voice-pack installer
    ├── mqtt_output.py             # MQTT publisher with auto-reconnect
    ├── audio_engine.py            # Browser-based audio: play instructions over WebSocket
    ├── recorder.py                # Session recorder
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
