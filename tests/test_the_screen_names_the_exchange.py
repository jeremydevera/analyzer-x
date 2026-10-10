"""The screen names the exchange the app trades (spec D13, Oct 10, 2026).

After the move to Gate a page that still says "MEXC" is a label that does not
match its data — the failure CLAUDE.md's label-must-match-data rule exists
for. The name comes from ONE answer, `/api/venue`, and no component spells
an exchange itself.
"""
import re
from pathlib import Path

from starlette.testclient import TestClient

from tradingagents import api

ROOT = Path(__file__).resolve().parents[1]


def test_the_api_names_the_exchange(monkeypatch):
    c = TestClient(api.app)
    monkeypatch.setenv("TA_VENUE", "gate")
    assert c.get("/api/venue").json() == {"venue": "gate", "name": "Gate"}
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert c.get("/api/venue").json() == {"venue": "mexc", "name": "MEXC"}


def _visible_text(src: str) -> str:
    """The parts of a .tsx file a person can read on screen: string literals
    and JSX text, with every comment removed first."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    return src


def test_no_component_spells_mexc_on_screen():
    bad = []
    for p in (ROOT / "webapp" / "src").rglob("*.tsx"):
        text = _visible_text(p.read_text(encoding="utf-8"))
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\bMEXC\b", line):
                bad.append(f"{p.relative_to(ROOT).as_posix()}: {line.strip()[:100]}")
    assert not bad, "say the exchange's name from useVenueName():\n" + "\n".join(bad)
