"""An id the Backtest tab cannot find is explained from the app's OWN records.

Oct 13, 2026 12:45pm, the operator: *"still not worked / 2WCGB7VB is existing
in practice, but when i search 2WCGB7VB in backtest tab its not existing"*.
#2WCGB7VB is FASTSTOCK 15m prank, TP 1.5% / SL 1.2% — switched on in nine
rooms and traded in practice from Oct 07, 2026 9:16pm until the move to Gate
on Oct 10, 2026 3:59am. Gate sells 1,038 contracts and FASTSTOCK is not one
of them, so no Gate backtest of it can exist. The tab answered *"no row
#2WCGB7VB in the store ... python -m tradingagents.rows_index resolve
2WCGB7VB says which it is"* — a command, for an id the app had printed itself
one tab over.

A review of the first draft ran it over all 13,141 ids in the rooms' records
and found six sentences that were false on real rows; each has a test here.

Every fixture sits on ONE timeline: the switch at SINCE, the practice run on
MEXC before it.
"""
import json

import pytest

from tradingagents import backtest_report as br, missing_row as mr, venue

SINCE = 1_791_619_184.0                     # Oct 10, 2026 3:59am
ON = SINCE - 4 * 86_400                     # Oct 06, 2026 — switched on (MEXC)
FAST = br.row_code("FASTSTOCK", "15m", "prank", 0, 1.2, 1.5, "flat", res="1m")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    (tmp_path / "venue.json").write_text(json.dumps({"venue": "gate", "since": SINCE}))
    monkeypatch.setattr(venue, "VENUE_FILE", tmp_path / "venue.json")
    for pid in ("55D32617", "6B08FF64"):
        room = tmp_path / "profiles" / pid
        room.mkdir(parents=True)
        _watch(room, {"at": ON, "action": "on", "id": FAST, "coin": "FASTSTOCK",
                      "tf": "15m", "signal": "prank", "tp": 1.5, "sl": 1.2,
                      "why": f"#{FAST} FASTSTOCK 15m prank TP 1.5% / SL 1.2% — 91.79%"})
    for d in ("rows", "state"):
        (tmp_path / "v2" / d).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def no_pay_floor(monkeypatch):
    """The twin and waiting tests below were written before 2:1 after fees
    (Oct 16, 2026) with pairs like 0.4% / 0.3% that can never pay it; they test
    how a twin is found, so the floor is off for them alone."""
    monkeypatch.setattr(br, "PAY_RATIO", 0.0)


def _watch(room, line):
    room.mkdir(parents=True, exist_ok=True)
    with (room / "strategy_watcher.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def _pair(home, coin, tf, rows, last_ms=1_791_905_400_000):
    (home / "v2" / "rows" / f"{coin}-{tf}.json").write_text(json.dumps(rows), encoding="utf-8")
    (home / "v2" / "state" / f"{coin}-{tf}.json").write_text(
        json.dumps({"__cloud__": True, "__last_ms__": last_ms}), encoding="utf-8")


def _row(coin, tf, signal, sl, tp, th=0.0, rt=0.2):
    return {"coin": coin, "tf": tf, "signal": signal, "th": th, "sl": sl, "tp": tp,
            "sizing": "flat", "res": "1m", "trades": 9, "rt": rt}


def _explain(home, code, *, listed=("BTC_USDT",), store_res="1m", kinds=None):
    kinds = kinds or {}
    return mr.explain(code, home=home, store_home=home / "v2", store_res=store_res,
                      listed=lambda: set(listed), id_of=lambda *a: "",
                      kind_of=lambda s: kinds.get(s, "stocks"))


def test_the_operators_id_names_its_coin_and_why_there_is_no_backtest(home):
    assert FAST == "2WCGB7VB"
    got = _explain(home, "#2wcgb7vb")
    assert got["reason"] == "not_listed"
    assert (got["coin"], got["tf"], got["signal"]) == ("FASTSTOCK", "15m", "prank")
    words = got["words"]
    assert words.startswith("#2WCGB7VB is FASTSTOCK 15m prank, TP 1.5% / SL 1.2%")
    assert "Gate does not sell FASTSTOCK" in words
    # the exchange it ran on is DERIVED from when the records say it ran
    assert "2 of your rooms switched it on while the app traded on MEXC" in words
    assert "Oct 06, 2026" in words, "the date, in the one date format"
    assert "python" not in words, "a sentence for the operator, never a command"


def test_a_row_switched_off_after_the_move_still_ran_on_the_old_exchange(home):
    """#2WCGB7VB was switched on Sep 30 - Oct 06 and noted off Oct 10, 2026
    4:51am, after the move: it ran on MEXC, and the note is its last change."""
    _watch(home / "profiles" / "55D32617",
           {"at": SINCE + 3_120, "action": "report", "id": FAST, "coin": "FASTSTOCK",
            "tf": "15m", "signal": "prank", "tp": 1.5, "sl": 1.2})
    words = _explain(home, FAST)["words"]
    assert "while the app traded on MEXC (last change Oct 10, 2026 4:51am)" in words


def test_a_room_that_switched_it_off_did_run_it(home):
    """Review: 160 answers said "named it but never switched it on" for rows
    a room had been running — #7X9R59U8, whose only record in Main is the
    watcher switching it OFF at 87.67%."""
    code = br.row_code("GPNSTOCK", "30m", "prank", 0, 2.0, 2.5, "flat", res="1m")
    _watch(home, {"at": ON, "action": "off", "id": code, "coin": "GPNSTOCK", "tf": "30m",
                  "signal": "prank", "tp": 2.5, "sl": 2.0})
    got = _explain(home, code, listed=())
    assert "#09439DC2 switched it on" in got["words"]
    assert "never switched it on" not in got["words"]


def test_a_room_that_only_refused_it_never_switched_it_on(home):
    room = home / "profiles" / "B52662ED"
    _watch(room, {"at": ON - 86_400, "action": "refused", "id": FAST, "coin": "FASTSTOCK",
                  "tf": "15m", "signal": "prank", "tp": 1.5, "sl": 1.2})
    got = _explain(home, FAST)
    assert got["rooms"] == ["#55D32617", "#6B08FF64"]
    assert "2 of your rooms switched it on" in got["words"]


def test_a_threshold_signal_from_the_watcher_log_is_found(home):
    """Review: the thresholds were tried as fractions (0.002) while ids hash
    the percent (0.2), so 125 fade15 / mom6 ids from the watcher logs got the
    old command message — #M2G8LLDG, FASTSTOCK 15m fade15, among them."""
    code = br.row_code("FASTSTOCK", "15m", "fade15", 0.2, 1.2, 1.5, "flat", res="1m")
    _watch(home / "profiles" / "4FC03172",
           {"at": ON, "action": "on", "id": code, "coin": "FASTSTOCK", "tf": "15m",
            "signal": "fade15", "tp": 1.5, "sl": 1.2})
    got = _explain(home, code)
    assert got["reason"] == "not_listed" and got["signal"] == "fade15"


@pytest.mark.usefixtures("no_pay_floor")
def test_a_stock_the_exchange_sells_under_its_short_name_points_at_that_id(home):
    """MEXC named stocks ABNBSTOCK; Gate names the same stock ABNB (60 of the
    145 stock names the rooms ever switched on, Oct 13, 2026)."""
    twin = br.row_code("FAST", "15m", "prank", 0, 1.2, 1.5, "flat", res="1m")
    _pair(home, "FAST", "15m", [_row("FAST", "15m", "prank", 1.2, 1.5)])
    got = _explain(home, FAST, listed=("FAST_USDT",))
    assert got["reason"] == "listed_as" and got["twin"] == twin
    assert f"Gate sells it as FAST, and the same strategy there is #{twin}" in got["words"]


def test_a_twin_that_is_not_on_the_list_is_never_offered_as_there(home):
    """Review: 1,257 of 1,700 alias answers named a twin the list does not
    hold (#824LGJCY → #WM7RU5VQ, UMC 30m ibs kept only TP 4/5), and searching
    that twin brought back the old command message."""
    _pair(home, "FAST", "15m", [_row("FAST", "15m", "prank", 0.8, 1.5)])
    got = _explain(home, FAST, listed=("FAST_USDT",))
    assert got["reason"] == "listed_as_absent"
    assert "is not on this list either: the backtest measured FAST 15m" in got["words"]
    assert "and the same strategy there is" not in got["words"]


def test_a_crypto_coin_sharing_the_short_name_is_never_the_same_stock(home):
    """Review: QNTSTOCK, OPENSTOCK, DASHSTOCK and CSTOCK were sent to Gate's
    crypto QNT, OPEN, DASH and C — other assets entirely."""
    got = _explain(home, FAST, listed=("FAST_USDT",), kinds={"FAST_USDT": "crypto"})
    assert got["reason"] == "not_listed"
    assert "sells it as" not in got["words"]


def test_an_id_no_record_names_is_left_to_the_old_answer(home):
    assert _explain(home, "ZZZZZZZZ") is None
    assert _explain(home, "not an id") is None


def test_a_coin_the_exchange_sells_but_never_measured(home):
    got = _explain(home, FAST, listed=("FASTSTOCK_USDT",))
    assert got["reason"] == "not_measured"
    assert "has not measured FASTSTOCK 15m yet" in got["words"]


def test_a_pair_measured_with_nothing_kept_is_not_called_unmeasured(home):
    """Review: all 57 "not measured yet" answers were pairs GitHub measured on
    Oct 13, 2026 that kept no row (SHLD 30m: `[]`, candles to 11:30am)."""
    _pair(home, "FASTSTOCK", "15m", [], last_ms=1_791_905_400_000)
    got = _explain(home, FAST, listed=("FASTSTOCK_USDT",))
    assert got["reason"] == "measured_empty"
    assert "measured FASTSTOCK 15m (candles to Oct 13, 2026 11:30am) and kept none" in \
        got["words"]
    assert "yet" not in got["words"]


@pytest.mark.usefixtures("no_pay_floor")
def test_a_measured_row_waiting_for_the_list(home):
    _pair(home, "FASTSTOCK", "15m", [_row("FASTSTOCK", "15m", "prank", 1.2, 1.5)])
    got = _explain(home, FAST, listed=("FASTSTOCK_USDT",))
    assert got["reason"] == "waiting"
    assert "measured and waits to be added to this list" in got["words"]


def test_a_combination_the_cost_line_skips_says_the_cost(home):
    """Review: SFP 15m's round trip is 0.91%, 61% of a 1.5% target — the
    shard skips it (GATE_BLOCK), so "not this signal, TP and SL" hid why."""
    _pair(home, "FASTSTOCK", "15m", [_row("FASTSTOCK", "15m", "prank", 0.8, 2.0, rt=0.9141)])
    got = _explain(home, FAST, listed=("FASTSTOCK_USDT",))
    assert got["reason"] == "cost_skip"
    assert "a round trip on FASTSTOCK costs 0.91%, at least half of its 1.5% target" in \
        got["words"]


def test_a_combination_measured_and_not_kept(home):
    _pair(home, "FASTSTOCK", "15m", [_row("FASTSTOCK", "15m", "prank", 0.8, 1.5)])
    got = _explain(home, FAST, listed=("FASTSTOCK_USDT",))
    assert got["reason"] == "not_kept"


def test_a_barrier_the_grid_never_measures(home):
    code = br.row_code("BTC", "15m", "prank", 0, 1.11, 1.37, "flat", res="1m")
    _watch(home, {"at": SINCE + 60, "action": "on", "id": code, "coin": "BTC", "tf": "15m",
                  "signal": "prank", "tp": 1.37, "sl": 1.11})
    _pair(home, "BTC", "15m", [_row("BTC", "15m", "prank", 0.8, 1.5)])
    got = _explain(home, code)
    assert got["reason"] == "not_in_grid"
    assert "does not measure TP 1.37% / SL 1.11% on 15m" in got["words"]


def test_a_tp_not_bigger_than_sl_is_measured_but_not_listed(home):
    code = br.row_code("BTC", "1h", "trend50", 0, 1.2, 1.2, "flat", res="1m")
    _watch(home / "profiles" / "55D32617",
           {"at": SINCE + 3600, "action": "on", "id": code, "coin": "BTC", "tf": "1h",
            "signal": "trend50", "tp": 1.2, "sl": 1.2})
    got = _explain(home, code, listed=("BTC_USDT",))
    assert got["reason"] == "tp_not_over_sl"
    assert "only strategies whose TP is bigger than their SL" in got["words"]
    assert "Gate" in got["words"] and "MEXC" not in got["words"], \
        "a strategy switched on after the move ran on Gate"


def _v1_case(home):
    v1 = br.row_code("BTC", "1h", "trend50", 0, 0.3, 0.4, "flat")
    (home / "deployments.jsonl").write_text(json.dumps(
        {"changed_at": SINCE + 60, "strategy_key": "trend50_1h_sl03tp04|BTC_USDT",
         "symbol": "—", "action": "deployed"}) + "\n", encoding="utf-8")
    seen = []

    def id_of(key, sym, room):
        seen.append((key, sym, room))
        return v1 if (key, sym) == ("trend50_1h_sl03tp04", "BTC_USDT") else ""

    got = mr.explain(v1, home=home, store_home=home / "v2", store_res="1m",
                     listed=lambda: {"BTC_USDT"}, id_of=id_of, kind_of=lambda s: "crypto",
                     spec_of=lambda key: {"tf": "1h", "signal": "trend50", "tp": 0.4,
                                          "sl": 0.3, "res": ""})
    return got, seen


@pytest.mark.usefixtures("no_pay_floor")
def test_a_v1_id_names_the_same_strategy_on_this_list(home):
    """Review: a switched-off row loses its v2 mark, so the trade history
    prints its v1 hash — #2H8Z7JCP (KII 15m stoch14) was sent to an empty v1
    tab while its v2 row #WTDBZ4N8 sat on this list."""
    twin = br.row_code("BTC", "1h", "trend50", 0, 0.3, 0.4, "flat", res="1m")
    _pair(home, "BTC", "1h", [_row("BTC", "1h", "trend50", 0.3, 0.4)])
    got, seen = _v1_case(home)
    assert ("trend50_1h_sl03tp04", "BTC_USDT", "main") in seen
    assert got["reason"] == "other_store" and got["twin"] == twin
    assert f"this list holds the same strategy as #{twin}" in got["words"]
    # the deploy log spells a switch-on "deployed" (17,042 of them on Oct 13)
    assert "#09439DC2 switched it on while the app traded on Gate" in got["words"]


def test_a_v1_id_whose_v2_twin_is_absent_says_why(home):
    got, _ = _v1_case(home)
    assert got["reason"] == "other_store_absent"
    assert "is not here either: Gate sells BTC, but the backtest has not measured" in \
        got["words"]


def test_an_unreadable_exchange_list_never_claims_a_coin_is_not_sold(home):
    def down():
        raise OSError("no network")

    got = mr.explain(FAST, home=home, store_home=home / "v2", store_res="1m",
                     listed=down, id_of=lambda *a: "")
    assert got["reason"] != "not_listed"
    assert "does not sell" not in got["words"]


def test_the_backtest_routes_carry_the_answer_on_a_miss():
    """Both lists answer an id search through `strategies()`, so the answer
    rides there — and only when the search found nothing."""
    import inspect

    from tradingagents import api

    src = inspect.getsource(api.strategies)
    assert "row_id_why" in src and "missing_row" in src


def test_the_panel_prints_the_answer_before_the_old_one():
    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert "setRowIdWhy(d.row_id_why" in panel
    i = panel.index("{rowIdWhy}")
    j = panel.index("no row <b>#{servedFilters.rowId}</b>")
    assert i < j
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert "row_id_why?:" in client


def _route(monkeypatch, *, rows, total, explained):
    """`api.strategies` with the index and the window re-measure stubbed: the
    row's last 30 days lost money on 5 trades."""
    from tradingagents import api, market_sweep as msw, rows_index as ri

    monkeypatch.setattr(ri, "query", lambda **k: {"rows": [dict(r) for r in rows],
                                                  "total": total})

    def window_rows(rs, days, **k):
        for r in rs:
            r.update(restated=True, w_trades=5, w_wins=1, w_losses=4, w_winrate=20.0,
                     w_profit=-3.0)
        return {"first": "Sep 13, 2026", "last": "Oct 13, 2026", "groups": 1}

    monkeypatch.setattr(msw, "window_rows", window_rows)
    monkeypatch.setattr(api, "index_status", lambda: {})
    monkeypatch.setattr(api, "_screen_note", lambda *a, **k: None)
    monkeypatch.setattr(mr, "explain", lambda *a, **k: explained.append(a) or
                        {"words": "explained"})
    return api.strategies(row_id="46V63K5Z", days=30, profitable=True, min_trades=1000,
                          min_winrate=90)


def test_an_id_search_ignores_the_window_floors_as_its_chip_says(monkeypatch):
    """Review, Oct 13, 2026: #46V63K5Z (KII 15m ibs) IS on the list, but the
    default 30-day window's "made money" floor hid it (total 1, window_hidden
    1, rows 0) — under a chip reading "every other filter ignored" — and the
    miss answer then called it "measured and waits to be added". An id names
    one row; the floors are filters, so an id search shows it."""
    explained: list = []
    row = {"id": "46V63K5Z", "coin": "KII", "tf": "15m", "signal": "ibs", "base": 5.0,
           "trades": 47, "wins": 30, "losses": 17, "winrate": 63.8, "profit": -9.57}
    got = _route(monkeypatch, rows=[row], total=1, explained=explained)
    assert [r["id"] for r in got["rows"]] == ["46V63K5Z"]
    assert got["window_hidden"] == 0
    assert not explained and not got.get("row_id_why"), "it is on the list"


def test_the_miss_answer_runs_only_when_the_list_holds_no_such_row(monkeypatch):
    explained: list = []
    got = _route(monkeypatch, rows=[], total=0, explained=explained)
    assert explained and got["row_id_why"] == "explained"


def test_the_logs_are_read_once_at_start_not_on_the_first_search(home, monkeypatch):
    """Cold, the first answer measured 29 s while the PC was busy (the page
    gives up at 30 s); `warm` fills the cache from the API's startup thread,
    and a search after it reads no log again."""
    import inspect

    from tradingagents import api

    assert mr.warm(home) == 3                           # Main and the two rooms
    reads = []
    real = mr._watch_index
    monkeypatch.setattr(mr, "_watch_index", lambda p: reads.append(p) or real(p))
    assert _explain(home, FAST)["reason"] == "not_listed"
    assert reads == [], "every log came from the cache"
    src = inspect.getsource(api._ids_lose_the_exchange)
    assert "missing_row" in src and "warm" in src and "Thread" in src


def test_a_strategy_under_two_to_one_after_fees_is_never_said_to_be_waiting(home):
    """Oct 16, 2026 ("Backtest list and rooms"): a measured strategy whose win,
    after fees, pays fewer than two losses is never listed. Saying it "waits
    to be added to this list" would be a promise the list never keeps."""
    code = br.row_code("BTC", "1h", "trend50", 0, 0.8, 1.0, "flat", res="1m")
    _watch(home / "profiles" / "55D32617",
           {"at": SINCE + 3600, "action": "on", "id": code, "coin": "BTC", "tf": "1h",
            "signal": "trend50", "tp": 1.0, "sl": 0.8})
    _pair(home, "BTC", "1h", [{**_row("BTC", "1h", "trend50", 0.8, 1.0), "cost_of_tp": 25.0,
                               "gate": "warn"}])
    got = _explain(home, code, listed=("BTC_USDT",))
    assert got["reason"] == "not_two_to_one", got
    assert "after fees" in got["words"] and "+0.75%" in got["words"] and "-1.05%" in got["words"]
    assert "waits to be added" not in got["words"]


def test_a_two_to_one_strategy_not_filed_yet_still_waits(home):
    code = br.row_code("BTC", "1h", "trend50", 0, 1.0, 3.0, "flat", res="1m")
    _watch(home / "profiles" / "55D32617",
           {"at": SINCE + 3600, "action": "on", "id": code, "coin": "BTC", "tf": "1h",
            "signal": "trend50", "tp": 3.0, "sl": 1.0})
    _pair(home, "BTC", "1h", [{**_row("BTC", "1h", "trend50", 1.0, 3.0), "cost_of_tp": 5.0,
                               "gate": "ok"}])
    got = _explain(home, code, listed=("BTC_USDT",))
    assert got["reason"] == "waiting", got
