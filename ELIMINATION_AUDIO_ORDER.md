# Elimination Audio Call Order — Design Decisions

The audio call order of Elimination, decided one trigger point in
`breakfast/elimination.py` at a time. This file is the detailed record of
those decisions.

Baseline before the decisions below: Elimination calls `self.audio.play(...)` directly and inline —
it does not go through `breakfast/caller.py`'s Caller/ambient machinery the
way X01 does. No call anywhere in `elimination.py` passes `channel=` or
`break_last=`, so everything today is a plain sequential `voice`-channel
call — no ambient layer, no interruption semantics.

---

## Case 1 — Match start sequence

**Current behavior:** three calls, always in this order, fired together
0.5s after the match is created (`elimination.py:92-98`):
1. `play("matchon")`
2. `play(<first player's name>.lower())`
3. `play("freipass")` — unconditional, first player always starts with a
   freipass

**Decision:** new order — `matchon` → player name → **`filler_after_name`
(new key)**. Freipass is no longer announced at match start at all (the
old unconditional `play("freipass")` call is dropped from this sequence
entirely).

Example stitched phrasing: "Neus Spiel" (matchon) + "Peter" (name) + "du
bisch am Zug" (filler_after_name) → "Neus Spiel, Peter, du bisch am Zug."

`filler_after_name` is a **new voice-pack key**, not yet recorded — needs
adding to `tools/voicepack_leni.toml`. Likely reusable beyond just match
start (e.g. wherever else a player-name announcement currently has
nothing after it) — to be confirmed case by case as we go, not assumed
here.

---

## Case 2 — Per-dart miss call

**Current behavior:** every dart that lands as a miss (value 0) plays
`play("miss", prob=0.35)` — up to 3× per turn, independent of the rest of
the turn's outcome (`elimination.py:163`).

**Decision:** keep as-is, no change.

---

## Case 3 — Turn preview: score announcement

**Current behavior:** right after the 3rd dart of a turn lands, before
it's known whether the player survives: `play(str(running_score))`
(`elimination.py:181`).

**Decision:** keep as-is, no change.

---

## Case 4 — Turn preview: fail cue (eliminated / life lost)

**Current behavior:** immediately after the score announcement (Case 3),
if the turn score didn't beat the target: `play("eliminated")` if this
loss brings the player to 0 lives, else `play("life_lost")`
(`elimination.py:189`).

**Decision:** new order — **player name (new call, not previously
announced here) → `eliminated` / `life_lost`**.

**Later change:** the name is announced only before `eliminated`. A
`life_lost` after the 3rd dart plays without the name (the score is
followed directly by `life_lost`). The rare turn-end fallback (Case 7)
follows the same rule.

**Recordings must be re-recorded** to read as a natural continuation
after a name, not a standalone phrase:
- `life_lost`: "Peter, du hesch es Lebe verlore / minus eis"
- `eliminated`: "Peter, du bisch dusse / you lost"

(i.e. the existing `life_lost`/`eliminated` files in
`tools/voicepack_leni.toml` get their phrasing changed, same key names,
new content — not new keys.)

---

## Case 5 — close / too_low

**Current behavior:** only on a failed turn, after the fail cue (Case 4).
Mutually exclusive `if`/`elif` — at most one of the two can ever fire per
turn:
```python
if 1 <= gap <= 10:        # gap = target - score
    play("close", prob=0.7)
elif score < 5:
    play("too_low", prob=0.5)
```
If neither condition matches, this case is silent.

**Decision:** keep as-is, no change.

---

## Case 6 — nice (good score on a passing turn)

**Current behavior:** only on a passing turn (score beat the target),
after the score announcement: `play("nice", prob=0.4)`, only if
`score >= 100` (`elimination.py:197`).

**Decision:** change the threshold condition from `score >= 100` to
`score >= 2 * target` — i.e. "nice" now fires when the player scores at
least **double** the target they had to beat (the previous player's
turn total), regardless of the absolute score value. `prob=0.4` and the
call itself (`play("nice", ...)`) stay unchanged — only the trigger
condition changes.

---

## Case 7 — Turn-end fallback (when the preview didn't fire)

**Current behavior:** in rare cases (e.g. fewer than 3 darts detected),
the 3-dart preview (Cases 3/4) never ran. `_end_turn()`/`_apply_turn()`
then catches up with equivalent calls at a different point in the code:
fallback `play(str(score))` (`elimination.py:226`), and if needed
`eliminated`/`life_lost` (`elimination.py:245`/`274`, only if the
preview hadn't already announced it).

**Decision:** mirrors Cases 3 and 4 exactly — score stays as-is, then
player name → `eliminated`/`life_lost` (with the same re-recorded
phrasing decided in Case 4). No separate/simpler behavior for this
fallback path.

---

## Case 8 — Game over (matchshot + winner)

**Original behavior (before this redesign):** when only one active player
remains: `play_sequence("matchshot", winner.lower())`, fired after darts
were physically pulled from the board (`_end_turn()` → `_apply_turn()`)
— *after* the preview's Case 3/4 cues had already played right after the
3rd dart.

**Decision:** for the match-ending turn specifically, **skip Case 4
entirely** (no "Peter, du bisch dusse" for the final losing player) —
go straight from the score announcement (Case 3, unchanged) to the
winner announcement. New order: score → **winner name → `matchshot`**
(reversed from the old `matchshot` → name).

Example stitched phrasing: "Max" (winner name) + "du hesch gwunne"
(`matchshot`) → "Max, du hesch gwunne."

`matchshot` itself was left unchanged — shared with X01's caller (which
uses the opposite order), and the existing phrasing already reads fine
either way.

**Follow-up timing fix (implemented after live testing):** the match
now finishes **immediately in the 3-dart preview**
(`_publish_turn_preview()`), not after darts are physically pulled —
matching the original intent that the moment the score is known, the
game should already switch to the win announcement, not wait for the
board to report the darts being pulled. `_finish_match()` (shared by the
preview and the rare <3-dart fallback in `_apply_turn()`) does the full
state transition — `active`/`winner`/`state`/stats_db writes — right
there. `on_board_state()`'s existing `state != "playing"` guard means
`_end_turn()`/`_apply_turn()` are simply never invoked again for that
turn once the match is marked finished, so there's no double-processing
when the darts are eventually pulled.

**Known risk:** finishing the match on the 3-dart preview's tentative read
(before the throw is "confirmed" by the dart-pull/correction flow) means a
misdetected dart can end the match and record a wrong winner. The Undo
control walks the turn back, reopens the match and removes its result from
the stats.

---

## Case 9 — Next player name + freipass re-grant

**Current behavior:** at the end of `_apply_turn()`, after any
non-match-ending outcome (`elimination.py:280-283`):
1. `play(<new current player>.lower())` — announces whoever is now
   current
2. **Only if** the new current player just inherited a freipass from an
   elimination (`self.freipass` set `True` only in the "someone got
   eliminated" branch): `play("freipass", prob=0.8)` — always *after*
   the name, never before or bundled with it

**Decision:** order stays name → freipass (unchanged), but the
`freipass` recording itself needs updating to read as a natural
continuation after the name (same pattern as Cases 4/8) instead of a
standalone word.

Example stitched phrasing: "Peter" (name) + "du hesch en Freipass"
(`freipass`) → "Peter, du hesch en Freipass."

Same key, new content in `tools/voicepack_leni.toml` (not a new key).
`prob=0.8` unchanged unless said otherwise.

---

## Case 10 — Freipass consumption (currently silent)

**Current behavior:** when a turn only "passes" because of an active
freipass (score > 0 instead of score > target), there is no dedicated
audio cue marking that — the listener only hears the normal score/pass
cues (Case 3, and Case 6's "nice" if applicable), nothing that
distinguishes "passed on merit" from "passed only via freipass."

**Decision:** keep as-is, no change. Raised only because it was the one
fully silent moment found during the inventory — no concrete need
identified for marking it separately (a listener not watching the board
losing the "why did this pass" nuance is a minor cosmetic gap, not a
real problem worth extra recordings/complexity).

---

## Case 11 — Target announcement (missed in the original inventory)

**Current behavior (before this addition):** `self.target` (the score
the incoming player needs to beat) was never announced via audio at
all — only tracked internally for the pass/fail check and published in
`snapshot()`/MQTT state. The Case 9 "next player" block only ever played
the name (and freipass, when applicable) — a genuine gap missed during
the original case-by-case pass, since there was no existing audio call
to catalogue for it.

**Decision:** when the new current player does **not** have a freipass,
announce name → **`filler_target` (new key)** → **target + 1** (not the
bare target — `passes = score > target`, so the target value itself
would *not* be enough to pass; the announced number is the actual
minimum passing score), right where Case 9's freipass re-grant already
lives (`elimination.py:290-293`). When the player **does** have a
freipass, nothing changes from Case 9's decision (name → `freipass`) —
freipass means any score > 0 passes, so the target number is irrelevant
that turn and is deliberately **not** announced alongside it (the two
are mutually exclusive, not additive).

Example stitched phrasing (target was 42, so 43 is what's actually
announced): "Peter" (name) + "du bruchsch" (`filler_target`) + "43"
(target + 1) → "Peter, du bruchsch 43."

`filler_target` is a **new voice-pack key** (`tools/voicepack_leni.toml`,
"Elimination" group, next to `filler_after_name`) — variants `"du
bruchsch"` / `"es bruucht"`.

---

## Status

All 10 cases from the initial inventory plus Case 11 (found afterward)
have been discussed, decided, and **implemented** in
`breakfast/elimination.py` (Case 11 as a follow-up addition). Summary of what changed vs. the original
baseline:

- **Case 1** (match start): dropped the unconditional opening `freipass`
  call; added new `filler_after_name` key after the first player's name.
- **Case 2** (per-dart miss): unchanged.
- **Case 3** (score preview): unchanged.
- **Case 4** (fail cue): added a name announcement before
  `eliminated`/`life_lost`; both re-recorded to read as a continuation
  after a name.
- **Case 5** (close/too_low): unchanged.
- **Case 6** (nice): trigger condition changed from `score >= 100` to
  `score >= 2 * target`.
- **Case 7** (turn-end fallback): mirrors Cases 3/4 exactly.
- **Case 8** (game over): Case 4 skipped entirely on the match-ending
  turn; new order winner name → `matchshot` (reversed from before);
  `matchshot` left unchanged. Follow-up: the whole match now finishes
  immediately in the 3-dart preview instead of waiting for darts to be
  pulled; Undo reopens the match if the dart was misdetected.
- **Case 9** (next player + freipass re-grant): order unchanged
  (name → freipass), `freipass` re-recorded as a continuation after a
  name.
- **Case 10** (freipass consumption): unchanged, stays silent.
- **Case 11** (target announcement): new — name → `filler_target` →
  target + 1 (the actual minimum passing score), only when the player
  does *not* have a freipass.

**Voice-pack content** (`tools/voicepack_leni.toml`): two brand-new keys
(`filler_after_name`, `filler_target`), three re-recorded existing keys
(`life_lost`, `eliminated`, `freipass` — "continuation after a name"
phrasing instead of standalone), `matchshot` left unchanged (shared with
X01, existing phrasing already works either order — see the Case 8
resolution above). All generated via the Settings-tab "Regenerate voice
pack" button (force=True to pick up the re-recorded existing keys).
