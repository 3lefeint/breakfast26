"""The members of this location and the memberships of this installation at other locations (sharing, #26).

A player becomes a member of a location only by an invitation of its admin; the invitation is a text code. The admin
(behind the PIN of the location) creates a mailbox at the relay for the member (relay/PROTOCOL.md, "Mailboxes"), a random
key for it, and hands the member the invitation: the relay address, the one-time token, the key and the name of the
member. At home *Join a location* redeems it with a device key of its own and stores the membership: the mailbox, the
keys, the direction (pull, push or both) and the local player the member is. No match is sent here, that is the sync.

The members and the memberships are tables of `stats.db`; the keys live in `sharing.json` next to the config file
(mode 600), like the identity of the location.
"""

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from breakfast.locations import LocationError, _b64, _unb64, http_base
from breakfast.names import normalize

log = logging.getLogger(__name__)

CODE_PREFIX = "BFM1-"
DIRECTIONS = ("pull", "push", "both")
MAILBOX = re.compile(r"^[0-9a-f]{32}$")
TIMEOUT_S = 10


def make_member_code(relay, mailbox, token, key, location, player):
    """The invitation of a member as one text."""
    data = {"r": relay, "m": mailbox, "t": token, "k": _b64(key), "l": {"i": location["id"], "n": location["name"]}, "p": player}
    return CODE_PREFIX + _b64(json.dumps(data, separators=(",", ":")).encode())


def read_member_code(code):
    """The invitation text as {relay, mailbox, token, key, location: {id, name}, player}, or a LocationError."""
    code = (code or "").strip()
    try:
        if not code.startswith(CODE_PREFIX):
            raise ValueError
        d = json.loads(_unb64(code[len(CODE_PREFIX):]))
        out = {"relay": d["r"], "mailbox": d["m"], "token": d["t"], "key": _unb64(d["k"]),
               "location": {"id": d["l"]["i"], "name": d["l"]["n"]}, "player": normalize(d["p"])}
        if not (isinstance(out["relay"], str) and out["relay"].startswith(("http://", "https://"))
                and isinstance(out["mailbox"], str) and MAILBOX.match(out["mailbox"])
                and isinstance(out["token"], str) and out["token"]
                and len(out["key"]) == 32 and isinstance(out["location"]["name"], str) and out["player"]):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise LocationError("this is not a member invitation") from None
    return out


def _now():
    return datetime.now(timezone.utc).isoformat()


class Members:
    def __init__(self, locations, db, config_path, post=None):
        """*locations*: this installation as a location (signs the admin's requests), *db*: the StatsDB."""
        self._locations, self._db = locations, db
        self.path = Path(config_path).parent / "sharing.json"
        self._lock = threading.RLock()
        self._post = post or (lambda url, **kw: requests.post(url, timeout=TIMEOUT_S, **kw))

    # ── the file with the keys ────────────────────────────────────────────────

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    # ── the admin: members of this location ───────────────────────────────────

    def status(self):
        """What the settings page shows: whether the first invitation needs the admin's consent, the members, the memberships."""
        with self._lock:
            return {"consent": bool(self._load().get("consent")), "members": self.members(), "subscriptions": self.subscriptions()}

    def members(self):
        with self._db.transaction() as c:
            return [dict(r) for r in c.execute("SELECT mailbox_id, player, created_at, up FROM members ORDER BY created_at")]

    def _local_player(self, name):
        name = normalize(name)
        with self._db.transaction() as c:
            return name if c.execute("SELECT 1 FROM players WHERE name = ? AND guest = 0", (name,)).fetchone() else None

    def invite_member(self, player, pin, confirm=False):
        """Make a local player a member of this location: a mailbox at the relay and the invitation code for him. The
        first invitation needs `confirm`: the admin confirms that the matches of the members, with their co-players, are
        stored. Returns {"mailbox_id", "code", "expires_at"}."""
        with self._lock:
            name = self._local_player(player)
            if name is None:
                raise LocationError("choose a player of this installation")
            data = self._load()
            if not data.get("consent") and not confirm:
                raise LocationError("the admin has to confirm first that the matches of the members are stored")
            with self._db.transaction() as c:
                if c.execute("SELECT 1 FROM members WHERE player = ?", (name,)).fetchone():
                    raise LocationError(f"{name} is a member already")
            made = self._locations.signed(pin, "POST", f"/locations/{self._locations.identity()['id']}/members", {})
            key = secrets.token_bytes(32)
            data["consent"] = True
            data.setdefault("mailboxes", {})[made["mailbox_id"]] = {"key": _b64(key)}
            self._save(data)
            with self._db.transaction() as c:
                c.execute("INSERT INTO members (mailbox_id, player, created_at) VALUES (?, ?, ?)", (made["mailbox_id"], name, _now()))
            ident = self._locations.identity()
            log.info("Members: invited %s, mailbox %s", name, made["mailbox_id"])
            return {"mailbox_id": made["mailbox_id"], "expires_at": made["expires_at"],
                    "code": make_member_code(ident["relay"], made["mailbox_id"], made["token"], key, ident, name)}

    def _member(self, mailbox_id):
        if not MAILBOX.match(str(mailbox_id or "")):
            raise LocationError("unknown member")
        with self._db.transaction() as c:
            row = c.execute("SELECT mailbox_id, player FROM members WHERE mailbox_id = ?", (mailbox_id,)).fetchone()
        if row is None:
            raise LocationError("unknown member")
        return dict(row)

    def reinvite_member(self, mailbox_id, pin):
        """A new invitation for a member who lost his (the same mailbox and key)."""
        with self._lock:
            member = self._member(mailbox_id)
            made = self._locations.signed(pin, "POST", f"/mailboxes/{mailbox_id}/invitations", {})
            key = _unb64(self._load()["mailboxes"][mailbox_id]["key"])
            ident = self._locations.identity()
            log.info("Members: a new invitation for %s", member["player"])
            return {"mailbox_id": mailbox_id, "expires_at": made["expires_at"],
                    "code": make_member_code(ident["relay"], mailbox_id, made["token"], key, ident, member["player"])}

    def remove_member(self, mailbox_id, pin):
        """Block a member: his mailbox is deleted at the relay at once, what his devices already pulled stays with them.
        Nothing is forgotten here while the relay could not be reached."""
        with self._lock:
            member = self._member(mailbox_id)
            self._locations.signed(pin, "DELETE", f"/mailboxes/{mailbox_id}")
            data = self._load()
            data.get("mailboxes", {}).pop(mailbox_id, None)
            self._save(data)
            with self._db.transaction() as c:
                c.execute("DELETE FROM members WHERE mailbox_id = ?", (mailbox_id,))
            log.info("Members: removed %s", member["player"])

    # ── at home: memberships of this installation ─────────────────────────────

    def subscriptions(self):
        with self._db.transaction() as c:
            return [dict(r) for r in c.execute(
                "SELECT mailbox_id, location_id, location_name, direction, player, created_at FROM subscriptions ORDER BY created_at")]

    def preview(self, code):
        """What an invitation is, for the confirmation: the location, the member's name and whether this installation has
        a player of that name (the suggestion; the user always confirms or picks another)."""
        invitation = read_member_code(code)
        return {"location": invitation["location"], "member": invitation["player"],
                "suggested": self._local_player(invitation["player"]), "known": self._known(invitation["mailbox"])}

    def _known(self, mailbox_id):
        with self._db.transaction() as c:
            return bool(c.execute("SELECT 1 FROM subscriptions WHERE mailbox_id = ?", (mailbox_id,)).fetchone())

    def join(self, code, player, direction):
        """Redeem a member invitation: this installation is a member of that location, `player` (a player of this
        installation, created when there is none of that name) is the member, `direction` is pull, push or both."""
        invitation = read_member_code(code)
        if direction not in DIRECTIONS:
            raise LocationError("choose pull, push or both")
        player = normalize(player)
        if not player:
            raise LocationError("choose the player you are at this location")
        with self._lock:
            if self._known(invitation["mailbox"]):
                raise LocationError("you are a member of this location already")
            base = http_base(invitation["relay"])
            device = Ed25519PrivateKey.generate()
            public = _b64(device.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
            raw = json.dumps({"token": invitation["token"], "public_key": public}, separators=(",", ":"))
            timestamp = str(int(time.time()))
            path = "/mailbox-invitations/redeem"
            message = f"POST\n{path}\n{timestamp}\n{hashlib.sha256(raw.encode()).hexdigest()}"
            headers = {"x-timestamp": timestamp, "x-signature": _b64(device.sign(message.encode())), "content-type": "application/json"}
            try:
                res = self._post(base + path, data=raw.encode(), headers=headers)
            except requests.RequestException as e:
                raise LocationError(f"the relay is not reachable: {e}") from None
            try:
                answer = res.json()
            except ValueError:
                answer = {}
            if res.status_code >= 400:
                raise LocationError(str(answer.get("error") or f"the relay answered {res.status_code}"))
            self._db.upsert_player(player)
            data = self._load()
            data.setdefault("devices", {})[answer["mailbox_id"]] = {
                "key": _b64(invitation["key"]),
                "device_key": _b64(device.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))}
            self._save(data)
            with self._db.transaction() as c:
                c.execute("INSERT INTO subscriptions (mailbox_id, relay, location_id, location_name, device_id, direction, player, created_at)"
                          " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (answer["mailbox_id"], base, answer["location"]["id"], answer["location"]["name"], answer["device_id"],
                           direction, player, _now()))
            log.info("Members: joined %s as %s (%s)", answer["location"]["name"], player, direction)
            return {"mailbox_id": answer["mailbox_id"], "location": answer["location"], "direction": direction, "player": player}

    def leave(self, mailbox_id):
        """Stop being a member here: the membership and its keys are forgotten on this installation. What it already pulled
        stays; the location removes the mailbox."""
        if not MAILBOX.match(str(mailbox_id or "")):
            raise LocationError("unknown membership")
        with self._lock:
            if not self._known(mailbox_id):
                raise LocationError("unknown membership")
            data = self._load()
            data.get("devices", {}).pop(mailbox_id, None)
            self._save(data)
            with self._db.transaction() as c:
                c.execute("DELETE FROM subscriptions WHERE mailbox_id = ?", (mailbox_id,))
            log.info("Members: left %s", mailbox_id)
