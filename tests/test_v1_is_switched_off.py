"""v1 is switched off — but nothing about it is deleted.

The operator, three times in three days (docs/OPERATOR-ASKS.md):

* `Sep 22, 2026` — *"fuck you, stop the v1 now and start the v2 who said to
  start v1?"*
* `Sep 24, 2026` — *"stop the v1 i dont need it anymore"*
* `Sep 24, 2026` — *"disable candles v1 and backtest v1 since i already have
  backtestv2 and candles v2"*

WHAT IS OFF: starting the three market-wide v1 jobs, and offering v1 anywhere
on the nav.

WHAT IS NOT, and each for a measured reason:

* **the v1 data.** v1 holds a year of history; v2 holds thirty days, because
  MEXC sells ~30 days of 1-minute candles.
* **every v1 READ path.** All **97** of their armed strategy/coin pairs were
  chosen from v1 rows — `settings["strategy_res"]` marks not one as v2 — so a
  live trade's `#id` still has to resolve.
* **`collect`**, or a v1 run already in flight could never land.
* **`pairbt` / `stratbt`**, which re-measure ONE row a person is watching.
  With all 97 armed rows coming from v1, re-checking one by hand is the last
  thing to take away.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from tradingagents import db_jobs as dj

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("kind", ["download", "backtest", "btupdate"])
def test_the_three_v1_market_jobs_are_refused_at_the_route(kind):
    """409 with the reason, from the door the screen knocks on."""
    from fastapi.testclient import TestClient

    from tradingagents import api as api_mod

    r = TestClient(api_mod.app).post(f"/api/jobs/{kind}/start", json={})
    assert r.status_code == 409, r.text
    why = r.json()["detail"]
    assert "v1 is switched off" in why
    assert "Backtest v2" in why, "a refusal must name what to use instead"
    assert "not deleted" in why, "and say their results are still there"


@pytest.mark.parametrize("kind", ["download", "backtest", "btupdate"])
def test_the_LIBRARY_can_still_start_one(kind):
    """THE PART THAT BIT. Putting this refusal inside `db_jobs.start` broke
    thirteen tests and every one was right: `start("download")` is how the
    one-disk rule is exercised (a v2 job must wait for a v1 job and the other
    way round), how `resume_if_died` is driven, and how several v2 tests set
    up the v1 job they need to contend with. The machinery is shared and still
    exists — only ASKING for it from the screen is switched off."""
    assert dj.v1_off_why(kind), "the list must still name it"
    src = inspect.getsource(dj.start)
    assert "V1_OFF" not in src and "v1_off_why" not in src,         "the refusal crept back into the shared library"


@pytest.mark.parametrize("kind", ["collect", "pairbt", "stratbt",
                                  "download_v2", "backtest_v2", "btupdate_v2",
                                  "collect_v2"])
def test_everything_else_is_untouched(kind):
    """Refusing too much is the way this breaks. `collect` lands a v1 run
    already in flight; `pairbt`/`stratbt` re-measure the ONE row a person is
    looking at, and all 97 armed rows are v1 ones."""
    assert kind not in dj.V1_OFF, f"{kind} must still be startable"


def test_the_nav_offers_no_v1_screen():
    """Both names stay — the operator still has a Candles and a Backtest tab —
    but each points at the v2 page."""
    nav = (REPO / "webapp" / "src" / "layout" / "AppSidebar.tsx").read_text(
        encoding="utf-8")
    block = nav[:nav.index("New Crypto")]
    assert '"/candles-v2"' in block and '"/backtest-v2"' in block
    assert '    path: "/candles",' not in block, "v1 candles is still on the nav"
    assert '    path: "/backtest",' not in block, "v1 backtest is still on the nav"


def test_the_v1_pages_and_routes_still_ANSWER():
    """Switched off is not deleted. The pages exist and the API still serves
    v1, because 97 armed strategies point into that store."""
    for page in ("backtest", "candles"):
        assert (REPO / "webapp" / "src" / "app" / "(admin)" / page
                / "page.tsx").exists(), f"/{page} was deleted, not disabled"


def test_a_refused_v1_job_is_409_and_not_a_crash():
    """A 500 reads as a broken app and sends them to the logs. Nothing is
    broken — the job was switched off on purpose."""
    from tradingagents import api

    src = inspect.getsource(api)
    assert src.count("db_jobs.V1Off") + src.count("dj.V1Off") >= 3, \
        "every start() caller must turn V1Off into its 409, not a 500"
