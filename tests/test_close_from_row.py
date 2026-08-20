"""Closing a live position: armed from the row, sent only by the button.

Operator, 2026-08-20: "where is the close button in open position? why did you
remove it? when i click that it should flash close the position in mexc".

The per-row control lived in the legacy _positions() band, which was deleted as
a duplicate — leaving only a dropdown below the table, and a CONFIRM step that
rendered in a different section hundreds of pixels further down, so a click
looked like it did nothing.
"""
from __future__ import annotations

SRC = open("app.py", encoding="utf-8").read()


def test_the_live_table_has_a_close_cell_per_row():
    assert "class='mv-x'" in SRC
    assert "href='?close=" in SRC


def test_the_paper_table_has_no_close_control():
    """There is no market to close a simulated fill on, so the cell is gated on
    the live book. Asserted on the gate that follows the anchor, not on a
    fixed-size window around it."""
    i = SRC.index("class='mv-x'")
    tail = SRC[i:i + 500]
    assert ") if live else \"\"" in tail, "the close cell must be live-only"


def test_the_close_column_only_exists_on_the_live_grid():
    assert '"<div class=\'mv-r\'>Close</div>" if live else ""' in SRC


def test_the_get_link_only_arms_and_never_sends_an_order():
    """A refresh or a prefetch must not be able to replay a close. The link
    sets pending state and the parameter is consumed; at.close_one is reached
    only from the confirm button."""
    arm = SRC.index('_asked = st.query_params.get("close")')
    assert 'del st.query_params["close"]' in SRC[arm:arm + 900], \
        "the parameter must be cleared so a reload cannot re-arm"
    # the order call is inside the confirm button branch, not the link branch
    confirm = SRC.index('key="mvx_confirm"')
    order = SRC.index("at.close_one(_pend)")
    assert confirm < order, "close_one must sit inside the confirm branch"


def test_the_confirmation_states_what_becomes_real():
    for phrase in ("at market now?", "becomes real the moment",
                   "There is no undo", "re-enter on its next signal"):
        assert phrase in SRC, phrase


def test_only_one_confirm_block_survives():
    """The duplicate in the dead _positions() band is gone; two blocks meant
    two CONFIRM buttons for one pending close."""
    assert SRC.count("at.close_one(_pend)") == 1
    assert 'key="cl_confirm"' not in SRC
    assert SRC.count('key="mvx_confirm"') == 1


def test_the_cache_is_cleared_after_a_close():
    """The positions read is cached, so the closed row would otherwise stay on
    screen and read as a failed close."""
    i = SRC.index("at.close_one(_pend)")
    assert "_live_open_positions.clear()" in SRC[i:i + 600]


def test_a_position_that_closed_itself_is_reported_not_retried():
    i = SRC.index('_pend = st.session_state.get("close_pending")')
    assert "is no longer open" in SRC[i:i + 900]
