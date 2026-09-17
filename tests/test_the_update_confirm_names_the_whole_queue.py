"""UPDATE CANDLES names the WHOLE queue it starts (docs/RCA.md RCA-2026-09-17-E).

An update tops up every stored pair AND fetches every pair the venue lists
that the store has never had (`db_jobs.pending_work` → stale + missing). On
Candles v2 the store held 5 pairs, the confirm said "Update 5 stored pair(s)?
... nothing is downloaded again", and the job it started queued 1,003 pairs
of 30-day one-minute history (`Sep 17, 2026 10:17pm`).

The number a button prints is the number of work it will DO
(RCA-2026-09-10-C, second fault). These tests read the WORDS of the confirm,
because the screen has no rows to assert on.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "webapp/src/components/candles/DownloadScreen.tsx"


def _update_handler() -> str:
    src = SRC.read_text(encoding="utf-8")
    i = src.index("const update = async")
    j = src.index('api.jobStart("download", { mode: "update" })', i)
    return src[i:j]


def test_the_confirm_counts_the_never_stored_pairs_too():
    frag = _update_handler()
    assert "confirm(" in frag, "a multi-hour download is confirmed first"
    assert "pending?.missing" in frag, \
        "the never-stored count comes from the pending route, never a literal"
    assert "fetched in full" in frag, "and says those pairs are whole downloads"


def test_the_confirm_has_no_hardcoded_duration():
    # 113 pairs took 30 minutes on Sep 17, 2026 — a typed "about 1.5 hours"
    # for 1,003 would have been a number nobody measured (label-must-match-data).
    frag = _update_handler()
    assert not re.search(r"\d+(\.\d+)?\s*(hours?|minutes?|mins?)\b", frag), frag


def test_the_field_the_confirm_reads_is_one_the_route_returns():
    api_ts = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    i = api_ts.index("export type CandlePending = {")
    j = api_ts.index("};", i)
    assert "missing: number" in api_ts[i:j], \
        "`missing` must be a field of the pending route's answer, not a guess"
    assert "get<CandlePending>" in api_ts[api_ts.index("candlePending:"):], \
        "and candlePending must be typed with it, on both stores"
