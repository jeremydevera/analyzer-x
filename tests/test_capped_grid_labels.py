"""A capped page must not call its own size "combinations tested".

The streaming fold hands the renderer a bounded selection, so the number in
the provenance line is no longer len(rows). Printing it there would be the
exact failure `label-must-match-data` exists to catch: a true value under a
false caption. On 2026-08-26 a 2-month sweep measured 21,278,772 combinations;
a page capped at 250,000 must say both numbers and name where the rest live.
"""
from tradingagents import backtest_report as br, db_jobs


def _row(coin="AAA", tf="1h", sig="mom6", profit=1.0):
    return {"coin": coin, "tf": tf, "signal": sig, "th": 0.3, "sl": 0.6,
            "tp": 1.8, "sizing": "flat", "profit": profit, "trades": 100,
            "wins": 50, "losses": 50, "winrate": 50.0, "dd": 1.0, "days": 89,
            "bars": 2159, "mon": [1.0], "id": "#AAAAAA", "tpd": 1.1,
            "green": 1, "months": 2, "stop_reachable": True, "gate": "ok"}


def _payload(rows, **kw):
    p = {"rows": rows, "meta": {"AAA|1h": {"bars": 2159, "days": 89, "rt": 0.04,
                                           "liq": 4.0, "fee": 0.0004}},
         "series": {}, "months": ["2026-08"], "cur": "2026-08", "lev": 20,
         "slip": 0.0003, "base": 5.0, "ladder": [1, 1, 2, 2, 4, 4, 8],
         "deployed": [], "excluded": [], "days_asked": 60,
         "fetched": "Aug 26, 2026 7:04am", "reuse": {}}
    p.update(kw)
    return p


def test_the_page_prints_the_measured_total_not_its_own_size():
    html = br.render(_payload([_row()], rows_total=21_278_772, rows_capped=True,
                              row_cap=250_000,
                              grid_path="G:/tradingagents-home/parquet/grids/x.parquet"),
                     title="t")
    assert "21,278,772" in html, "the count is what was MEASURED"
    assert "1</b> most profitable" in html or "1</b> most profitable of" in html, \
        "and the page says how many it is actually showing"
    assert "x.parquet" in html, "and names where every row is kept"


def test_an_uncapped_page_reads_exactly_as_before():
    rows = [_row(profit=1.0), _row(sig="rsi14", profit=2.0)]
    html = br.render(_payload(rows, rows_total=2, rows_capped=False), title="t")
    assert "2 combinations" in html.replace("<b>", "").replace("</b>", "")
    assert "most profitable of" not in html, "nothing was capped, so nothing is claimed"


def test_a_payload_from_an_older_run_still_renders():
    """No rows_total (a pre-streaming payload): fall back to the row count."""
    html = br.render(_payload([_row(), _row(sig="rsi14")]), title="t")
    assert "2 combinations" in html.replace("<b>", "").replace("</b>", "")


def test_the_finished_job_reports_the_measured_total():
    assert db_jobs._measured({"rows": [1, 2, 3], "rows_total": 21_278_772}) == 21_278_772
    assert db_jobs._measured({"rows": [1, 2, 3]}) == 3


def test_persist_results_never_replaces_a_streamed_snapshot():
    """The sink already wrote every row; saving the page's selection over it
    would turn a complete record into a truncated one."""
    calls = []

    class PQ:
        @staticmethod
        def save_grid(rows, *, label, day=None):
            calls.append(len(rows))

    n = db_jobs.persist_results({"rows": [_row()], "rows_total": 21_278_772,
                                 "grid_path": "G:/x.parquet"},
                                days=60, label="pc-2mo", pq=PQ)
    assert calls == [], "the streamed snapshot stands"
    assert n == 21_278_772

    # and with no streamed snapshot (an older caller) it still saves
    n2 = db_jobs.persist_results({"rows": [_row(), _row(sig="rsi14")]},
                                 days=60, label="x", pq=PQ)
    assert calls == [2] and n2 == 2
