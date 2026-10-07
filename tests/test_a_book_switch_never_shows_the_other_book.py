"""The DEMO tab shows the demo book — never a late answer for LIVE.

Operator, Oct 07, 2026: *"why trade histsory is blank for 6B08FF64?"* — the
DEMO tab read "0 on this book" and "No closed trades on the demo book yet"
while #6B08FF64's practice book held 104 closed trades (the newest MDTSTOCK,
SL, -0.77 at 2:07pm). Its real-money book has 0.

Measured in Safari's engine: the six rooms' panels share four request lanes
and each asks again every 5 s whether or not its last read came back, so a
read for the room on screen waited 62 s for a lane — and the LIVE reads queued
before the click on DEMO kept landing after it, painting LIVE's 0 under the
DEMO tab. Two rules, one per half:

* Trade history keeps each answer with the book, page and search it was asked
  for and shows it only while that is still what the panel shows (PnlPanel's
  rule since Sep 27, 2026).
* A read whose exact twin is still WAITING for a lane joins it; once sent, a
  read is never joined (a later read is a new question).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_a_late_answer_for_the_other_book_is_dropped():
    s = _src("webapp/src/components/trade/TradeHistory.tsx")
    load = s[s.index("useLiveRefresh(() => {"):s.index("}, 5_000, [dry, page, q]);")]
    assert "const asked = `${dry}|${page}|${q.trim()}`;" in load
    assert "if (asked !== wantNow.current) return;" in load, "a late answer is dropped"
    assert "setD(" not in s, "no answer reaches the screen without its key"
    assert "const d = got && got.key === want ? got.data : null;" in s
    # what it says while the right answer is on its way: never the other book's count
    assert "reading the ${dry ? \"demo\" : \"live\"} book…" in s


def test_a_new_book_starts_on_page_one_in_the_same_click():
    """The page used to be reset in an effect, after the click had already
    asked for the old page of the new book."""
    s = _src("webapp/src/components/trade/TradeHistory.tsx")
    assert "useEffect(() => { setPage(1); }" not in s
    assert "const pickBook = (v: boolean) => { setDry(v); setPage(1); };" in s
    assert "onClick={() => pickBook(v)}" in s and "onClick={() => setDry(v)}" not in s


def test_a_read_waiting_for_a_lane_is_joined_never_one_already_sent():
    s = _src("webapp/src/lib/api.ts")
    fl = s[s.index("async function fetchLaned"):]
    fl = fl[:fl.index("\n}\n")]
    assert "const twin = same ? _waitingReads.get(same) : undefined;" in fl
    assert "if (twin && twin.gen === gen) return (await twin.p).clone();" in fl, \
        "only a twin of this page, and every reader gets its own copy"
    # the twin is forgotten the moment it leaves the queue (sent or refused)
    after_lane = fl[fl.index("await takeLane(behind, gen, droppable, chrome);"):]
    assert after_lane.index("_waitingReads.delete(same)") < after_lane.index("await fetch(")
    # reads only, never an order; and never across priorities
    assert 'const same = droppable ? `${room} ${behind ? "behind" : "front"} ${input}` : "";' in fl
    assert 'const droppable = method === "GET" && !chrome;' in fl
