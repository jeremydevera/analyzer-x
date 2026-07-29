"""Unit tests for the background new-listing watcher (no network, no sound)."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "watch_mexc.py"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def watcher():
    spec = importlib.util.spec_from_file_location("watch_mexc", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["watch_mexc"] = mod
    spec.loader.exec_module(mod)
    return mod


def _coin(base="XPLK", hours=0.5):
    return {"symbol": f"{base}USDT", "base": base, "name": f"{base} Coin",
            "contract": "", "first_open_ms": 0, "age_hours": hours,
            "listed_date": "2026-07-30"}


# --- state persistence ----------------------------------------------------


def test_state_round_trips(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT", "BUSDT"})
    assert watcher.load_state(path) == {"AUSDT", "BUSDT"}


def test_missing_state_reads_as_empty(watcher, tmp_path):
    assert watcher.load_state(tmp_path / "absent.json") == set()


def test_corrupt_state_reads_as_empty(watcher, tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert watcher.load_state(path) == set()


def test_state_survives_an_unwritable_path(watcher, tmp_path):
    """A failed save must not kill a long-running watcher."""
    watcher.save_state(tmp_path / "no-such-dir" / "state.json", {"AUSDT"})


# --- alert text -----------------------------------------------------------


def test_alert_lines_name_the_coin_age_and_symbol(watcher):
    title, body = watcher.alert_text([_coin("XPLK", 0.5)])
    assert "1 new" in title
    assert "XPLK" in body
    assert "XPLK Coin" in body


def test_alert_text_summarises_several_coins(watcher):
    title, body = watcher.alert_text([_coin("A", 1), _coin("B", 2)])
    assert "2 new" in title
    assert "A" in body and "B" in body


# --- notifier selection ---------------------------------------------------


def test_macos_uses_osascript_and_afplay(watcher):
    cmds = watcher.notify_commands("Darwin", "title", "body", sound=True)
    joined = " ".join(" ".join(c) for c in cmds)
    assert "osascript" in joined
    assert "afplay" in joined


def test_linux_uses_notify_send(watcher):
    cmds = watcher.notify_commands("Linux", "title", "body", sound=True)
    joined = " ".join(" ".join(c) for c in cmds)
    assert "notify-send" in joined


def test_sound_can_be_switched_off(watcher):
    cmds = watcher.notify_commands("Darwin", "t", "b", sound=False)
    assert all("afplay" not in " ".join(c) for c in cmds)


def test_unknown_platform_degrades_to_no_commands(watcher):
    assert watcher.notify_commands("Plan9", "t", "b", sound=True) == []


# --- one poll iteration ---------------------------------------------------


def test_tick_alerts_and_persists(watcher, tmp_path):
    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    sent = []

    with patch.object(watcher, "poll_new_listings",
                      return_value=([_coin()], {"OLDUSDT", "XPLKUSDT"})), \
         patch.object(watcher, "deliver", side_effect=lambda *a, **k: sent.append(a)):
        found = watcher.tick(state, max_age_hours=48, sound=True, webhook=None)

    assert [c["base"] for c in found] == ["XPLK"]
    assert sent, "an alert should have been delivered"
    assert watcher.load_state(state) == {"OLDUSDT", "XPLKUSDT"}


def test_tick_stays_silent_when_nothing_is_new(watcher, tmp_path):
    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    sent = []
    with patch.object(watcher, "poll_new_listings",
                      return_value=([], {"OLDUSDT"})), \
         patch.object(watcher, "deliver", side_effect=lambda *a, **k: sent.append(a)):
        found = watcher.tick(state, max_age_hours=48, sound=True, webhook=None)
    assert found == []
    assert sent == []


def test_tick_survives_a_mexc_outage(watcher, tmp_path):
    """A blocked host must not end the loop."""
    from tradingagents.dataflows.mexc import MexcUnavailable

    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    with patch.object(watcher, "poll_new_listings",
                      side_effect=MexcUnavailable("all hosts blocked")):
        assert watcher.tick(state, max_age_hours=48, sound=False, webhook=None) == []
    assert watcher.load_state(state) == {"OLDUSDT"}      # baseline untouched


def test_webhook_payload_shape(watcher, tmp_path):
    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    posted = {}

    def fake_post(url, payload):
        posted["url"] = url
        posted["payload"] = payload

    with patch.object(watcher, "poll_new_listings",
                      return_value=([_coin()], {"OLDUSDT", "XPLKUSDT"})), \
         patch.object(watcher, "notify_commands", return_value=[]), \
         patch.object(watcher, "post_webhook", side_effect=fake_post):
        watcher.tick(state, max_age_hours=48, sound=False,
                     webhook="https://example.test/hook")

    assert posted["url"] == "https://example.test/hook"
    assert posted["payload"]["count"] == 1
    assert posted["payload"]["coins"][0]["base"] == "XPLK"
    json.dumps(posted["payload"])          # must be serialisable
