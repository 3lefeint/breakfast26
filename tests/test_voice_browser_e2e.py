"""Two real browsers (Chromium with a fake microphone) join the voice chat of a match on a relay under `wrangler dev`
and must end up with a connected WebRTC link and audio arriving. Skipped without Playwright and its Chromium."""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

sync_api = pytest.importorskip("playwright.sync_api")

from breakfast.elimination import EliminationController
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.online import OnlineSession
from breakfast.stats import StatsDB

RELAY = Path(__file__).resolve().parents[1] / "relay"
WRANGLER = RELAY / "node_modules" / ".bin" / "wrangler"

pytestmark = pytest.mark.skipif(
    not WRANGLER.exists() or not shutil.which("node"),
    reason="needs `npm install` in relay/ and node")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def relay(tmp_path_factory):
    port = _free_port()
    state = tmp_path_factory.mktemp("wrangler-state")
    proc = subprocess.Popen(
        [str(WRANGLER), "dev", "--port", str(port), "--ip", "127.0.0.1", "--persist-to", str(state)],
        cwd=RELAY, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                if requests.get(f"http://127.0.0.1:{port}/", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("wrangler dev did not come up")
        yield f"127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _session():
    ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=StatsDB(":memory:"))
    return OnlineSession(ctrl)


def _until(page, expression, timeout=20):
    """Poll `expression` in the page. (`wait_for_function` evaluates a string, which the page's own policy forbids.)"""
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(expression):
            return
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {expression}")


def test_two_browsers_hear_each_other(relay):
    host, guest = _session(), _session()
    code = host.create(f"ws://{relay}", "Home", "pw")
    guest.join(f"ws://{relay}", code, "Club", "pw")
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
            except Exception as e:
                pytest.skip(f"no Chromium for Playwright: {e}")
            context = browser.new_context(permissions=["microphone"])
            pages = []
            for session in (host, guest):
                page = context.new_page()
                page.goto(session.voice_url("en"))
                page.click("#join")
                page.wait_for_selector("#mute:not([disabled])", timeout=15000)
                pages.append(page)
            for page in pages:
                _until(page, "() => Object.values(window.__voice.peers).some(p => p.pc.connectionState === 'connected')")
            for page in pages:
                received = page.evaluate("""async () => {
                    const peer = Object.values(window.__voice.peers)[0];
                    const first = await peer.pc.getStats();
                    let bytes = 0;
                    first.forEach(r => { if (r.type === 'inbound-rtp' && r.kind === 'audio') bytes = r.bytesReceived; });
                    return bytes;
                }""")
                assert received > 0
            assert pages[0].locator("#peers li").count() == 2 and "Club" in pages[0].locator("#peers").inner_text()
            pages[1].click("#mute")
            _until(pages[0], "() => document.querySelector('#peers').innerText.includes('muted')", 5)
            pages[1].click("#leave")
            _until(pages[0], "() => document.querySelector('#peers').innerText.includes('Nobody')", 10)
            browser.close()
    finally:
        host.leave(); guest.leave()
