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
    # two since the UPDATE path landed: the full measure and the continuation
    # each report per rule, and each must send the pair's real span
    assert len(per_rule) >= 1, "expected a per-rule report"
    for call in per_rule:
        span = next(k for k in call.keywords if k.arg == "span")
        assert ast.unparse(span.value) == "span", \
            f"line {call.lineno}: the per-rule report must send the pair's span, not a literal"


def test_the_span_is_built_from_the_pairs_own_first_and_last_bar(shard_src):
    """Not the run's window: a young coin's history is honestly shorter, and
    the tile must say what THIS pair was tested over."""
    i = shard_src.index("span, span_ms = _span(df[")
    body = shard_src[i:i + 200]
    assert 'df["Date"].iloc[0]' in body and 'df["Date"].iloc[-1]' in body
    helper = shard_src[shard_src.index("def _span("):][:600]
    assert "fmt_when(" in helper, "the one date formatter (CLAUDE.md), never strftime"
    assert "[a, b]" in helper, "and the same bars as milliseconds for the browser's clock"


def test_the_span_is_dates_only(shard_src):
    """Operator, 2026-09-09: "you only need to show what date are you testing
    like july 18 to sept 9". The bar count moved into the note; the span
    answers exactly one question."""
    i = shard_src.index("span, span_ms = _span(df[")
    body = shard_src[i:shard_src.index("report(", i)]
    assert "nbars" not in body, "the span carries dates, nothing else"
    helper = shard_src[shard_src.index("def _span("):][:600]
    assert "→" in helper
    first_note = shard_src[shard_src.index("report(", i):][:300]
    assert "nbars" in first_note, "the bar count now rides in the note"


# ---------------------------------------------------------- the run header
def test_the_header_says_which_dates_the_whole_run_tests_on_its_own_line():
    """It WAS on screen — as the tail of a grey one-liner — and the operator
    said "i can only see machine loading". Its own line, full size, first
    word "Testing"."""
    body = PANEL.read_text(encoding="utf-8")
    i = body.index("Testing {fmtWhenMs(from)} → {fmtWhenMs(Date.now())}")
    # the whole header block: from where `days` is read to the dates line
    start = body.rindex("const days = cloud.shards.find((s) => s.days)?.days", 0, i)
    block = body[start:i + 900]
    assert "font-semibold" in block, "the dates are the prominent part"
    assert "text-theme-sm" in block, "not the grey xs text it hid in before"
    # derived from the run's own `days`, never a literal date
    assert "(days + 30) * 86400_000" in block, "days+30: the shard's own cut"
    # and the old buried form is gone
    assert "testing {fmtWhenMs(from)} → today (last {days} days)" not in body


def test_the_header_tells_the_truth_about_update_on_the_cloud():
    """This test used to pin the OPPOSITE sentence — "BACKTEST and UPDATE
    both re-measure every bar" — and promised to fail the day the cloud
    learned to continue from a pair's last test. That day was 2026-09-09
    (sweep_shard.continue_pair). Now it pins the new truth: a FULL run says
    "from scratch" and that positions are saved; an UPDATE run says it tests
    only the new candles and counts continued vs measured-in-full."""
    body = PANEL.read_text(encoding="utf-8")
    assert "from scratch (BACKTEST)" in body
    assert "the next UPDATE tests only the new" in body
    assert 'cloud.shards.some((s) => s.mode === "update")' in body
    assert "UPDATE — testing only the new candles since each coin" in body
    # the old lie must not come back in either branch
    assert "UPDATE both re-measure" not in body
    assert "cannot continue from a coin" not in body
    shard = SHARD.read_text(encoding="utf-8")
    assert "def continue_pair(" in shard, "the cloud continues a pair now"
    # a FULL measure still cuts at the run's window, exactly as before
    assert "def window(df):" in shard
    assert "pd.Timedelta(days=DAYS)" in shard
    # THE LEAD-IN IS COUNTED IN BARS, NOT CALENDAR DAYS (Sep 11, 2026). This
    # line pinned `pd.Timedelta(days=DAYS + 30)` — a flat 30-day run-up that
    # scaled with nothing: 2,880 spare bars at 15m and, at 4h, only 180 where
    # a confluence rule needs 200. The rules were blind over the start of
    # their own window and every cloud win rate was overstated (commit
    # 686cfed89dd). A lookback is counted in bars, so the warm-up is too, and
    # the guard must not drag the calendar version back.
    assert "WARMUP_BARS" in shard
    assert "warm = min(WARMUP_BARS, len(df) - len(measured))" in shard
    assert "days=DAYS + 30" not in shard, "the calendar lead-in must not return"


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
    block = body[i:i + 700]
    # the BROWSER's clock, from the bars' milliseconds; the runner's own string
    # (UTC) only for runs measured before span_ms existed (RCA-2026-09-09-S)
    assert "fmtWhenMs(sh.span_ms[0])" in block and "fmtWhenMs(sh.span_ms[1])" in block
    assert ": sh.span" in block, "older runs still show their string"
    assert "title={label}" in block, "hover shows it in full when truncated"
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
                "span_ms", "finished", "board", "days", "failed", "pct",
                "updated"):
        assert f'"{key}"' in payload, f"{key} missing from the payload"
    types = API_TS.read_text(encoding="utf-8")
    i2 = types.index("export interface CloudShard")
    shape = types[i2:types.index("}", i2)]
    for key in ("shard", "stage", "pct", "note", "done", "total", "rows",
                "days", "span", "span_ms", "finished", "board"):
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


# ------------------------------------------- RCA-2026-09-09-S: the 100% bar
# Run 34360893326, Sep 09, 2026 10:03pm: the header read "100.0% 1/1 coins ·
# 0 rows measured · 0/1 machine(s) finished" and the tile "machine 0 100%"
# while the note said "testing · 0G 1h: continuing from …". `done` was the
# coin the machine is ON and `total` the coins it had claimed — the
# one-at-a-time claim board keeps those equal. And the tile's dates were the
# runner's clock (UTC): "12:00pm → 1:00pm" for bars the store on the same PC
# called 8:00pm → 9:00pm.
def _reporter(monkeypatch):
    import importlib.util

    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    monkeypatch.setenv("SHARD", "0")
    spec = importlib.util.spec_from_file_location("progress_pct_test", PROGRESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sent = []
    monkeypatch.setattr(mod, "_req", lambda method, url, token, body=None:
                        sent.append((method, body)) or {"content": {"sha": "x"}})
    return mod.Reporter(every=0), sent


def _payload(sent):
    import base64

    return json.loads(base64.b64decode(sent[-1][1]["content"]).decode())


def test_the_bar_is_not_100_while_the_first_coin_is_still_being_tested(monkeypatch):
    rep, sent = _reporter(monkeypatch)
    rep.board = 2                      # the run holds two coins
    rep.finished = 0                   # none finished yet
    rep("testing", 1, 1, rows=0, note="0G 1h: rule 40/120", span="a → b",
        span_ms=(1788955200000, 1788958800000))
    p = _payload(sent)
    assert p["done"] == p["total"] == 1, "the old fields still say what they said"
    assert p["pct"] == 0.0, "but the bar no longer reads 100% from the first second"
    assert p["finished"] == 0 and p["board"] == 2
    assert p["span_ms"] == [1788955200000, 1788958800000]
    rep.finished = 1
    rep("testing", 2, 2, force=True)
    assert _payload(sent)["pct"] == 50.0
    # no span → no milliseconds either, never a stale pair's dates
    assert _payload(sent)["span_ms"] is None


def test_the_shard_counts_finished_coins_and_the_runs_board():
    src = SHARD.read_text(encoding="utf-8")
    main = src[src.index("def main("):]
    assert "report.board = " in main
    assert main.count("report.finished = done_pairs // len(TFS)") == 2, (
        "after a finished pair AND after a pair given up on")
    # every date span rides as milliseconds too, and none is built by hand
    assert 'span=f"' not in src and 'span = (f"' not in src and 'span = f"' not in src
    assert src.count("span_ms=span_ms") == 5, "each of the five span reports"


def test_the_panel_draws_the_run_from_finished_over_board():
    body = PANEL.read_text(encoding="utf-8")
    assert body.count("runProgress(cloud.shards)") == 2, "the header AND the run bar"
    fn = body[body.index("function runProgress("):]
    fn = fn[:fn.index("\n}")]
    assert "s.finished ?? s.done ?? 0" in fn, "older shard files fall back"
    assert "Math.max(a, s.board ?? 0)" in fn, "the board is one number, never a sum"
    # a machine's tile counts what it finished; its 100% bar is gone
    tile = body[body.index("machine {sh.shard}"):][:600]
    assert "coin(s) done" in tile
    assert "width: `${sh.pct" not in body
