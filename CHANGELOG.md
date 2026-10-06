# Changelog

## [Unreleased]

### Added
- A Security section in the README and a `SECURITY.md`: Breakfast has no login and belongs on a trusted network.
- Voice Pack tab: a pack selector, so every plan file `tools/voicepack_<name>.toml` can be edited, listened to and regenerated, not only Leni; it starts on the active profile if that has a plan (#37).
- English voice pack plan `tools/voicepack_ryan.toml` (en-GB-RyanNeural) with the same keys as the Leni plan.
- Language switch: the interface is English or German, one language per installation, set under Settings → General → Language or with `[web] language`; it covers Home, `/tv` and `/audio`, and the achievement names and descriptions follow it (#24).

### Changed
- The updater fetches releases over HTTPS without a deploy key, an SSH address of `origin` works too.

### Removed
- The `voicepack` command (`--list`, `--installed`, `--install`) and the catalog of downloadable voice packs; generate a pack with `tools/generate_voicepack.py`, see VOICE_PACKS.md.

## [0.10.0] - 2026-10-06

### Added
- Black Belt: the doubles drill for one player, D1 to D20 and the bull's eye (or backwards) without a restart, with three darts of its own per field and the darts left after a hit as bonus darts; a setup page, a live view on `/tv` with the ladder, a result with the furthest field, restarts, darts and how far each attempt got, a card on Home and a Black Belt chip in the Stats with the belts, the furthest, the darts and the runs per player. A run ends with the belt or when it is finished. Started through `/api/black-belt/*` or MQTT (#31).
- Field Training: one player throws a number of darts at one field, a number or the bull (100 darts at a number and 50 at the bull by default), with a setup page, a live view on `/tv`, a result with points, hit rate, singles, doubles and triples, the points per turn and a board of every dart, a rating and a personal best for a full run, a card on Home and a Training chip in the Stats with the best, the average, the trend and the hit rate per player and field; a shorter run or one ended early is saved as practice. Started through `/api/field-training/*` or MQTT (#30).
- Black Belt achievements: Black Belt, Coloured Belts and Dead Eye (#31).
- Field Training achievements: Bull Drill, Hundred Darts, Triple Threat and Grand Tour; a run that is only practice counts for Triple Threat alone (#30).
- Settings → Achievements (shown with the Dev tab): every achievement with the sound it plays now, one or more files of the achievements folder to assign to it, a preview, an upload of new sounds, and renaming and deleting the files; the assignment is stored in `[achievements.sounds]` and applies at once (#25).

### Changed
- Interface: a sidebar with the main places, a top bar with the board connection, a button for the TV and Settings, glass panels over a slowly moving aurora background in the color of the accent preset, and a new Play page with the games and the training drills as cards; Players shows an avatar for every player, a small dartboard drawn from the name in the hue of the player's color; the profile, the Stats, Settings, About, the pages of the games, and the frame of `/tv` and `/audio` and the X01, Elimination, Target Battle, Killer, Field Training and Black Belt views are in the same style, with the avatar of the player in place of a color dot next to a name and for the darts on the board, and an avatar for every player in the ranking of Elimination, and a new logo and favicons replace the old ones; the other pages follow one by one (#34).
- Settings: Restart and Updates show only under the General tab.


## [0.9.0] - 2026-10-04

### Added
- Achievements: 91 of them for every game mode, from Bullseye to the Four-Course Meal, some with tiers and 34 secret ones. The stats database records who earned which, an undo or correction that reopens a match takes it back (#23).
- Achievements: `/tv` shows an unlock banner when a player earns one, several one after the other, and plays `achievement_<id>` or `achievement` from the `achievements/` folder of the sound directory if a file exists (#23).
- Player profile: the Players tab opens a profile with the player's achievements as badges, in sections by game mode, with the progress to the next tier and the share of players who have each (#23).
- Badge motifs for every achievement, drawn in a style per game mode; an achievement without a motif shows a star (#23).
- Target Battle game with a setup page, a live view with a wheel for the target, a result page, voice calls, a `wheel` sound if you supply one, and a Stats chip with a scoring profile filter (#21).
- Killer game, started through `/api/killer/*` or MQTT, with a setup page, a live view on `/tv` that colors the field of every number in the color of its player, a result page with a rematch and a correction of the last turn, voice calls and a Stats chip (#20).
- Killer: a bull-off for the first player and a throw for the numbers before the game, both on by default (#20).
- Every X01 and Elimination turn stores the time it was played (#27).
- Setting `[stats] timezone` (also under Settings → Statistics, which suggests the zone of the browser while none is set), an IANA name such as `Europe/Zurich`, default `UTC` (#27).
- Player profile: a color picker for the player's color, stored with the player (#29).

### Changed
- Elimination: a dart corrected by tapping is stored with its field and counts for achievements, like a corrected dart in X01 (#27).
- Elimination, Target Battle and Killer share one base for the darts of a turn, corrections and undo; nothing changes from the outside (#28).
- Home: the cards are grouped as Elimination, Target Battle, Killer and TV, then Players and Stats, then Board and Settings.

## [0.8.1] - 2026-10-03

### Changed
- Elimination: `life_lost` is played without the player's name, also when fewer than three darts were detected; `eliminated` still follows the name.

### Fixed
- Announcements are no longer cut off at the start or skipped: the `/audio` page, the TV page and the voice pack preview play through one shared audio context instead of opening a new stream per sound (#18).
- A sound that fails to load or play is reported in the audio page log and the browser console instead of being skipped silently (#18).
- Pages that connect get the current state, including the player list, instead of an older cached copy that could be empty until the next game event.
- A player added, hidden, unhidden or deleted in the Players tab updates the open pages right away.
- Freeplay: a dart outside the board no longer counts its sector number towards the turn total published over MQTT (`autodarts/freeplay/total`, `throw{1,2,3}_value`).
- Freeplay LED display: a missed dart shows `0` instead of `-`, so it can be told apart from a dart not thrown yet (#7).

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
