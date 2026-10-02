# X01 Audio Call Order — Review

Every X01 audio trigger, one at a time: what plays today, what stands out, the options, and a
proposal. The decisions are recorded here when they are made, the same way
`ELIMINATION_AUDIO_ORDER.md` does it for Elimination. The decisions are implemented, except case 12.

**Status: cases 1 to 11 are decided, case 12 (pacing) stays open until it can be measured with the real voice pack.** The decisions are implemented, except case 12.

## How X01 audio works

`Caller` (`breakfast/caller.py`) turns the game events into calls. The lifecycle events (match
start, leg start, bust, won, cancelled) are handled there, the per-dart and turn-end calls in
`X01Caller` (`breakfast/caller_x01.py`).

| Event | Raised when |
|-------|-------------|
| `match_started` | a match begins (first leg) |
| `game_started` | a further leg begins |
| `dart` | a dart lands; it carries the field, number, multiplier and the dart's place in the turn |
| `bust` | the turn ended in a bust (instead of a dart event for the busting dart) |
| `turn_end` | the darts were pulled; the snapshot already shows the **incoming** player and their remaining |
| `won` | a leg (`scope: game`) or the match (`scope: match`) was won |
| `match_ended` | the match closed; only a cancellation is announced, a won match was already |

Playback: the voice channel is one queue, every sound waits for the one before it.
`break_last` (used by the per-dart calls) cuts the sound that is playing and empties the queue.
Keys that start with `ambient_` go to a second channel that never interrupts the voice. A
`with audio.batch():` block sends a known sequence in one message so the browser fetches it in
parallel.

Settings (`[caller]`): `per_dart` (true), `turn_total` (true), `checkout_limit` (1, 0 = off),
`announce_change` (false), `call_player` (true), `ambient_volume` (0.6, 0 = ambient off),
`call_misses` (true).

### What happens today

The sequences below come from running the real `Caller` with a sound set that has every key except
the plain single field files (`s5`), the way the own set is. `!` marks `break_last`, `~` the ambient
channel, `(x missing)` a key that does not exist.

| Situation | Calls, in order |
|-----------|-----------------|
| Match starts | `anna`, `matchon`, `ambient_matchon_ashi`~ |
| Dart 1, T20 | `t20`! |
| Dart 2, S5 | `5`! (`s5` is missing, the number is called) |
| Dart 3, miss next to 7 | `m7`!, `65` (the turn total), `ambient_t20s5m7`~ |
| Three T20 | `t20`!, `t20`!, `t20`!, `180`, `ambient_t20t20t20`~ |
| Darts pulled, next player has 501 | `ambient_playerchange_bruno`~ (no name) |
| Next player has 80 | `anna`, `you_require`, `require_80` |
| Same player, again 80 (limit 1) | `ambient_checkout_call_limit`~, `ambient_playerchange_ashi`~ (no name) |
| Next player has 169 (bogey) | `ambient_bogey_number_169`~, `ambient_playerchange_ashi`~ (no name) |
| Next player has 40, `require_40` missing | `anna`, `you_require` (and then nothing) |
| Bust | `busted`, `ambient_noscore`~ |
| Leg won | `gameshot_l1_n`, `anna`, `ambient_gameshot_ashi`~ |
| Next leg starts | `carl`, `gameon`, `ambient_gameon_bruno`~ |
| Match won | `matchshot`, `anna`, `ambient_matchshot_ashi`~ |
| Match cancelled | `matchcancel` |

---

## Case 1 — Match start

**Current behavior:** `match_started` plays the first player's name, then `matchon` (or `gameon` if
there is no `matchon`), then the ambient chain `ambient_matchon_<player>` → `ambient_matchon` →
`ambient_gameon_<player>` → `ambient_gameon`. The name is skipped if `call_player` is off; a name
without a recording falls back to `unknown_player`.

**Observations:**
- The order is name → `matchon`. Elimination was changed to `matchon` → name → `filler_after_name`
  ("Neus Spiel, Peter, du bisch am Zug"). X01 reads "Peter, match on".
- `matchon` and `gameon` are the only separate keys for the whole opening; no "you require" or
  anything about the starting score.

**Options:**
- **A. Keep it.** The order is established and the recordings fit it.
- **B. Same order as Elimination:** `matchon` → name (→ optionally a filler such as
  "you start"). Needs the filler key recorded if it is wanted.

**Proposal:** B if the packs were recorded with a continuation in mind ("match on, Peter"), otherwise A.
Worth checking against the real voice pack first.

**Decision:** A. Keep it: name, then `matchon`. No code change.

---

## Case 2 — Leg start

**Current behavior:** `game_started` (never for the first leg) plays the name of the player who
starts, `gameon`, then the ambient chain `ambient_gameon_<player>` → `ambient_gameon`.

**Observations:** Same order as Case 1 and the same question. The first player of a leg is
announced here, and `turn_end` right after may add an ambient `ambient_playerchange_<player>`
(Case 6) for the same player.

**Options:** follow Case 1 (A or B).

**Proposal:** whatever Case 1 gets, for consistency.

**Decision:** A, same as Case 1: name, then `gameon`. No code change.

---

## Case 3 — Per-dart call

**Current behavior (`per_dart` on):** every dart is called by its field key (`t20`, `d16`, `m7`,
`bull`, `bullseye`), always with `break_last`, so a call that is still playing is cut when the next
dart lands. Fallbacks: a field without a recording falls back by type — a single is called by its
number (`5`), a miss by `outside`, a double or triple by `double`/`triple` followed by the number.
The dart that wins the leg is silent (the win call follows). A bust has no dart event for the
busting dart, so that dart is not called. `call_misses` off silences only the misses.

**Observations:**
- There is no probability on the per-dart calls; Elimination's miss comment fires with 0.35.
- A bust gives `busted` after the darts before it, without the busting dart's own call.
- Plain singles (`s5`) are not in the own set, so every single is announced as a bare number
  (`5`), which is the same file as the turn total's vocabulary (Case 4).

**Options:**
- **A. Keep it.**
- **B. Call only the interesting darts** (doubles, triples, bulls, misses), singles silent. Quieter
  and faster, but a single becomes a silent dart, which can read as "not detected".
- **C. Keep all calls but a probability on misses**, like Elimination's.

**Proposal:** A. If the turn feels long (Case 12), B is the first thing to try, since it removes
the most audio per turn.

**Decision:** A. Keep it: every dart is called. No code change.

---

## Case 4 — Turn total

**Current behavior (`turn_total` on):** after the third dart the total of the turn is called as a
plain number (`65`, `180`), queued after the dart's own call. Not called when the third dart wins
the leg, and not for a bust (there is no third dart event). A turn that scores nothing plays `0`.

**Observations:**
- With `per_dart` on, the third dart's call and the total are two voice items back to back.
- With `per_dart` off, the total is the only call of the turn (shown in the last example of the
  table above: a total and the ambient combo, nothing for the first dart).
- The total uses the plain number files (`0`–`180`), the same files the single-dart fallback uses.

**Options:** A. Keep it. B. Call the total only from a threshold (100 and up), the way a caller does.

**Proposal:** A.

**Decision:** A. Keep it: the turn total is always called (`turn_total` still switches it off). No code change.

---

## Case 5 — Ambient turn ladder

**Current behavior:** with `ambient_volume` above 0, after the third dart: `ambient_<f1><f2><f3>`
(for example `ambient_t20t20t20`), else `ambient_<total>`, else the first of `ambient_150more`,
`ambient_120more`, `ambient_100more`, `ambient_50more`, `ambient_1more` that fits, and
`ambient_noscore` for a turn of 0. Plays on the ambient channel in parallel with the voice.

**Observations:** It never replaces the voice calls; with a pack that has no `ambient_*` files it is
simply silent. After a bust `Caller` plays `ambient_noscore` (Case 8).

**Options:** A. Keep it. (There is nothing to reorder, it is parallel to the voice.)

**Proposal:** A.

**Decision:** A. Keep it. No code change.

---

## Case 6 — Turn end: the checkout call

**Current behavior (`turn_end`):** for the **incoming** player, if `checkout_limit` is not 0 and the
remaining score is 2 to 170:
- a bogey number (159, 162, 163, 165, 166, 168, 169): ambient only (`ambient_bogey_number_<n>`,
  else `ambient_bogey_number`), nothing spoken;
- otherwise, while the same remaining score has been announced at most `checkout_limit` times for
  this player: name (if `call_player`), `you_require`, `require_<n>`; `require_<n>` is only played
  if `you_require` exists, and never replaced by the score numbers, so a missing `require_<n>` ends
  the sentence after "you require";
- over the limit: ambient only (`ambient_checkout_call_limit`).

The counter is per player and per remaining score and resets when the remaining changes or the
match starts.

**Observations:**
- A missing `require_<n>` leaves "Anna, you require" without a number (shown in the table).
- Over the limit nothing is spoken, not even the name (this is issue #6, see Case 7).
- The name inside the checkout call is gated by `call_player`; the name in Case 7 is not.

**Options for a missing `require_<n>`:**
- **A. Keep it** (the sentence stops; the rule is that required scores never reuse the excited score files).
- **B. Skip `you_require` too** when `require_<n>` is missing, so the player is not left with half a sentence.
- **C. Spell the number** from digit files if the pack has them.

**Options for the repeat limit:** A. keep `checkout_limit = 1`. B. raise the default (2–3).

**Proposal:** B for the missing number (a half sentence is worse than silence), A for the limit.

**Decision:** Missing `require_<n>`: option B, skip the whole checkout call (no `you_require` either). Repeat limit: A, `checkout_limit` stays 1.

---

## Case 7 — Turn end: announcing the player (issue #6)

**Current behavior:** if no checkout call was made, the incoming player is called only when
`announce_change` is on (default **off**) and there is more than one player. Otherwise only
`ambient_playerchange_<player>` (or `ambient_playerchange`) plays on the ambient channel.

**Observations:**
- With the defaults the incoming player is **never** named outside a checkout call: every turn above
  170 remaining changes players in silence (see the table: "Darts pulled, next player has 501").
  Inside the checkout range the name is only part of the checkout call, so once the limit applies it
  disappears as well. That is exactly the symptom of #6, and it is the default, not a fault.
- `announce_change` does not look at `call_player`: with `call_player` off and `announce_change`
  on, names are still announced at turn end (checked), but not at match or leg start.

**Options:**
- **A. Keep the default off** and document it (the issue's "by design" answer).
- **B. Default `announce_change` to on** (names at every change; the checkout call then does not
  repeat the name, as today).
- **C. Name the player always, separate from the checkout call**: name first, then the checkout
  call without the name (changes the structure of Case 6).
- Independent of the above: make `announce_change` respect `call_player`.

**Proposal:** B, plus the `call_player` fix. With several players at the board a change in silence
is the thing people notice.

**Decision:** B. `announce_change` defaults to on. `announce_change` respects `call_player`, so with `call_player` off no name is called at turn end either.

---

## Case 8 — Bust

**Current behavior:** `busted`, then `ambient_noscore` at the ambient volume. The busting dart has
no call of its own.

**Observations:**
- The ambient call is not guarded by `ambient_volume`: with the ambient off (volume 0) the bust
  still sends `ambient_noscore`, just at volume 0 (checked). Everything else ambient is skipped at 0.
- No name and no total on a bust.
- Since the busting dart is now stored with the turn (#16), its field is available if it should be
  called.

**Options:** A. Keep it. B. Call the busting dart first (`t20`, then `busted`). C. Skip the
`ambient_noscore` at volume 0.

**Proposal:** C (a plain bug), A for the order.

**Decision:** `ambient_noscore` is skipped at `ambient_volume` 0 (bug fix). The busting dart is not called, order stays `busted` then ambient (A).

---

## Case 9 — Leg won

**Current behavior:** `gameshot_l<n>_n` as one recording ("game shot and the leg"), or `gameshot` then
`leg_<n>`; then the winner's name; then `ambient_gameshot_<player>` → `ambient_gameshot`. The leg
number is the leg just finished.

**Observations:** The winner is named **after** the call: "Game shot and the leg, Anna". Elimination
moved the winner's name before `matchshot` ("Max, du hesch gwunne").

**Options:** A. Keep it. B. Name first (name, then `gameshot_l<n>_n`).

**Proposal:** decide together with Case 10 so legs and the match read the same way.

**Decision:** B. The winner's name comes first, then `gameshot_l<n>_n` (or `gameshot` and `leg_<n>`). Note: `gameshot_l<n>_n` is recorded as one block, so check that it reads well after a name.

---

## Case 10 — Match won

**Current behavior:** `matchshot` (or `gameshot` if there is none), the winner's name, then
`ambient_matchshot_<player>` → `ambient_matchshot` → `ambient_gameshot_<player>` → `ambient_gameshot`.

**Observations:** The same order Elimination used before its change; `matchshot` is shared with
Elimination, which now plays it after the name. The Elimination review noted that the recording
reads fine either order.

**Options:** A. Keep it. B. Name → `matchshot` (like Elimination).

**Proposal:** B, so one `matchshot` recording reads the same in both games.

**Decision:** B. Name, then `matchshot` (or `gameshot`), same as Elimination.

---

## Case 11 — Match cancelled

**Current behavior:** if the match closes without a win, `matchcancel` and then
`ambient_matchcancel_<player>` → `ambient_matchcancel`. A won match is silent here.

**Observations:** nothing unusual; no name.

**Options:** A. Keep it.

**Proposal:** A.

**Decision:** A. Keep it. No code change.

---

## Case 12 — Pacing (across all cases)

**Current behavior:** all voice sounds go through one queue; there is no gap or pause setting.
At the end of an ordinary turn the board produces up to four voice items (three dart calls,
cut by `break_last` as the next dart lands, and the total), then at the pull the checkout block
(name, `you_require`, `require_<n>`) as one batch.

**Observations:**
- The feeling that the turn-end phrases are slow is about the queue after the pull: three phrases
  back to back, each as long as its recording.
- The real length depends on the voice pack; it cannot be measured without its sound files.

**Measuring (needs the real sound files):** with `ffprobe`, add the durations of the files of a
typical sequence — `<name>` + `you_require` + `require_<n>` for the checkout block, and `<field>` +
`<total>` for the end of a turn — and compare that to the time between the darts being pulled and
the next dart.

**Options:** shorter recordings or combined ones (as Elimination did with the "continuation after a
name" phrasing), Case 3 option B (fewer calls per turn), or dropping the name from the checkout
call when only two players play.

**Proposal:** measure first; the options above are cheap to try once there is a number.

**Decision:** open until the real voice pack is measured (needs the sound files, not on this machine).

---

## What this review does not cover

Sets (only legs are called), Cricket and other modes (no handler is registered, they are silent),
and Freeplay (it has its own small call set in `source_direct.py`).
