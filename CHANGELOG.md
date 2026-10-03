# Changelog

## [Unreleased]

### Fixed
- Announcements are no longer cut off at the start or skipped: the `/audio` page, the TV page and the voice pack preview play through one shared audio context instead of opening a new stream per sound (#18).
- A sound that fails to load or play is reported in the audio page log and the browser console instead of being skipped silently (#18).
- Pages that connect get the current state, including the player list, instead of an older cached copy that could be empty until the next game event.
- A player added, hidden, unhidden or deleted in the Players tab updates the open pages right away.

## [0.8.0] - 2026-10-02

### Added
- Online Elimination: sites at different places play one match through a relay; the host sets lives and order, every site stores the whole match, the host can start a rematch from the result page, and the relay (`relay/`) is a Cloudflare Worker (#10).

### Fixed
- The X01 bust sound `ambient_noscore` no longer plays when the ambient volume is 0 (#8).
- The player is named at every change again once the checkout limit applies (#6).

### Changed
- X01: `announce_change` is on by default and follows `call_player` (#6, #8).
- X01: the winner's name is called before `gameshot` and `matchshot` (#8).
- X01: a checkout call without a `require_<n>` recording is skipped instead of stopping after "you require" (#8).
- Checkout % counts the darts thrown at a score a double can finish instead of the turns that started in checkout range, like Autodarts.
- Darts thrown at an odd score no longer count as checkout attempts.
- The Home pages scroll as a whole with header and footer pinned, so a full-page screenshot and a print capture the whole page (#17).

### Removed
- Double %: it showed the same numbers as checkout %.

## [0.7.0] - 2026-10-02

### Added
- About page behind an ℹ️ button in the footer: version, release time, joke of the day and changelog; `[web] joke_of_the_day` turns the joke off (#11).
- The position of every dart is stored for X01 and Elimination; the Stats heatmap can show where the darts landed, with a density overlay from 30 darts on, and the Elimination view gets the same board (#15).

### Fixed
- The dart that busts is stored, and a bust on the first dart no longer loses the turn (#16).

### Changed
- The release date is a UTC timestamp, the footer shows only the version (#11).

## [0.6.0] - 2026-10-02

### Added
- Stats tab, X01 view: overview, records, players compared and per-player charts, top 10 legs and checkouts (#14).
- Stats tab, Elimination view: overview and records, placements, form, head to head, game length and activity (#14).
- Stats tab: chips to switch between an X01 view and an Elimination view (#14).
- Elimination turns are stored with score, target and outcome (#14).

### Changed
- The Home pages scroll anywhere in the window and use a wider content column.
- The turn that ends an Elimination match is stored as well (#14).

### Removed
- Stats tab: the screen that mixed X01 and Elimination (#14).

## [0.5.0] - 2026-10-01

### Added
- TV view: dart boxes and the live dartboard while no match is running (#13).
- X01: tapping a dart box opens the correction dialog.
- TV view: live dart positions on a dartboard in X01 and Elimination (#12).
- Clickable dartboard for correcting a misdetected dart (#9).
- Expanded Elimination matches under Recent matches show placement, lives, turns and average (#5).
- Per-player dashboard: Elimination section with games, wins, win rate, placements and darts per turn (#1).

### Fixed
- X01 throw corrections send the field as `coords`, which Autodarts accepts instead of answering 502.

### Changed
- A rejected X01 throw correction logs the Autodarts response.

## [0.4.1] - 2026-09-30

### Fixed
- The update panel no longer reports "rolled back" while the update is still building (#3).
- The updater restarts itself through a detached helper container (#4).

## [0.4.0] - 2026-09-30

### Added
- DEBUG/INFO logging across the app; config changes log keys, never values.
- Colored log output, opt out with `NO_COLOR`; `LOG_LEVEL` sets the level, also for the updater.
- X01: "Bogey — no checkout" badge on /tv for scores without a 3-dart finish.
- Freeplay audio: a miss comment per dart and the turn total.
- The voice-pack profile setting is a dropdown of the installed profiles.
- Elimination: Undo walks back the last completed turn, also in a finished match.
- Settings: Voice Pack tab to add, preview, save and delete voice-pack entries.

### Changed
- Internal code comments and docs tidied.
- Solo X01 sessions no longer count toward wins and win/loss.

### Fixed
- Autodarts messages are processed one at a time in arrival order (#2).

## [0.3.0] - 2026-08-18

### Added
- The /tv header glows green/yellow/red with the board status.

### Fixed
- Elimination setup: the player chips and the game-players list no longer reflow each other.

## [0.2.0] - 2026-08-18

### Added
- GitHub issue templates for bug reports, feature requests, and change requests.
- Self-update: a Settings panel checks for and installs a newer release, via a new `updater` service, with rollback.

### Changed
- Dev-mode unlock needs 5 taps on the version number instead of 7.

## [0.1.0] - 2026-07-08
- Start of a clean tracked history.
