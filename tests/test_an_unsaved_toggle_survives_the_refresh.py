"""Clicking LIVE went back by itself, five seconds later.

Operator, `Sep 13, 2026`: *"WHEN I CLICK LIVE TOGGLE OFF IT GOES BACK ON
WHY?"*, then — correcting a first answer that blamed the save step —
*"MY ISSUE IS WHEN I CLICK LIVE BUTTON IT GOES ON IMMEDIATELY BEFORE CLICKING
SAVE BUTTON"*.

Driven in a real browser against the running app, both halves measured:

    t = 7 ms      aria-checked -> true      (the pill goes red at once)
    t = 3,016 ms  aria-checked -> true
    t = 6,015 ms  aria-checked -> FALSE     <- the draft is gone
    non-GET requests in that window: 0

So there were two facts, and they pull opposite ways:

* the pill arms INSTANTLY on screen, which reads as "this is live now" — it
  is not; zero writes left the browser and the runner only ever reads the
  file on disk;
* five seconds later `useLiveRefresh(load, 5_000)` overwrote the draft with
  what is on disk, and `setDirty(false)` took the "unsaved changes" warning
  with it, so nothing was left to say a click had been lost.

Reaching SAVE CONFIG was a race against a timer nobody could see.

The poll itself is not the bug and is not removed — it exists because a live
stop-loss on PSXSTOCK at `Sep 10, 2026 8:04pm` left the win rate stale
(*"i want the ui realtime when i lose it should show the winrate lose"*). The
rule is narrower: **a refresh owns the numbers that MOVE; the operator owns
the fields they can type in.**

After the fix, same browser, same page: on at 11 ms, still on at 6 s, 12 s
and 18 s; 27 polls landed in 11 seconds while the draft stood; DISCARD put it
back; 0 writes throughout.
"""
from __future__ import annotations

import pathlib
import re

import pytest

GRID = pathlib.Path("webapp/src/components/trade/StrategiesGrid.tsx")


@pytest.fixture(scope="module")
def src() -> str:
    return GRID.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def load_body(src) -> str:
    """Just `load`, so an assertion about it cannot be satisfied by some other
    function that happens to contain the same call."""
    i = src.index("const load = useCallback(")
    return src[i:src.index("[catalog]);", i)]


# ------------------------------------------- 1. the refresh keeps its hands off
def test_a_refresh_does_not_clear_the_unsaved_flag(load_body):
    """`setDirty(false)` inside the poll is the whole bug: it discarded the
    edit AND the warning that an edit existed."""
    assert "setDirty(false)" not in load_body, (
        "the 5 s poll clears the operator's unsaved-changes flag")


def test_the_editable_fields_are_preserved_while_a_draft_stands(load_body):
    """books / coins / base_margin are what the grid lets you change. They are
    carried over from the previous rows when a draft is pending; everything
    else on the row is taken fresh from the server."""
    assert "const pending = dirtyRef.current;" in load_body
    assert "if (!pending) return row;" in load_body
    for field in ("books", "coins", "base_margin"):
        assert re.search(rf"{field}: mine\.{field}", load_body), field
    # the settings object the SAVE button sends must not be replaced either
    assert "if (!pending) {" in load_body
    assert "setSettings(se.settings);" in load_body
    i = load_body.index("if (!pending) {")
    assert load_body.index("setSettings(se.settings);") > i, \
        "setSettings must sit inside the not-pending branch"


def test_the_moving_numbers_still_land_every_poll(load_body):
    """The reason this poll exists. None of these is typeable, so a refresh
    owning them cannot lose an edit — and the operator asked for them to be
    realtime after a live stop went unnoticed."""
    for always in ("setCounts(st)", "setLocks(st.locks)", "setAcctCap(",
                   "setCapHit(", "setConflicts(st.conflicts)"):
        assert always in load_body, always
    # rows are re-taken from the server every time; only the editable fields
    # of a pending draft are carried across
    assert "st.rows.map((row)" in load_body


def test_it_reads_a_ref_not_the_state(src):
    """`load` is the poll's dependency. Reading `dirty` state inside it would
    rebuild the callback on every keystroke and restart the interval."""
    assert "const dirtyRef = useRef(false);" in src
    assert "dirtyRef.current = true;" in src, "an edit has to set it"


# ------------------------------------------------ 2. the screen tells the truth
def test_the_banner_says_the_runner_is_still_on_the_saved_config(src):
    """A red pill read as "armed". The words have to carry what the colour
    cannot: nothing is live until SAVE CONFIG writes the file."""
    assert "unsaved — the runner is still on the saved config" in src


def test_a_draft_can_be_thrown_away(src):
    """The poll used to do this by accident; now it must be deliberate, or a
    draft the operator changed their mind about has no way out."""
    i = src.index("unsaved — the runner is still on the saved config")
    near = src[i:i + 900]
    assert ">\n                discard\n              </button>" in near or \
        "discard" in near, "no discard control beside the unsaved notice"
    assert "dirtyRef.current = false; setDirty(false); setNote(\"\"); load();" in src


# --------------------------------------------- 3. a click still arms nothing
def test_toggling_a_book_writes_nothing_to_the_server(src):
    """Measured: 0 non-GET requests in the 6 s after a click. The toggle edits
    local state; only `save` posts, and it confirms first."""
    i = src.index("const toggleBook =")
    body = src[i:src.index("const setMargin =", i)]
    for call in ("tradeApi.", "api.", "fetch("):
        assert call not in body, f"toggleBook talks to the server via {call}"
    assert "mut((s) =>" in body


def test_only_save_posts_the_config(src):
    assert src.count("tradeApi.settingsSave(") == 1
    i = src.index("const save = async ()")
    body = src[i:src.index("tradeApi.settingsSave(", i)]
    assert "confirm(" in body, "a real-money save is confirmed first"


def test_a_refused_save_keeps_the_draft(src):
    """A 409 from the live-lock guard leaves the file unchanged. Wiping the
    edit there would be the same disappearing click, one layer along."""
    i = src.index("const save = async ()")
    body = src[i:i + 2400]
    catch = body[body.index("} catch (e) {"):]
    assert "dirtyRef.current = false" not in catch, \
        "a refused save must not throw the operator's edit away"
    assert "NOT saved" in catch
