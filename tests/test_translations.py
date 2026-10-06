"""Every text passed to t() in the frontend has a German translation."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"
CALL = re.compile(r"""\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`([^`$]*)`)""")
ENTRY = re.compile(r"""^\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*:""", re.M)


def _unescape(text):
    return re.sub(r"\\(.)", r"\1", text)


def _used():
    used = {}
    for path in list(SRC.rglob("*.svelte")) + list(SRC.rglob("*.js")):
        if path.parent.name == "locales":
            continue
        for m in CALL.finditer(path.read_text(encoding="utf-8")):
            text = _unescape(next(g for g in m.groups() if g is not None))
            used.setdefault(text, path.relative_to(SRC))
    return used


def _german():
    source = (SRC / "lib" / "locales" / "de.js").read_text(encoding="utf-8")
    return {_unescape(next(g for g in m.groups() if g is not None)) for m in ENTRY.finditer(source)}


def test_every_used_text_is_translated():
    german = _german()
    missing = {text: str(path) for text, path in _used().items() if text not in german}
    assert not missing, f"missing German translations: {missing}"


def _backend_texts():
    """Messages the backend sends and the frontend translates with t(res.error)."""
    source = (SRC.parents[1] / "breakfast" / "web" / "server.py").read_text(encoding="utf-8")
    return set(re.findall(r'"error": "([^"]+)"', source))


def test_no_unused_german_entries():
    used = set(_used()) | _backend_texts()
    unused = sorted(text for text in _german() if text not in used)
    assert not unused, f"German entries no code uses: {unused}"
