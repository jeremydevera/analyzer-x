"""Every machine tile says WHICH DATES it is testing, on every report.

Operator, 2026-09-09, looking at twenty machine tiles: *"so why does it not
show what dates its testing like machine 7 Aug 11, 2025 12:00am → Sep 08,
20"*. Machine 7 had dates; the other seventeen did not.

The dates were added the same day (05a092c775b) INSIDE the note, written once
when a pair's candles finished loading. The per-rule note then overwrote it
120 times a pair, and the reporter publishes at most once every 45 seconds, so
a tile showed dates only if its tick happened to land in the instant between
those two lines. Measured on run 34307921614 at 12:46pm: 3 of 20 machines had
dates, 17 did not.

That fix shipped with NO test — three files changed, zero assertions. This
file is that missing guard: the span is its own field, it rides EVERY report
while a pair is being measured, and it is blank exactly when no pair is being
measured.
"""
import ast
import json
from pathlib import Path

import pytest

SHARD = Path(".github/scripts/sweep_shard.py")
PROGRESS = Path(".github/scripts/progress.py")
PANEL = Path("webapp/src/components/backtest/JobsPanel.tsx")
API_TS = Path("webapp/src/lib/api.ts")


def _calls(src: str, name: str) -> list:
    """Every call to `name(...)` in the source, as AST nodes."""
    tree = ast.parse(src)
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == name]


@pytest.fixture
def shard_src():
    return SHARD.read_text(encoding="utf-8")


# ------------------------------------------------------- the emitter
def test_the_reporter_publishes_span_as_its_own_field():
    """Inside `note` it was overwritten by the next note. A separate key
    cannot be."""
    src = PROGRESS.read_text(encoding="utf-8")
    assert "span: str = \"\"" in src, "the reporter must take a span"
    assert '"span": span[:120]' in src, \
        "the span must be published as its own key, not folded into note"


def test_every_report_in_the_shard_passes_a_span(shard_src):
    """THE REGRESSION. One report carried the dates and the rest did not, so
    whichever fired when the 45s window opened decided whether the operator
    saw them. Every call must be explicit — a call that omits `span` silently
    publishes "" and blanks the tile."""
    calls = _calls(shard_src, "report")
    assert len(calls) >= 5, f"expected every report call, found {len(calls)}"
    missing = [c.lineno for c in calls
               if not any(k.arg == "span" for k in c.keywords)]
    assert not missing, (
        f"report(...) at line(s) {missing} does not pass span — the tile will "
        f"lose its dates the moment that call wins the 45-second window")


def test_the_per_rule_report_carries_the_dates(shard_src):
    """The one that fires 120 times a pair — the note the operator almost
    always sees."""
    calls = _calls(shard_src, "report")
    per_rule = [c for c in calls
                if any(isinstance(k.value, ast.JoinedStr)
                       and "rule " in ast.unparse(k.value)
                       for k in c.keywords if k.arg == "note")]
    assert len(per_rule) == 1, "expected exactly one per-rule report"
    span = next(k for k in per_rule[0].keywords if k.arg == "span")
    assert ast.unparse(span.value) == "span", \
        "the per-rule report must send the pair's span, not a literal"


def test_the_span_is_built_from_the_pairs_own_first_and_last_bar(shard_src):
    """Not the run's window: a young coin's history is honestly shorter, and
    the tile must say what THIS pair was tested over."""
    i = shard_src.index("span = (")
    body = shard_src[i:i + 260]
    assert "df['Date'].iloc[0]" in body and "df['Date'].iloc[-1]" in body
    assert "fmt_when(" in body, "the one date formatter (CLAUDE.md), never strftime"
    assert "nbars" in body, "the bar count belongs with the dates"


def test_the_span_is_blank_when_no_pair_is_being_measured(shard_src):
    """A span belongs to a pair under test. Carrying the last one into
    "downloading candles" would print one pair's name beside another pair's
    dates; carrying it into "done" would read as still running."""
    calls = _calls(shard_src, "report")
    for want in ("downloading candles", "pair(s) lost so far"):
        hit = [c for c in calls
               if any(k.arg == "note" and want in ast.unparse(k.value)
                      for k in c.keywords)]
        assert hit, f"no report found for {want!r}"
        span = next(k for k in hit[0].keywords if k.arg == "span")
        assert ast.unparse(span.value) == "''", \
            f"the {want!r} report must CLEAR the span, not carry a stale one"
    done = [c for c in calls
            if c.args and isinstance(c.args[0], ast.Constant)
            and c.args[0].value == "done"]
    assert done, "no 'done' report found"
    span = next(k for k in done[0].keywords if k.arg == "span")
    assert ast.unparse(span.value) == "''", \
        "a finished machine is not testing a span"


def test_the_note_no_longer_carries_the_dates(shard_src):
    """Two homes for one fact is one fact waiting to drift — and the note is
    capped at 120 chars, where the dates crowded out the rule number."""
    notes = [ast.unparse(k.value)
             for c in _calls(shard_src, "report") for k in c.keywords
             if k.arg == "note"]
    for n in notes:
        assert "→" not in n, f"the dates are still inside a note: {n}"


# ------------------------------------------------------------ the panel
def test_the_tile_renders_the_span_on_its_own_line():
    body = PANEL.read_text(encoding="utf-8")
    assert "{sh.span && (" in body, "the tile must render the span"
    i = body.index("{sh.span && (")
    block = body[i:i + 400]
    assert "{sh.span}" in block
    assert "title={sh.span}" in block, "hover shows it in full when truncated"
    # its OWN line: the note's <p> closes before the span's opens
    assert body.index("{sh.stage ?? \"waiting\"}") < i
    assert "</p>" in body[body.index("{sh.stage ?? \"waiting\"}"):i]


def test_a_run_measured_before_this_has_no_span_and_renders_nothing():
    """Older shard files carry no `span` key. `sh.span &&` must swallow
    undefined rather than print it."""
    body = PANEL.read_text(encoding="utf-8")
    assert "{sh.span && (" in body
    assert "sh.span ?? " not in body, \
        "a default would print an empty line for every old run"
    types = API_TS.read_text(encoding="utf-8")
    assert "span?: string;" in types, "optional: old runs do not have it"


def test_the_payload_a_shard_writes_round_trips_to_the_panels_shape():
    """The API passes each shard file through verbatim (cloud_sweep reads the
    JSON and hands it on), so the emitter's keys ARE the panel's props."""
    src = PROGRESS.read_text(encoding="utf-8")
    i = src.index("payload = {")
    payload = src[i:src.index("}", src.index('"updated"'))]
    for key in ("shard", "stage", "done", "total", "rows", "note", "span",
                "days", "failed", "pct", "updated"):
        assert f'"{key}"' in payload, f"{key} missing from the payload"
    types = API_TS.read_text(encoding="utf-8")
    i2 = types.index("export interface CloudShard")
    shape = types[i2:types.index("}", i2)]
    for key in ("shard", "stage", "pct", "note", "done", "total", "rows",
                "days", "span"):
        assert key in shape, f"CloudShard is missing {key}"


def test_the_span_fits_the_publishers_cap():
    """120 chars. The longest real shape must not be truncated mid-date."""
    span = "18,959 bars · Aug 10, 2025 5:00am → Sep 09, 2026 4:00am"
    assert len(span) <= 120
    # and with the longest coin/timeframe this store has seen beside it, the
    # NOTE stays inside its own cap too
    note = "UPROBINHOOD 30m: rule 114/120 (cf_obretest_l2)"
    assert len(note) <= 120


def test_json_dumps_of_a_span_survives_the_base64_write():
    """The reporter base64s json.dumps(payload); the arrow is non-ASCII."""
    import base64

    payload = {"span": "2,369 bars · Aug 10, 2025 8:00am → Sep 09, 2026 12:00am"}
    back = json.loads(base64.b64decode(
        base64.b64encode(json.dumps(payload).encode())).decode())
    assert back["span"] == payload["span"]
