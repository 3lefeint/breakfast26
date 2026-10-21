"""This installation as a location at the relay: its identity, the admin PIN, invitations and links.

A location is registered once at the relay with an Ed25519 key; every later request is signed with it
(see relay/PROTOCOL.md, "Locations"). Two locations are linked through a one-time invitation code. The
identity, the PIN check value and the PIN lock live in `location.json` next to `config.toml`; removing the
`pin` entry from that file resets a forgotten PIN.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

log = logging.getLogger(__name__)

TIMEOUT_S = 10
NAME_MAX = 24
PIN_DIGITS = (4, 8)
PIN_ITERATIONS = 200_000
LOCK_FIRST_TRIES = 3         # wrong PINs before the first lock, 2 before each later one
LOCK_LATER_TRIES = 2
LOCK_FIRST_S = 60
LOCK_LATER_S = 300
CODE_PREFIX = "BF1-"


class LocationError(Exception):
    """Something the user has to be told: wrong PIN, no relay, an invalid invitation, ..."""


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def http_base(relay_url):
    """The https/http address of a relay given as wss:// or ws:// (or already https)."""
    url = (relay_url or "").strip().rstrip("/")
    for ws, http in (("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(ws):
            return http + url[len(ws):]
    return url


def make_code(relay_url, token):
    """The invitation as one text: the relay it belongs to and the one-time token."""
    return CODE_PREFIX + _b64(json.dumps({"r": relay_url, "t": token}, separators=(",", ":")).encode())


def read_code(code):
    """(relay http address, token) of an invitation text, or a LocationError."""
    code = (code or "").strip()
    try:
        if not code.startswith(CODE_PREFIX):
            raise ValueError
        data = json.loads(_unb64(code[len(CODE_PREFIX):]))
        relay, token = data["r"], data["t"]
        if not (isinstance(relay, str) and isinstance(token, str) and relay.startswith(("http://", "https://"))):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise LocationError("this is not an invitation code") from None
    return relay, token


def _pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITERATIONS)


class Locations:
    def __init__(self, config_path, post=None, get=None, delete=None, patch=None, now=time.time):
        self.path = Path(config_path).parent / "location.json"
        self._now = now
        self._lock = threading.RLock()
        self._post = post or (lambda url, **kw: requests.post(url, timeout=TIMEOUT_S, **kw))
        self._get = get or (lambda url, **kw: requests.get(url, timeout=TIMEOUT_S, **kw))
        self._delete = delete or (lambda url, **kw: requests.delete(url, timeout=TIMEOUT_S, **kw))
        self._patch = patch or (lambda url, **kw: requests.patch(url, timeout=TIMEOUT_S, **kw))

    # ── the file ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, state):
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp, self.path)

    def status(self):
        state = self._load()
        return {"registered": "id" in state, "id": state.get("id"), "name": state.get("name"),
                "relay": state.get("relay"), "pin_set": "pin" in state}

    # ── the PIN ───────────────────────────────────────────────────────────────

    def _check_pin(self, state, pin):
        """Raises unless `pin` is right; counts wrong tries and applies the lock."""
        if "pin" not in state:
            raise LocationError("no PIN is set; set one first")
        lock = state.setdefault("lock", {"fails": 0, "locks": 0, "until": 0})
        wait = lock["until"] - self._now()
        if wait > 0:
            raise LocationError(f"too many wrong PINs, try again in {int(wait) + 1} s")
        stored = state["pin"]
        good = hmac.compare_digest(_pin_hash(str(pin or ""), _unb64(stored["salt"])), _unb64(stored["hash"]))
        if good:
            lock.update(fails=0, locks=0, until=0)
            return
        lock["fails"] += 1
        if lock["fails"] >= (LOCK_FIRST_TRIES if lock["locks"] == 0 else LOCK_LATER_TRIES):
            lock["locks"] += 1
            lock["fails"] = 0
            lock["until"] = self._now() + (LOCK_FIRST_S if lock["locks"] == 1 else LOCK_LATER_S)
        self._save(state)
        raise LocationError("wrong PIN")

    @staticmethod
    def _valid_pin(pin):
        pin = str(pin or "")
        if not (pin.isascii() and pin.isdigit() and PIN_DIGITS[0] <= len(pin) <= PIN_DIGITS[1]):
            raise LocationError(f"the PIN is {PIN_DIGITS[0]} to {PIN_DIGITS[1]} digits")
        return pin

    def _set_pin(self, state, pin):
        salt = secrets.token_bytes(16)
        state["pin"] = {"salt": _b64(salt), "hash": _b64(_pin_hash(self._valid_pin(pin), salt))}
        state["lock"] = {"fails": 0, "locks": 0, "until": 0}

    # ── requests to the relay ─────────────────────────────────────────────────

    def _headers(self, state, method, path, raw):
        """The headers that sign a request to the relay (the signature covers method, path, time and body)."""
        timestamp = str(int(self._now()))
        message = f"{method}\n{path}\n{timestamp}\n{hashlib.sha256(raw.encode()).hexdigest()}"
        key = Ed25519PrivateKey.from_private_bytes(_unb64(state["key"]))
        return {"x-location": state["id"], "x-timestamp": timestamp, "x-signature": _b64(key.sign(message.encode()))}

    def _signed(self, state, method, base, path, body=None):
        raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers = self._headers(state, method, path, raw)
        if raw:
            headers["content-type"] = "application/json"
        fn = {"POST": self._post, "GET": self._get, "DELETE": self._delete, "PATCH": self._patch}[method]
        return self._answer(fn, base + path, data=raw.encode() if raw else None, headers=headers)

    def signer_for(self, relay_url):
        """`sign(method, path, raw) -> headers` for requests of this location to `relay_url`, or None when this
        installation is not registered there."""
        state = self._load()
        if "id" not in state or state.get("relay") != http_base(relay_url):
            return None
        return lambda method, path, raw: self._headers(state, method, path, raw)

    @staticmethod
    def _answer(fn, url, **kw):
        try:
            res = fn(url, **kw)
        except requests.RequestException as e:
            log.warning("Locations: %s is not reachable: %s", url, e)
            raise LocationError(f"the relay is not reachable: {e}") from None
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code >= 400:
            message = str(data.get("error") or f"the relay answered {res.status_code}")
            log.warning("Locations: %s answered %s: %s", url, res.status_code, message)
            raise LocationError(message)
        return data

    def _registered(self):
        state = self._load()
        if "id" not in state:
            raise LocationError("register this location first")
        return state

    # ── commands ──────────────────────────────────────────────────────────────

    def register(self, relay_url, name, pin):
        """Create the identity, set the PIN and register at the relay."""
        with self._lock:
            if "id" in self._load():
                raise LocationError("this location is registered already")
            name = (name or "").strip()
            if not name or len(name) > NAME_MAX:
                raise LocationError(f"give this location a name of 1 to {NAME_MAX} characters")
            base = http_base(relay_url)
            if not base:
                raise LocationError("set the relay address in Settings first")
            state = {"relay": base, "name": name}
            self._set_pin(state, pin)
            key = Ed25519PrivateKey.generate()
            public = _b64(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
            body = {"name": name, "public_key": public}
            raw = json.dumps(body, separators=(",", ":"))
            timestamp = str(int(self._now()))
            message = f"POST\n/locations\n{timestamp}\n{hashlib.sha256(raw.encode()).hexdigest()}"
            headers = {"x-timestamp": timestamp, "x-signature": _b64(key.sign(message.encode())), "content-type": "application/json"}
            data = self._answer(self._post, base + "/locations", data=raw.encode(), headers=headers)
            state["id"] = data["id"]
            log.info("Locations: registered as %s at %s", state["id"], base)
            state["key"] = _b64(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
            self._save(state)
            return self.status()

    def set_pin(self, pin):
        """Set a new PIN; only possible while none is set (after its entry was removed from the file)."""
        with self._lock:
            state = self._registered()
            if "pin" in state:
                raise LocationError("a PIN is set already")
            self._set_pin(state, pin)
            self._save(state)

    def change_pin(self, pin, new_pin):
        """Replace the PIN by a new one; needs the current PIN."""
        with self._lock:
            state = self._registered()
            self._check_pin(state, pin)
            self._save(state)
            self._set_pin(state, new_pin)
            self._save(state)
            log.info("Locations: the PIN was changed")

    def rename(self, name, pin):
        """Change the name of this location; its id and links stay."""
        with self._lock:
            state = self._registered()
            self._check_pin(state, pin)
            self._save(state)
            name = (name or "").strip()
            if not name or len(name) > NAME_MAX:
                raise LocationError(f"give this location a name of 1 to {NAME_MAX} characters")
            self._signed(state, "PATCH", state["relay"], f"/locations/{state['id']}", {"name": name})
            state["name"] = name
            self._save(state)
            log.info("Locations: renamed %s", state["id"])
            return self.status()

    def unregister(self, pin):
        """Delete this location and its links at the relay, then forget the identity here. Nothing is
        forgotten here while the relay could not be reached."""
        with self._lock:
            state = self._registered()
            self._check_pin(state, pin)
            self._save(state)
            self._signed(state, "DELETE", state["relay"], f"/locations/{state['id']}")
            self.path.unlink(missing_ok=True)
            log.info("Locations: signed off %s", state["id"])

    def invite(self, pin):
        """A one-time invitation code for another location."""
        with self._lock:
            state = self._registered()
            self._check_pin(state, pin)
            self._save(state)
            data = self._signed(state, "POST", state["relay"], f"/locations/{state['id']}/invitations", {})
            log.info("Locations: invitation created")
            return make_code(state["relay"], data["token"])

    def join(self, code, pin):
        """Redeem an invitation code: this location and the one that issued it are linked."""
        with self._lock:
            state = self._registered()
            self._check_pin(state, pin)
            self._save(state)
            relay, token = read_code(code)
            if http_base(relay) != state["relay"]:
                raise LocationError("this invitation is for another relay")
            data = self._signed(state, "POST", state["relay"], "/invitations/redeem", {"token": token})
            log.info("Locations: linked with %s", data["peer"]["id"])
            return {"link_id": data["link_id"], "peer": data["peer"]}

    def links(self):
        """The links of this location as the relay knows them."""
        with self._lock:
            state = self._registered()
            return self._signed(state, "GET", state["relay"], f"/locations/{state['id']}/links")["links"]

    def open_matches(self):
        """The open online matches of the linked locations (fetched when asked, not kept)."""
        with self._lock:
            state = self._registered()
            return self._signed(state, "GET", state["relay"], f"/locations/{state['id']}/open-matches")["matches"]

    def join_ticket(self, code):
        """A one-time ticket to join the open match `code` of a linked location without its password."""
        with self._lock:
            state = self._registered()
            data = self._signed(state, "POST", state["relay"], f"/locations/{state['id']}/join-ticket", {"code": str(code).strip().upper()})
            log.info("Locations: joining the match %s of a linked location", data.get("code"))
            return data["ticket"]

    def unlink(self, link_id, pin):
        with self._lock:
            if not re.fullmatch(r"[0-9a-f]{32}", str(link_id or "")):
                raise LocationError("unknown link")
            state = self._registered()
            self._check_pin(state, pin)
            self._save(state)
            self._signed(state, "DELETE", state["relay"], f"/links/{link_id}")
            log.info("Locations: link %s removed", link_id)
