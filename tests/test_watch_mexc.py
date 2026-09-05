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


@pytest.fixture(autouse=True)
def _no_upcoming_lookup(watcher):
    """Stub the announcement lookup so no unit test reaches the network.

    tick() checks for scheduled listings on every poll; without this a test that
    only cares about new listings would quietly hit the live exchange.
    """
    with patch.object(watcher, "upcoming_listings", return_value=[]):
        yield


def _coin(base="XPLK", hours=0.5):
    return {"symbol": f"{base}USDT", "base": base, "name": f"{base} Coin",
            "contract": "", "first_open_ms": 0, "age_hours": hours,
            "listed_date": "2026-07-30"}


# --- state persistence ----------------------------------------------------


def test_state_round_trips(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT", "BUSDT"})
    assert watcher.load_state(path) == {"AUSDT", "BUSDT"}


# --- heartbeat and status -------------------------------------------------


def test_save_state_records_a_heartbeat(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT"}, now=1_000_000.0)
    raw = json.loads(path.read_text())
    assert raw["last_poll_at"] == 1_000_000.0
    assert raw["polls"] == 1
    assert raw["symbol_count"] == 1


def test_poll_counter_increments_across_saves(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT"}, now=1.0)
    watcher.save_state(path, {"AUSDT", "BUSDT"}, now=2.0)
    raw = json.loads(path.read_text())
    assert raw["polls"] == 2
    assert raw["last_poll_at"] == 2.0


def test_alert_is_recorded_in_state(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT"}, now=5.0, last_alert=[_coin("XPLK")])
    raw = json.loads(path.read_text())
    assert raw["last_alert_at"] == 5.0
    assert raw["last_alert"] == ["XPLK"]


def test_alert_details_survive_a_later_quiet_poll(watcher, tmp_path):
    """A poll with nothing new must not erase the previous alert record."""
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT"}, now=5.0, last_alert=[_coin("XPLK")])
    watcher.save_state(path, {"AUSDT"}, now=9.0)
    raw = json.loads(path.read_text())
    assert raw["last_alert"] == ["XPLK"]
    assert raw["last_alert_at"] == 5.0
    assert raw["last_poll_at"] == 9.0


def test_status_reports_running_when_the_heartbeat_is_recent(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT"}, now=1_000.0)
    status = watcher.status(path, interval=120, now=1_060.0)
    assert status["running"] is True
    assert status["seconds_since_poll"] == pytest.approx(60.0)
    assert status["symbol_count"] == 1


def test_status_reports_stopped_when_the_heartbeat_is_stale(watcher, tmp_path):
    """Missing two intervals means the process is gone, not merely slow."""
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT"}, now=1_000.0)
    status = watcher.status(path, interval=120, now=1_000.0 + 400)
    assert status["running"] is False


def test_status_handles_a_watcher_that_never_ran(watcher, tmp_path):
    status = watcher.status(tmp_path / "absent.json", interval=120, now=10.0)
    assert status["running"] is False
    assert status["last_poll_at"] is None
    assert status["polls"] == 0


def test_format_status_is_human_readable(watcher, tmp_path):
    path = tmp_path / "state.json"
    watcher.save_state(path, {"AUSDT", "BUSDT"}, now=1_000.0,
                       last_alert=[_coin("XPLK")])
    text = watcher.format_status(watcher.status(path, interval=120, now=1_060.0))
    assert "running" in text.lower()
    assert "2" in text                     # symbol count
    assert "XPLK" in text                  # last alert echoed


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


def test_macos_uses_osascript_and_afplay(watcher, monkeypatch):
    """The DECISION, not the machine running the test.

    `afplay` is appended only when the macOS sound file is on disk, so this
    asserted a filesystem fact about the runner: green on a Mac, red on every
    Linux CI box and on the operator's Windows PC. Pointing `_MAC_SOUND` at a
    file that certainly exists tests the branch instead.
    """
    monkeypatch.setattr(watcher, "_MAC_SOUND", __file__)
    cmds = watcher.notify_commands("Darwin", "title", "body", sound=True)
    joined = " ".join(" ".join(c) for c in cmds)
    assert "osascript" in joined
    assert "afplay" in joined


def test_macos_still_notifies_when_the_sound_is_missing(watcher, monkeypatch):
    """A missing sound file must cost the SOUND, never the notification."""
    monkeypatch.setattr(watcher, "_MAC_SOUND", "/nope/not/here.aiff")
    cmds = watcher.notify_commands("Darwin", "title", "body", sound=True)
    joined = " ".join(" ".join(c) for c in cmds)
    assert "osascript" in joined
    assert "afplay" not in joined


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


def test_tick_announces_a_newly_scheduled_listing(watcher, tmp_path):
    """The earliest warning the exchange gives: announced, not yet trading."""
    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    sent = []
    upcoming = [{"symbol": "NATGUSDT", "base": "NATG", "name": "NatGold Digital",
                 "open_ms": 1785409200000, "hours_until": 12.5}]

    with patch.object(watcher, "poll_new_listings", return_value=([], {"OLDUSDT"})), \
         patch.object(watcher, "upcoming_listings", return_value=upcoming), \
         patch.object(watcher, "deliver", side_effect=lambda *a, **k: sent.append(a)):
        watcher.tick(state, max_age_hours=48, sound=True, webhook=None)

    assert sent, "an announcement should have been delivered"
    title, body = sent[0][0], sent[0][1]
    assert "announced" in title.lower()
    assert "NATG" in body
    assert "12.5h" in body or "12h" in body


def test_an_announcement_is_only_delivered_once(watcher, tmp_path):
    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    sent = []
    upcoming = [{"symbol": "NATGUSDT", "base": "NATG", "name": "NatGold",
                 "open_ms": 1785409200000, "hours_until": 12.5}]

    with patch.object(watcher, "poll_new_listings", return_value=([], {"OLDUSDT"})), \
         patch.object(watcher, "upcoming_listings", return_value=upcoming), \
         patch.object(watcher, "deliver", side_effect=lambda *a, **k: sent.append(a)):
        watcher.tick(state, max_age_hours=48, sound=True, webhook=None)
        watcher.tick(state, max_age_hours=48, sound=True, webhook=None)
    assert len(sent) == 1


def test_a_failed_upcoming_lookup_does_not_break_the_tick(watcher, tmp_path):
    from tradingagents.dataflows.mexc import MexcHostUnavailable

    state = tmp_path / "state.json"
    watcher.save_state(state, {"OLDUSDT"})
    with patch.object(watcher, "poll_new_listings", return_value=([], {"OLDUSDT"})), \
         patch.object(watcher, "upcoming_listings",
                      side_effect=MexcHostUnavailable("blocked")):
        assert watcher.tick(state, max_age_hours=48, sound=False, webhook=None) == []


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
