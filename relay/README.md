# Breakfast relay

Lets Breakfast installations at different places play one Elimination match together. A
Cloudflare Worker with one Durable Object per match; every site connects to it with an
outgoing WebSocket, so no port forwarding or VPN is needed.

- `PROTOCOL.md`: the messages, close codes and rules (protocol version 1)
- `DESIGN.md`: why it is built this way
- `src/protocol.ts`: frame types and validation, `src/core.ts`: the match state machine (plain
  TypeScript, no Cloudflare APIs), `src/worker.ts`: the Worker and the Durable Objects
- `protocol-tests/messages.json`: example frames the relay and the Python client are both
  tested against

The folder does not import anything from `breakfast/`, so it can move to its own repository
(`git filter-repo --subdirectory-filter relay`).

## Develop

```bash
cd relay
npm install
npm test            # state machine and protocol, in plain Node
npm run typecheck
npm run dev         # wrangler dev on http://127.0.0.1:8787 (workerd, local Durable Objects)
```

Then point a Breakfast at it with `[online] relay_url = "ws://127.0.0.1:8787"`.

## Deploy

```bash
npx wrangler login
npm run deploy
```

Use the `wss://` address wrangler prints as `relay_url`. The free plan is enough for a few
players: a match only costs a few small messages per turn.

## Usage reports

`POST /telemetry` takes the anonymous usage and error reports of Breakfast installations (`[telemetry]`
in their config, off by default) and stores them in a D1 database. Every batch is checked strictly
(fixed fields per event type, 16 KB, 50 events) and limited per address and per installation; the address
itself is never stored. Set it up once:

```bash
npx wrangler d1 create breakfast-telemetry     # put the printed database_id into the config you deploy with
npx wrangler d1 migrations apply breakfast-telemetry --remote
npm run deploy        # or: npx wrangler deploy -c <your config>, if you keep your own with the database_id and a domain
```

Without the `DB` binding the route answers 503 and the rest of the relay is not affected. Read the reports with
`npx wrangler d1 execute breakfast-telemetry --remote --command "SELECT type, COUNT(*) FROM events GROUP BY type"`;
locally, `migrations apply ... --local` and `npm run dev` give a database to try it against.

## Try it by hand

Two Breakfast installations on one machine, each with its own `config.toml` and database:

1. `npm run dev` in `relay/`
2. In both configs: `[online] relay_url = "ws://127.0.0.1:8787"` and a different `site_name`; give them
   different `[web] port`s and `[stats] db` files.
3. Start both (`python main.py ...`), open `#elimination` on each, pick **Online**.
4. On the first: set a password, **Create**. On the second: the same password, the code, **Join**.
5. Pick the players of each site, **Start** on the first. Both TV views (`/#tv`) show the match; a turn
   thrown on one board appears live on the other.

To see the pause and rejoin: cut the network of one site for a minute (or close its connection to
the relay). The others show "Waiting for ... to reconnect", and the site rejoins by itself when the
connection is back. If it stays away for three minutes the host decides: play on without it or end
the match.

Limits for now: a Breakfast that is restarted mid-match cannot rejoin (the match lives in its memory),
and undo and turn corrections are off in online matches; tapping a wrong dart on your own turn works.

`pytest tests/test_online_e2e.py` plays whole matches between two sites against `wrangler dev`
(it is skipped without `npm install` in `relay/`).
