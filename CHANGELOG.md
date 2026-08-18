# Changelog

## [Unreleased]

### Added
- DEBUG/INFO logging across the app; config changes log keys, never values.
- Colored log output, opt out with `NO_COLOR`; `LOG_LEVEL` sets the level, also for the updater.

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
