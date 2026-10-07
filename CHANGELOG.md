# Changelog

## [Unreleased]

### Added
- Checkout Trainer on the Play page, with three exercises: Random checkout (a finishable score from 2 to 170 is drawn, up to three darts on the board, in a range, a number of attempts and optionally with the standard route shown, with the next score drawn after a miss), Route quiz (tap the first dart of a route on a virtual board) and Setup shots (tap the darts that set up a finish and see what is left and what it allows). The routes come from a table of the usual checkout chart; any other valid route counts too. The Stats page has a Checkout view with the success rate by range and score and the weakest scores (#32).

### Changed
- Achievements that can be decided during a match (a bullseye, a maximum, a first hit in Killer, ...) are announced as soon as they happen, as provisional, and made final when the match ends; only the ones that need the result (a win, a first match, the counters) come at the end. An undo takes a provisional one back, and a match that is abandoned stores nothing, so a game with many players no longer ends with minutes of banners (#44).

### Fixed
- Achievements earned together in one match are announced one at a time, each with its own banner and sound, one banner length apart; before, the sounds ran back to back while the first banner was still showing (#36).
- Elimination: a dart of the last turn can be corrected after it ended the match; the finished screens show the darts of that turn, tapping one plays the turn again with the corrected dart and resumes the match if it no longer decides it. The correction of a turn total no longer changes the turn before after such a finish (#43).
- A build from source (`npm run build` in `frontend/`) now writes the Web UI to `breakfast/web/dist`, where the server serves it from; before, it landed in `frontend/dist` and a source install showed no or an outdated interface.

## [1.1.0] - 2026-10-07

### Added
- Settings → General → Aurora and glass: speed, intensity and softness of the aurora, the tilted streaks on or off, five ready-made palettes (Northern lights, Ember, Lavender, Graphite, Sakura), the milkiness of the glass panels and how much the top bar covers the page under it, each as a slider with a live preview; and a pause that saves power: the aurora always stops while the page is hidden and, with `aurora_pause_idle`, after some minutes without input. `[web] aurora_palette`, `aurora_streaks`, `aurora_speed`, `aurora_intensity`, `aurora_blur`, `aurora_pause_idle`, `glass_strength`, `bar_opacity`.
- Aurora colors: the same section sets the base color and the three color areas of the background, each with sliders for hue, saturation and brightness (or a hex value), shown at once while picking; `[web] aurora_base`, `aurora_1`, `aurora_2`, `aurora_3`, a color you do not set stays the one of the theme.
- Setting `[web] aurora_animation` (the same section, Animate the background): false lets the aurora in the background stand still, which saves power and heat; it applies at once.
- A standalone Windows version: `breakfast-windows-vX.Y.Z.zip` with `breakfast.exe`, no Python or Docker needed, with its own data folder, a first-start setup in the web UI, an autostart script, `ffmpeg` included, and updates from Settings → Updates with a checksum check and an automatic rollback (#38).
- Windows build: `breakfast.exe` carries a version resource (product name and version) (#38).
- Voice-pack player names live in a private file `data/voicepack/<pack>.toml` that git does not track: the Voice Pack tab saves them there instead of into the plan, and the generator (`--overlay <file>`) and the tab merge them into the plan's "Player names" group (#42).

### Fixed
- Home and `/tv` now apply `[web] theme` and `accent_color` when they load; before, only `/audio` and the Settings page did.

### Changed
- Interface: the footer is gone, the version (five taps unlock the Dev tab) and the link to the About page sit in the sidebar, and the MQTT and Autodarts status sits next to the board status in the top bar; the top bar is nearly opaque, so the page that scrolls under it no longer shows through, and the sidebar and the page background cover the whole page, also in a full-page screenshot.
- Without an Autodarts account in the configuration, `direct` mode starts the web UI only instead of stopping with an error.
- Frontend build dependencies updated (devalue, postcss, source-map-js, nanoid), which closes the security alerts for them.

## [1.0.0] - 2026-10-06

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
