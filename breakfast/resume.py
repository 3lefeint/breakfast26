"""Matches that were in play when the program ended, and the offer to play them on.

The controllers of X01, Elimination and Killer save the match in play after every change (`TurnGameController._save`).
After a start the saved matches wait here. Nothing resumes by itself: the home app offers them, and the player
chooses to resume or to discard.
"""

import logging

log = logging.getLogger(__name__)


def _key(mode):
    return mode.lower()


class ResumeOffers:
    def __init__(self, stats_db, controllers, tournament=None, board_darts=None, on_change=None):
        """*controllers*: {mode: controller} of the games that save their match. *tournament*: takes over the match of
        a running tournament. *board_darts*: tells how many darts are on the board now."""
        self._db = stats_db
        self._controllers = controllers
        self._tournament = tournament
        self._board_darts = board_darts
        self._on_change = on_change
        saved = stats_db.running_matches() if stats_db else {}
        self._pending = {mode: entry for mode, entry in saved.items() if mode in controllers}
        for mode in set(saved) - set(self._pending):
            stats_db.clear_running_match(mode)

    def offers(self):
        """The matches that can be resumed. One that has been replaced by a new game is no longer offered."""
        for mode in [m for m in self._pending if self._controllers[m].game is not None]:
            del self._pending[mode]
        return [{"key": _key(mode), "mode": mode, "saved_at": entry["saved_at"],
                 "players": list(entry["data"].get("players") or []),
                 "tournament": bool(entry["data"].get("tournament_id"))}
                for mode, entry in self._pending.items()]

    def _mode_of(self, key):
        return next((m for m in self._pending if _key(m) == key), None)

    def resume(self, key):
        """Play on the saved match. Returns an error text, None when it went well."""
        mode = self._mode_of(key)
        if mode is None:
            return "no such match to resume"
        if any(c.game is not None for c in self._controllers.values()):
            return "a game is open, cancel it first"
        data = self._pending[mode]["data"]
        controller = self._controllers[mode]
        tournament_id = data.get("tournament_id")
        if tournament_id:
            if not (self._tournament and self._tournament.running and self._tournament.t["id"] == tournament_id):
                self.discard(key)
                return "the tournament of this match is not running any more"
        elif self._tournament and self._tournament.running:
            return "a tournament is running, abort it first"
        del self._pending[mode]
        try:
            game = controller.resume(data, on_end=self._tournament._on_match_end) if tournament_id \
                else controller.resume(data)
        except Exception:
            log.exception("Resuming the %s match failed", mode)
            self._db.clear_running_match(mode)
            return "the match cannot be resumed"
        self._set_board(game)
        if tournament_id and not self._tournament.adopt(game):
            controller.stop()
            return "the match does not belong to the tournament"
        log.info("%s match resumed", mode)
        if self._on_change:
            self._on_change()
        return None

    def discard(self, key):
        mode = self._mode_of(key)
        if mode is None:
            return False
        data = self._pending.pop(mode)["data"]
        self._db.clear_running_match(mode)
        self._db.discard_unfinished(data.get("match_id"))
        if self._on_change:
            self._on_change()
        return True

    def _set_board(self, game):
        """Darts that are on the board now are not new ones of the turn in progress: wait until they are pulled."""
        count = self._board_darts.count() if self._board_darts else 0
        game._board_count = count
        game._await_pull = count > 0
