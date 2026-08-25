"""Counting money must PRINT the value it was given.

The digits are assembled from three CSS counters with literal "," and "."
between them, so an off-by-one in the split shows a plausible wrong number —
exactly the failure mode label-must-match-data exists to catch. These tests
reconstruct what the browser will print and compare it to the figure.
"""
from __future__ import annotations

import re

import pytest

# app.py is the retired Streamlit screen; CI installs no streamlit, so these
# tests skip there instead of failing collection (red CI #84-#90, 2026-08-25)
pytest.importorskip("streamlit")
import app


def _rendered(html: str) -> str:
    """Rebuild the string the browser prints from the seed values + structure."""
    seed = dict(re.findall(r"--(a[wfk]):(-?\d+)", html.split("style='")[1]
                           if "style='" in html else ""))
    m = re.search(r"aria-hidden='true'>([^<]*)<i", html)
    sign = m.group(1) if m else ""
    if "class='k'" in html:                       # k , w3 . f
        return (f"{sign}{int(seed['ak'])},"
                f"{int(seed['aw']):03d}.{int(seed['af']):02d}")
    return f"{sign}{int(seed['aw'])}.{int(seed['af']):02d}"


def _accessible(html: str) -> str:
    """The text a screen reader gets."""
    m = re.search(r"<span class='ani-sr'>([^<]*)</span>", html)
    return m.group(1) if m else ""


@pytest.mark.parametrize("value,sign,expect", [
    (193.50,   False, "193.50"),
    (0.0,      False, "0.00"),
    (0.07,     False, "0.07"),
    (-72.27,   True,  "-72.27"),
    (20.35,    True,  "+20.35"),
    (-30.04,   True,  "-30.04"),
    (1234.56,  False, "1,234.56"),
    (1005.07,  False, "1,005.07"),   # the zero-padding case: not "1,5.7"
    (1000.00,  False, "1,000.00"),
    (999.99,   False, "999.99"),
    (-1234.05, True,  "-1,234.05"),
])
def test_the_digits_print_the_value(value, sign, expect):
    app._ANI_STATE.clear()
    html = app._ani_money(value, key=f"t{value}", sign=sign)
    assert _rendered(html) == expect, html


def test_it_counts_from_the_previous_value_not_from_zero():
    app._ANI_STATE.clear()
    first = app._ani_money(100.00, key="acct")
    # first paint counts up from zero
    assert re.search(r"from\{--aw:0; --af:0\}", first), first
    second = app._ani_money(150.25, key="acct")
    assert re.search(r"from\{--aw:100; --af:0\}", second), second
    assert re.search(r"to\{--aw:150; --af:25\}", second), second


def test_each_key_counts_from_its_own_last_value():
    app._ANI_STATE.clear()
    app._ani_money(10.00, key="a")
    app._ani_money(500.00, key="b")
    a2 = app._ani_money(11.00, key="a")
    assert "from{--aw:10; --af:0}" in a2, "key 'a' must not inherit b's 500"


def test_rounding_never_produces_a_hundred_cents():
    app._ANI_STATE.clear()
    html = app._ani_money(9.999, key="r")
    assert _rendered(html) == "10.00", html


def test_a_huge_figure_is_static_rather_than_wrong():
    app._ANI_STATE.clear()
    html = app._ani_money(1_500_000.25, key="big")
    assert "1,500,000.25" in html and "@keyframes" not in html


def test_none_is_an_em_dash_not_a_zero():
    app._ANI_STATE.clear()
    assert "&mdash;" in app._ani_money(None, key="n")


def test_the_seed_holds_the_final_value_for_reduced_motion():
    """With animation off the inline seed is what shows, so it must be the
    CURRENT figure, never the previous one."""
    app._ANI_STATE.clear()
    app._ani_money(5.00, key="s")
    html = app._ani_money(88.44, key="s")
    seed = html.split("style='")[1].split("'")[0]
    assert seed == "--aw:88;--af:44", seed


def test_ids_are_unique_so_two_figures_cannot_share_a_keyframe():
    app._ANI_STATE.clear()
    a = app._ani_money(1.00, key="x")
    b = app._ani_money(2.00, key="y")
    ida = re.search(r"id='(anm\d+)'", a).group(1)
    idb = re.search(r"id='(anm\d+)'", b).group(1)
    assert ida != idb


def test_the_css_registers_the_properties_and_the_padding_styles():
    css = app.ANI_CSS
    for prop in ("--aw", "--af", "--ak"):
        assert f'@property {prop} {{ syntax:"<integer>"' in css, prop
    assert "@counter-style ani2" in css and "pad:2" in css
    assert "@counter-style ani3" in css and "pad:3" in css
    assert "prefers-reduced-motion" in css


@pytest.mark.parametrize("value,sign,expect", [
    (193.50, False, "193.50"),
    (-72.27, True, "-72.27"),
    (20.35, True, "+20.35"),
    (1005.07, False, "1,005.07"),
])
def test_the_accessible_text_agrees_with_the_printed_digits(value, sign, expect):
    """A CSS counter renders GLYPHS with no text behind them: Chrome's full
    accessibility tree exposed zero of these figures, so a screen reader got
    silence where the balance is. The hidden copy is the accessible value, and
    it must never drift from what the counters print."""
    app._ANI_STATE.clear()
    html = app._ani_money(value, key=f"a{value}", sign=sign)
    assert _accessible(html) == expect
    assert _rendered(html) == expect
    # and the visual half must not be announced a second time
    assert "aria-hidden='true'" in html


def test_the_accessible_copy_is_hidden_visually_but_not_from_the_a11y_tree():
    css = app.ANI_CSS
    assert ".ani-sr" in css
    assert "display:none" not in css.split(".ani-sr")[1].split("}")[0], \
        "display:none would remove it from the accessibility tree as well"
    assert "clip-path:inset(50%)" in css


def test_the_unit_is_inside_the_accessible_text():
    app._ANI_STATE.clear()
    html = app._ani_money(188.58, key="u", unit=" USDT")
    assert _accessible(html) == "188.58 USDT"
