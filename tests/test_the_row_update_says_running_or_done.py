"""UPDATE THIS BACKTEST says RUNNING (with a spinner) or DONE (with the time).

RCA-2026-09-24-K. The operator pressed it on #AJX2ZPQX (CAKE 1h zscore20) and
read, in green, "CAKE 1h · zscore20: 200 row(s), 220 indexed" — the finished
job's log line, word for word — and asked *"is it loading or done because if
its loading i already told you do a loading animation"*. It had finished at
Sep 24, 2026 11:41pm. While a job ran, the button only changed its word to
"UPDATING…", against the Sep 23 ask for an animation on everything loading.

The finished sentence is built in `webapp/src/lib/rowUpdate.ts`, which has no
imports so this test runs THAT file under node (type stripping) — the words
checked here are the words the screen prints.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "webapp/src/components/backtest/StrategiesPanel.tsx"
SENTENCE = REPO / "webapp/src/lib/rowUpdate.ts"
WHEN = "Sep 24, 2026 11:41pm"

CASES = {
    "done": {"pair": "CAKE 1h", "signal": "zscore20", "rows": 200, "indexed": 220},
    "current": {"pair": "CAKE 1h", "signal": "zscore20", "rows": 0,
                "indexed": 220, "already_current": True},
    "queued": {"pair": "CAKE 1h", "rows": 200, "index_error": "database is locked",
               "index_queued": True},
    "unfiled": {"pair": "CAKE 1h", "rows": 200, "index_error": "disk I/O error"},
    "failed": {"pair": "CAKE 1h", "error": "RuntimeError: no Min60 candles"},
}


@pytest.fixture(scope="module")
def said(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("ru") / "probe.mjs"
    probe.write_text(
        f'import {{ rowUpdateSentence }} from "{SENTENCE.as_uri()}";\n'
        f"const cases = {json.dumps(CASES)};\n"
        "const out = {};\n"
        f'for (const [k, j] of Object.entries(cases)) out[k] = rowUpdateSentence(j, "{WHEN}");\n'
        "console.log(JSON.stringify(out));\n", encoding="utf-8")
    got = subprocess.run([node, str(probe)], capture_output=True, text=True,
                         encoding="utf-8")  # node prints UTF-8; the "—" must survive
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_a_finished_update_says_done_and_when(said):
    """SHORT (operator, Sep 25, 2026: "i just want short if its done then
    show 100% done finished at (speficic date and time)"); the counts are
    still derived from the job, on hover (`detail`)."""
    t = said["done"]["text"]
    assert t == f"100% done — finished at {WHEN}", t
    d = said["done"]["detail"]
    assert "200 strategies" in d and "CAKE 1h zscore20" in d, d
    assert said["done"]["bad"] is False


def test_no_programmer_words_on_screen(said):
    """"row(s)" and "indexed" are the log line's words, not the operator's."""
    for k, v in said.items():
        assert "row(s)" not in v["text"] and "indexed" not in v["text"], (k, v)


def test_nothing_new_is_said_as_nothing_new(said):
    t = said["current"]["text"]
    assert t == f"100% done — finished at {WHEN} · no new candles", t
    assert "already up to date" in said["current"]["detail"].lower()


def test_every_ending_carries_the_time(said):
    for k, v in said.items():
        assert WHEN in v["text"], (k, v)


def test_a_failure_is_red_and_a_queue_is_not(said):
    assert said["failed"]["bad"] and said["unfiled"]["bad"]
    assert not said["queued"]["bad"], "queued is a wait, not a failure"
    assert "shows in the table shortly" in said["queued"]["text"]
    assert "next in line" in said["queued"]["detail"]


def test_a_finished_line_stays_short(said):
    """No ending that worked runs past one short line — the cost note and the
    counts are on hover. The failures keep their reason: a broken job may
    not read "100% done"."""
    for k in ("done", "current", "queued"):
        assert said[k]["text"].startswith("100% done — finished at"), (k, said[k])
        assert len(said[k]["text"]) <= 80, (k, said[k]["text"])
    for k in ("failed", "unfiled"):
        assert "100% done" not in said[k]["text"], (k, said[k])


def _running_branch(src: str) -> str:
    i = src.index("pairJob?.running && !jobIsThisRow ? (")
    return src[i:src.index("pairJob?.note && jobIsThisRow", i)]


def test_the_running_state_has_a_moving_spinner():
    src = PANEL.read_text(encoding="utf-8")
    btn = src[src.index("onClick={() => updateRow(open.id)}"):]
    btn = btn[:btn.index("</button>")]
    assert "animate-spin" in btn and "UPDATING…" in btn, \
        "the button must spin while THIS row's update runs"
    branch = _running_branch(src)
    assert branch.count("animate-spin") >= 2, \
        "both running lines (this row, another row first) spin"


def test_the_finished_state_is_the_sentence_never_the_raw_note():
    src = PANEL.read_text(encoding="utf-8")
    i = src.index("pairJob?.note && jobIsThisRow")
    tail = src[i:i + 1400]
    assert "rowUpdateSentence(" in tail and "fmtWhen(pairJob.finished)" in tail
    assert not re.search(r"\{\s*pairJob\.error\s*\?\?\s*pairJob\.note\s*\}", tail), \
        "the raw log line must not be printed as the finished label"


def test_the_job_publishes_what_the_sentence_needs():
    """The final write overwrote the file without the signal, and "no new
    bars" existed only inside the free-text note."""
    import inspect

    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_pairbt)
    # the SUCCESS write (it carries `indexed`); the error path writes its own earlier
    final = src[src.index("_pub(running=False, rows=n_rows, indexed=indexed"):]
    final = final[:final.index(")\n")]
    assert "signal=signal" in final and "already_current=" in final, final


# --- RCA-2026-09-25-B: found by pressing it for real after the fix above ----
# The first seconds of a pressed update read "undefined is being re-measured
# first — one row at a time" on the very row that was pressed, and the button
# did not spin: `db_jobs.start` wrote {"running": True, "now": "starting"}
# with no `pair`, and the job process takes a few seconds to publish one.

def test_the_first_status_names_the_pair_it_is_for():
    from tradingagents import db_jobs as dj

    got = dj._first_progress({"coin": "CAKE", "tf": "1h", "signal": "zscore20",
                              "days": 30})
    assert got["running"] is True and got["now"] == "starting"
    assert got["pair"] == "CAKE 1h" and got["signal"] == "zscore20", got
    assert dj._first_progress({"coin": "CAKE_USDT", "tf": "1h"})["pair"] == "CAKE 1h"


def test_a_job_about_no_single_pair_gets_no_pair():
    """A market-wide job must not claim to be about one coin."""
    from tradingagents import db_jobs as dj

    got = dj._first_progress({"coins": ["CAKE", "XPIN"], "mode": "update"})
    assert "pair" not in got and got["mode"] == "update"


def test_start_writes_that_first_status():
    import inspect

    from tradingagents import db_jobs as dj

    assert "_write_progress(f[\"progress\"], _first_progress(spec))" in inspect.getsource(dj.start)


def test_the_screen_never_prints_an_unnamed_pair():
    src = PANEL.read_text(encoding="utf-8")
    unnamed = src.index("pairJob?.running && !pairJob.pair ? (")
    other = src.index("pairJob?.running && !jobIsThisRow ? (")
    assert unnamed < other, "the 'not named yet' case must be caught first"
    assert "starting…" in src[unnamed:other]
