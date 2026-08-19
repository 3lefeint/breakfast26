# Changelog

## [Unreleased]

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
