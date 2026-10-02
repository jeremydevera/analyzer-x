"""The operator's one date format, held across the browser and Python.

This file used to exec app.py, the retired Streamlit screen, for most of its
tests. app.py was removed on Oct 02, 2026 with the New Crypto, Analysis and
LLM Models screens ("remove the new crypto, analysis and llm models completly,
i will not use them anymore"); the date-format guards CLAUDE.md names by test
name never read it, so they stay here unchanged.
"""

import pytest

pytestmark = pytest.mark.unit


def test_the_browser_uses_one_date_format_everywhere():
    """`Aug 22, 2026 4:00PM`, the format the operator asked for twice.

    Python keeps it in positions_view.fmt_when. The browser had NO shared
    formatter, so six components each called toLocaleString() and rendered
    `8/22/2026, 4:00:00 PM` — a different format on every screen the API did
    not pre-format, including the runner's own job panel.
    """
    import pathlib
    import re

    src = pathlib.Path("webapp/src")
    offenders = []
    for f in list(src.rglob("*.tsx")) + list(src.rglob("*.ts")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"new Date\([^)]*\)\.toLocale", line):
                offenders.append(f"{f}:{i}")
    assert not offenders, (
        "these format a date in the browser instead of using fmtWhen:\n  "
        + "\n  ".join(offenders))

    api = (src / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "export function fmtWhenMs" in api and "export const fmtWhen" in api


def test_the_two_date_formatters_agree(tmp_path):
    """One in Python, one in TypeScript. They must not drift — the whole point
    is that a stamp reads the same wherever it is drawn."""
    import datetime as dt
    import json
    import shutil
    import subprocess

    from tradingagents.positions_view import fmt_when

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node is not installed")

    cases = [dt.datetime(2026, 8, 22, 0, 5), dt.datetime(2026, 8, 22, 12, 0),
             dt.datetime(2026, 8, 22, 23, 59), dt.datetime(2026, 1, 1, 9, 30),
             dt.datetime(2026, 12, 31, 13, 7)]
    stamps = [c.timestamp() for c in cases]

    js = tmp_path / "p.mjs"
    api = "webapp/src/lib/api.ts"
    body = open(api, encoding="utf-8").read()
    start = body.index("const MONTHS")
    end = body.index("export const fmtWhen =")
    # lift the real implementation, not a copy of it
    lifted = (body[start:end].replace("export function", "function")
              .replace(": number | undefined | null", "")
              # fmtLeft (between MONTHS and fmtWhen since the rebuild ETA
              # work) spells the same type the other way round, and node
              # refused the whole file — so this guard of the MANDATORY date
              # format was red and proving nothing
              .replace(": number | null | undefined", "")
              .replace(": string", ""))
    js.write_text(lifted + "\nconsole.log(JSON.stringify("
                  + json.dumps(stamps) + ".map(s => fmtWhenMs(s * 1000))));\n")
    out = subprocess.run([node, str(js)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [fmt_when(s) for s in stamps]


def test_python_has_one_date_formatter_not_two():
    """market_sweep.fmt_stamp was a line-for-line copy of
    positions_view.fmt_when. Two copies of one rule is one rule waiting to
    drift, and this rule is "the operator asked for it twice"."""
    import inspect

    from tradingagents import market_sweep as msw, positions_view as pv

    src = inspect.getsource(msw.fmt_stamp)
    assert "fmt_when" in src, "fmt_stamp must delegate, not reimplement"
    assert "%b" not in src, "it is still formatting on its own"
    for ts in (1787371208, 1787326445.6, 0.0):
        assert msw.fmt_stamp(ts) == pv.fmt_when(ts)


def test_the_date_format_is_exactly_what_the_operator_asked_for():
    """`Aug 03, 2026 8:03pm`, given three times. Each part was wrong once:
    the day was unpadded, the meridiem was uppercase, and two API routes had
    hand-rolled copies with a `.replace(" 0", " ")` hack for a padded hour."""
    import datetime as dt

    from tradingagents.positions_view import fmt_when

    cases = {
        dt.datetime(2026, 8, 3, 20, 3): "Aug 03, 2026 8:03pm",
        dt.datetime(2026, 8, 22, 0, 5): "Aug 22, 2026 12:05am",
        dt.datetime(2026, 8, 22, 12, 0): "Aug 22, 2026 12:00pm",
        dt.datetime(2026, 1, 9, 9, 30): "Jan 09, 2026 9:30am",
        dt.datetime(2026, 12, 31, 13, 7): "Dec 31, 2026 1:07pm",
        dt.datetime(2026, 11, 5, 23, 59): "Nov 05, 2026 11:59pm",
    }
    for when, want in cases.items():
        assert fmt_when(when.timestamp()) == want, (
            f"{when} -> {fmt_when(when.timestamp())!r}, wanted {want!r}")


def test_no_module_formats_a_timestamp_by_hand():
    """Two API routes each had their own `%b %d, %Y %I:%M%p` plus a
    `.replace(" 0", " ")` to undo the padded hour. A copy is a rule that
    drifts, and this rule has now changed twice."""
    import pathlib

    offenders = []
    for f in pathlib.Path("tradingagents").rglob("*.py"):
        if f.name == "positions_view.py":
            continue                    # the one place it is allowed
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            # PARSING someone else's format (strptime) is fine — Twitter
            # sends what it sends. Only PRODUCING a stamp is the rule.
            # And a MONTH label ("Aug 2026") is not a timestamp: no clock
            # part, and the monthly columns are meant to read that way.
            if "strptime" in line:
                continue
            if "%b" in line and "%Y" in line and ("%M" in line or "%H" in line):
                offenders.append(f"{f}:{i}")
    # A GUARD IS ONLY AS WIDE AS ITS PATTERN (Sep 12, 2026). The rule above
    # wants `%b` and `%Y` and a clock part ON ONE LINE. `market_sweep
    # .candle_coverage` broke it and passed for weeks, because it spelled the
    # date with ATTRIBUTES instead of codes and spread it over two lines:
    #
    #     "first": f"{_d0:%b} {_d0.day}, {_d0.year}",
    #     "last": (f"{_d1:%b} {_d1.day}, {_d1.year} "
    #              f"{_h1}:{_d1:%M}{_d1:%p}"),
    #
    # `%Y` never appears, so neither line matched — and the Storage screen
    # printed `Sep 3, 2026 3:07PM`: unpadded day, uppercase PM, two of the
    # six parts wrong. So the check is repeated over the WHOLE FILE with the
    # attribute spellings counted as their codes.
    for f in pathlib.Path("tradingagents").rglob("*.py"):
        if f.name == "positions_view.py":
            continue
        src = f.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            if "strptime" in line:
                continue
            # a month code beside a hand-built day or year, in one f-string
            if "%b" in line and (".day}" in line or ".year}" in line):
                offenders.append(f"{f}:{i} (a date spelled with attributes)")
            # `%p` is uppercase AM/PM and there is no lowercase strftime code:
            # producing one at all means the rule is being re-implemented
            if "%p}" in line or '"%p"' in line or "'%p'" in line:
                offenders.append(f"{f}:{i} (%p is uppercase; the rule is not)")
    assert not offenders, ("hand-rolled date formats:\n  "
                           + "\n  ".join(sorted(set(offenders))))


def test_log_lines_carry_the_operator_date_format_too():
    """The Runner feed shows raw log lines, so `%(asctime)s` is a date on the
    operator's screen. basicConfig's default is `2026-08-22 19:27:03,488` —
    the exact compact stamp the rule bans, on every row. Fixing the message
    content but not the line's own timestamp is why this was asked a fourth
    time."""
    import io
    import logging

    from tradingagents.positions_view import WhenFormatter, fmt_when

    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(WhenFormatter("%(asctime)s %(levelname)s %(message)s"))
    lg = logging.getLogger("fmt-probe")
    lg.handlers[:] = [h]
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.info("scan PI_USDT")

    line = buf.getvalue().strip()
    assert " INFO scan PI_USDT" in line
    stamp = line.split(" INFO ")[0]
    import re

    assert re.fullmatch(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m", stamp), \
        f"log stamp is {stamp!r}"
    # and it is the SAME function, not another copy: the record's own creation
    # time, run through fmt_when, must reproduce the line exactly
    rec = logging.LogRecord("fmt-probe", logging.INFO, __file__, 1, "x", None, None)
    assert WhenFormatter().formatTime(rec) == fmt_when(rec.created)


def test_no_logger_is_configured_with_a_bare_asctime():
    """Every place that configures logging must set WhenFormatter, or that
    logger prints ISO stamps into a feed the operator reads."""
    import pathlib

    bad = []
    for f in [pathlib.Path("spx_bot.py"), *pathlib.Path("tradingagents").rglob("*.py")]:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        if "%(asctime)s" in text and "WhenFormatter" not in text:
            bad.append(str(f))
    assert not bad, ("these log ISO timestamps into an operator-facing log:\n  "
                     + "\n  ".join(bad))
