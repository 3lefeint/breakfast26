# Voice Packs & Sound Files

A practical guide to how Breakfast's sound system is organized and named —
written for anyone setting up or recording sounds, without needing to read
the caller code.

## How it works

Every sound is just a file named after a **call key**
(`matchon.mp3`, `t20.mp3`, `180.mp3`, ...). When something happens in a
game — a match starts, a dart lands, a leg is won — the caller asks the
audio engine to play one or more of these keys. If the file doesn't exist,
that call is silently skipped (or, for a few keys, a fallback key is tried
instead — see "Fallback chains" below). Nothing ever errors out because a
sound is missing.

### Directory layout

```
<audio dir>/                  # [audio] dir in config.toml — your own sounds
  matchon.mp3
  t20.mp3
  180.mp3
  freipass.mp3
  ...
  achievements/               # jingles for earned achievements, see below
    achievement.mp3
    achievement_ton_up.mp3
  profiles/                   # installed/downloaded voice packs
    en-US-Joey-Male/
      matchon.mp3
      ...
```

Your own `<audio dir>` is always the base set. If `[audio] profile` is set
to one of the `profiles/<name>/` directories, that pack is searched
**first**, and your own set fills in any key the pack doesn't have (e.g.
Elimination-specific keys like `freipass` or `eliminated`, which downloaded
packs never include). This fallback happens **per key**, not per file: a
key found in the profile only ever uses that profile's own variants — a
profile's `t20.mp3` is never mixed with your own set's `t20+1.mp3`.

### Variants (`key+1.mp3`, `key+2.mp3`, ...)

Multiple recordings of the same call key are picked at random. `t20.mp3`,
`t20+1.mp3`, `t20+2.mp3`, ... are all valid variants of the `t20` key — add
as many as you like, numbered from 1. This is how the real darts-caller
voice packs avoid repeating the exact same clip every time.

### Two score namespaces that never mix

There are two families of plain-number files, and they are kept strictly
separate:

- **`{n}`** — an *achieved* score, said with an excited tone. Used for
  per-dart score calls, turn totals, and Elimination's running total
  (`0.mp3` .. `180.mp3`).
- **`require_{n}`** — a *required* score (how many points are still
  needed for checkout), said with a calm, instructional tone. Only ever
  used for "you require ..." calls.

If a `require_{n}` recording is missing, the checkout call still plays
`you_require` but skips the number — it never falls back to the euphoric
`{n}` file, since that would sound wrong (excited tone for "you need to
score"). Recording your own `require_2.mp3` .. `require_170.mp3` (minus the
[bogey numbers](#bogey-numbers), which get their own optional
`ambient_bogey_number_{n}` instead) is the single biggest gap in most voice
packs downloaded via `python main.py voicepack --install`.

### Fallback chains

A handful of keys are tried in order, first match wins:

| Wanted | Tries in order |
|---|---|
| Match start | `matchon` → `gameon` |
| Match won | `matchshot` → `gameshot` |
| Leg won | `gameshot_l{n}_n` (e.g. `gameshot_l3_n`, a real-life "game shot, leg 3" style recording) → `gameshot` + `leg_{n}` played back to back |
| Bogey-number ambient | `ambient_bogey_number_{n}` → `ambient_bogey_number` |
| Ambient lifecycle calls | `ambient_{event}_{player}` → `ambient_{event}` (e.g. `ambient_matchon_dave` → `ambient_matchon`) |
| Player name | lowercased player name (e.g. `dave.mp3`) → `player{N}.mp3` (generic seat-number fallback) |

## Call-key reference

Only keys the caller actually plays today are listed (Cricket calling
isn't implemented yet, so it's left out). "Optional" means: if the file is
missing, that specific call is skipped — everything else keeps working.

### Shared lifecycle (X01 + Elimination)

| Key(s) | When it plays | Required? |
|---|---|---|
| `matchon` (→ `gameon`) | A new match starts | Recommended |
| `gameon` | A new leg starts (not the first one) | Optional |
| `<player name>` (lowercase) / `player{N}` | Whenever a player is announced (match start, leg won, checkout call, player change) | Optional |
| `matchshot` (→ `gameshot`) | The match is won | Recommended |
| `gameshot_l{n}_n` / `gameshot` + `leg_{n}` | A leg is won (not the match) | Recommended |
| `matchcancel` | The match ends without a winner (aborted) | Optional |
| `busted` | A turn busts (would take the player below 0/1) | Recommended |
| `ambient_matchon` / `_gameon` / `_matchshot` / `_gameshot` / `_matchcancel` (each with an optional `_{player}` variant) | Same moments as above, played on a separate ambient channel that never interrupts voice calls | Optional — the whole ambient layer can be left empty |

### Achievements

Not spoken and not part of a voice, so these sounds live in their own folder,
`<audio dir>/achievements/`, searched after your own set and the voice pack.
They play with the unlock banner on `/tv` when the match is over, once per
earned achievement.

| Key(s) | When it plays | Required? |
|---|---|---|
| `achievement_<id>` (e.g. `achievement_ton_up`) | That achievement is earned | Optional |
| `achievement` | Any achievement is earned and there is no file for its own `achievement_<id>` | Optional |

Variants work as everywhere else (`achievement+1.mp3`, `achievement_ton_up+1.mp3`, ...).
The ids: `first_breakfast`, `bullseye`, `shanghai`, `double_pack`, `maximum`,
`triple_bull`, `maximum_collector`, `a_hundred_served`, `ton_up`, `first_bite`,
`job_done`, `last_dart_finish`, `double_trouble`, `high_finish`,
`straight_to_the_double`, `big_fish`, `perfect_leg`, `last_at_the_table`,
`raising_the_bar`, `one_is_enough`, `second_chance`, `last_life_standing`,
`untouchable`, `full_house`, `hat_trick`, `no_free_ride`, `maximum_beaten`,
`back_from_the_brink`, `target_acquired`, `nine_out_of_nine`, `no_empty_rounds`,
`on_target`, `sharpshooter`, `perfect_battle`, `photo_finish`, `final_round_comeback`,
`double_focus`, `triple_focus`, `either_side_of_twenty`, `wrong_maximum`,
`better_late_than_never`, `exactly_sixty`, `extended_breakfast`, `regular_guest`,
`heavy_hitter`, `average_class`, `short_order`, `bullseye_finish`, `streak_master`,
`closing_routine`, `checkout_collector`, `roughly_pi`, `repdigit`, `small_fry`,
`fasting`, `deja_vu`, `case_of_the_jitters`, `spoilsport`, `lonely_one`, `early_bird`,
`night_owl`, `answer_to_everything`, `burnt_toast`, `breakfast_switch`, `not_found`,
`service_unavailable`, `full_english`, `copying_costs`, `a_new_low`,
`free_pass_failed`, `one_crumb_is_enough`, `tied_to_the_grave`, `after_me_the_deluge`,
`chips_for_breakfast`, `close_still_costs`, `beast_mode`. Without any file nothing plays, the banner still shows.

### X01-specific

| Key(s) | When it plays | Required? |
|---|---|---|
| `d{1-20}` / `t{1-20}` / `bull` / `bullseye` | Per-dart call, by field hit (double 16 → `d16`, triple 20 → `t20`, outer bull → `bull`, inner bull → `bullseye`) | Recommended for per-dart mode |
| `{n}` | Fallback per-dart call for a single (no dedicated single-number files needed — plain score files cover it) | Recommended |
| `outside` | A dart misses the board | Recommended |
| `double` / `triple` (played before the number, only if the `d{n}`/`t{n}` file above is missing) | Per-dart call fallback | Optional |
| `{n}` (turn total, after the 3rd dart) | End of a turn, not-per-dart mode or in addition to per-dart calls | Recommended |
| `you_require` + `require_{n}` | Turn start, checkout is reachable with 3 darts (2–170, not a bogey number) — see the [namespace rule](#two-score-namespaces-that-never-mix) | Recommended for checkout calls |
| `ambient_bogey_number_{n}` / `ambient_bogey_number` | Turn start, remaining is a bogey number (see below) | Optional |
| `ambient_checkout_call_limit` | A checkout call was rate-limited (`[caller] checkout_limit`) this turn | Optional |
| `ambient_playerchange_{player}` / `ambient_playerchange` | Player changes without any of the above being called | Optional |
| `ambient_{throw1}{throw2}{throw3}` (e.g. `ambient_t20t20t20`) / `ambient_{total}` / `ambient_150more` / `_120more` / `_100more` / `_50more` / `_1more` / `ambient_noscore` | Turn-total ambient ladder, by exact combo then by score threshold | Optional |

#### Bogey numbers

`159, 162, 163, 165, 166, 168, 169` — you cannot check out from these with
3 darts, so no checkout call is made for them; only the optional
`ambient_bogey_number_{n}` ambient plays instead.

### Elimination-specific

| Key(s) | When it plays | Required? |
|---|---|---|
| `freipass` | The very first player's opening turn (no target to beat yet), and again with 80% probability whenever a player restarts a fresh round with no target | Recommended |
| `miss` (35% probability) | A dart misses the board | Optional |
| `{n}` | Running turn total, per dart | Recommended |
| `close` (70% probability) | The turn total is close to the target | Optional |
| `too_low` (50% probability) | The turn total falls well short of the target | Optional |
| `nice` (40% probability) | A generic positive reaction | Optional |
| `eliminated` | A player is eliminated | Recommended |
| `life_lost` | A player loses a life without being eliminated | Recommended |
| `matchshot` + `<winner name>` | The game ends | Recommended |

### Target Battle-specific

| Key(s) | When it plays | Required? |
|---|---|---|
| `matchon` | The game starts | Recommended |
| `wheel` | A round with a random target starts and the wheel turns on `/tv`. A sound you supply (put `wheel.mp3` into your sound directory), the generation plan does not make it | Optional |
| `target_is` + `{n}` (the target) | The wheel has landed, 4.5 seconds after the round started; right away with a fixed target order | Recommended |
| `<player name>` + `filler_after_name` | A player is up: after the target at the start of a round, and for every next player | Recommended |
| `{n}` (the points of the turn, 0 and up) | After the third dart, or when the darts are pulled with fewer | Recommended |
| `nice` (40% probability) | All three darts of the turn scored | Optional |
| `<winner name>` (every winner) + `matchshot` | The game ends. Played alone, the total score is said instead | Recommended |

There is no call per dart. Undo and a corrected total make no calls.

### Killer-specific

| Key(s) | When it plays | Required? |
|---|---|---|
| `matchon` | The game starts | Recommended |
| `<player name>` + `bull_off` | The player throws at the bull to decide who starts | Recommended |
| `bull_off_tie` | Players are tied for the closest dart at the bull and throw again | Recommended |
| `<player name>` + `starts_game` | The bull-off is won (and the numbers are thrown next); without the number throw the player is called as the first one up instead | Recommended |
| `<player name>` + `throw_number` | The player throws for their number with the other hand | Recommended |
| `<player name>` + `throw_again` | The throw gave no number (taken, the bull, a miss), the player throws again | Recommended |
| `<player name>` + `your_number` + `{n}` | A number was thrown: the player is told it. With the numbers drawn at random it is told when the player is up for the first time instead of that it is their turn | | Recommended |
| `<player name>` + `filler_after_name` | A player is up: from the first turn on when the numbers were thrown, else from the second | Recommended |
| `<player name>` + `is_killer` | A double on the own number makes a killer | Recommended |
| `<player name>` + `life_lost` | A killer took a life from this player (the victim is named, a hit that puts a player out is only called as `eliminated`) | Recommended |
| `<player name>` + `own_goal` | A killer hit their own number, with the own goal option on | Recommended |
| `<player name>` + `eliminated` | A player is out | Recommended |
| `<winner name>` + `matchshot` | The game ends, with the dart that decides it | Recommended |

The calls follow the darts as they land, there is one group of calls per dart that did something and
none for a dart that did not. Before the game only the first dart of a visit counts and is called at once. Undo and a corrected last turn make no calls.

## Recording your own pack

You don't need full coverage to get started — missing keys are just
skipped, so build up gradually:

1. **Pick where it goes.** Your own recordings can live directly in
   `<audio dir>` (always active, no config needed), or under
   `<audio dir>/profiles/<some-name>/` if you want to keep them as a
   selectable pack alongside downloaded ones (`[audio] profile =
   "<some-name>"` in `config.toml`, or the Voice-pack field in the
   Settings tab).
2. **Start with the lifecycle set** (`matchon`, `gameshot`, `busted`,
   your own name(s) or `player1`/`player2`/...) — this alone makes every
   game recognizably "called."
3. **Add score files `0.mp3`..`180.mp3`** for per-dart/turn-total calls —
   the biggest chunk of files, but they're just spoken numbers and are
   shared by X01 and Elimination.
4. **Add field files** (`d1`..`d20`, `t1`..`t20`, `bull`, `bullseye`,
   `outside`) if you want doubles/triples announced by name instead of
   falling back to the plain number.
5. **Add `require_{n}`** files last — there are ~162 of them (2–170 minus
   bogey numbers), the most tedious set to record, and the caller degrades
   gracefully (`you_require` with no number) until they exist.
6. **Name files exactly as the key**, lowercase, `.mp3` or `.wav`
   (`t20.mp3`, not `T20.mp3` or `Triple20.mp3`). For more than one take of
   the same key, add `+1`, `+2`, ... (`nice.mp3`, `nice+1.mp3`).
7. **Test it** by starting a match/Elimination game and opening
   `http://<host>:8080/audio` in a tab with sound enabled — missing keys
   simply stay silent, so play a few turns and listen for gaps rather than
   expecting an error.

## Downloadable packs

```bash
python main.py voicepack --list                     # catalog
python main.py voicepack --install en-US-Joey-Male  # into <audio dir>/profiles/
```

These are third-party recordings (Amazon Polly / Google / OpenAI TTS
voices) from the darts-caller project's catalog — no license is published
for them, so installing one is an explicit opt-in, never automatic. They
cover the lifecycle/field/score vocabulary well but are missing
Elimination-only keys (`freipass`, `eliminated`, ...) and the entire
`require_{n}` namespace — your own `<audio dir>` set fills both gaps
automatically as the fallback.
