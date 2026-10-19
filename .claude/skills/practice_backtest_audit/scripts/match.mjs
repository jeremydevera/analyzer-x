// practice_backtest_audit's matching rules, kept apart from the browser so
// tests/test_practice_backtest_audit.py runs the very functions the audit
// runs. Pure: no screen, no files.

export const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Oct 13, 2026 7:15pm" (this PC's local time, as every screen prints it). */
export function parseWhen(s) {
  const m = /([A-Z][a-z]{2}) (\d{1,2}), (\d{4})(?: (\d{1,2}):(\d{2})(am|pm))?/.exec(s || "");
  if (!m || !MON.includes(m[1])) return null;
  let h = 0;
  let mi = 0;
  if (m[4]) {
    h = Number(m[4]) % 12 + (m[6] === "pm" ? 12 : 0);
    mi = Number(m[5]);
  }
  return new Date(Number(m[3]), MON.indexOf(m[1]), Number(m[2]), h, mi).getTime();
}

/** The project's one date format: Oct 03, 2026 8:03pm. */
export function fmtWhen(ms) {
  const d = new Date(ms);
  const h12 = d.getHours() % 12 || 12;
  const ap = d.getHours() < 12 ? "am" : "pm";
  return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2, "0")}, ${d.getFullYear()} `
    + `${h12}:${String(d.getMinutes()).padStart(2, "0")}${ap}`;
}

export function money(s) {
  const t = String(s || "").replace(/[−–]/g, "-").replace(/[^0-9.+-]/g, "");
  const v = parseFloat(t);
  return Number.isFinite(v) ? v : null;
}

/** One practice trade on the Main tab. Rooms running the same strategy give
 *  their trades the same id (AZOSTOCK #MRTZALF8 closed Oct 10, 2026 3:59am in
 *  #CC94D9FB and #6B08FF64), so the room is part of what makes it one trade. */
export function tradeKey(t) {
  return `${t.room}|${t.trade_id}|${t.closed}`;
}

// Only a trade its own target or stop closed can be set against a backtest
// exit. The move to Gate closed 91 open practice trades at the old exchange's
// last price (Oct 10, 2026 3:56am, 3:58am and 3:59am, `VENUE_SWITCH`), 20 of
// them inside the first run's opening minute; a hand close or the panic
// button is the same case. Those are named, never compared, and their ids are
// never looked up — a looked-up switch id reads as "no result" in the report.
const BY_STRATEGY = new Set(["TP", "SL"]);
const CLOSED_BY = {
  VENUE_SWITCH: "the move to Gate",
  MANUAL_UI: "hand",
  PANIC_CLOSE: "the panic button",
};

/** null when the trade's own target or stop closed it, else why it is not compared. */
export function notByItsStrategy(t) {
  const why = String(t.closed_by ?? "").trim().toUpperCase();
  if (BY_STRATEGY.has(why)) return null;
  if (!why || /^[—–-]+$/.test(why)) return "closed without a recorded reason, not by its strategy";
  return `closed by ${CLOSED_BY[why] || why}, not by its strategy`;
}

/** The practice trades a backtest can answer, the ones it cannot (each with
 *  its verdict), and the strategy ids to look up — each once, first seen first. */
export function split(trades) {
  const compared = [];
  const named = [];
  for (const t of trades) {
    const why = notByItsStrategy(t);
    if (why) named.push({ ...t, verdict: why });
    else if (!t.strategy_id) named.push({ ...t, verdict: "no strategy id on the row" });
    else compared.push(t);
  }
  return { compared, named, ids: [...new Set(compared.map((t) => t.strategy_id))] };
}

/** Step 12, in the operator's words (Oct 14, 2026): 10.6 against 10.8 is
 *  close, against 100 it is not. Close = the same result and within 10% or $0.10. */
export function verdict(p, b) {
  if (p == null || b == null) return "unreadable";
  if (p !== 0 && b !== 0 && (p > 0) !== (b > 0)) return "not close (one won, one lost)";
  const d = Math.abs(p - b);
  return d <= Math.max(0.10, 0.10 * Math.abs(p)) ? "close" : "not close";
}

const msOf = (x, k) => (x[`${k}_ms`] != null ? x[`${k}_ms`] : parseWhen(x[k]));

/** The backtest trade nearest a practice trade — the opened time decides, the
 *  closed time breaks ties — and the verdict. More than `openTolMin` minutes
 *  between the two opened times is no equivalent. */
export function compare(t, log, openTolMin = 10) {
  const tO = msOf(t, "opened");
  const tC = msOf(t, "closed");
  let best = null;
  for (const b of log) {
    const bO = msOf(b, "opened");
    if (bO == null || tO == null) continue;
    const bC = msOf(b, "closed");
    const dO = Math.abs(bO - tO);
    const dC = bC != null && tC != null ? Math.abs(bC - tC) : 0;
    const score = dO * 10 + dC;
    if (!best || score < best.score) best = { b, dO, dC, score };
  }
  if (!best || best.dO > openTolMin * 60_000) {
    // ALREADY IN ITS OWN TRADE (Oct 15, 2026): the stored backtest walks
    // without switch-ons, so a strategy switched on while it held a trade -
    // CLANKER #WVUWQDBP, short from Oct 09, 2026 11:45pm to Oct 10, 2026
    // 12:40pm, switched on at 9:56am - cannot open practice's first one.
    const busy = tO == null ? null : log.find((b) => {
      const bO = msOf(b, "opened");
      const bC = msOf(b, "closed");
      return bO != null && bC != null && bO < tO && bC > tO;
    });
    if (busy) {
      return { verdict: "backtest already in its own trade", backtest: busy,
               note: `the backtest held a ${busy.side || "trade"} from ${busy.opened} to `
                     + `${busy.closed}, so it could not open this one` };
    }
    return { verdict: "no equivalent",
             note: best ? `nearest backtest trade opened ${best.b.opened} (${Math.round(best.dO / 60000)} min away)`
                        : "the backtest's trade list is empty" };
  }
  if (/^END$/i.test(best.b.closed_by || "")) {
    // the backtest's candles stopped while this trade was still open: its
    // "profit" is only the mark at that last candle (XDC 30m, Oct 13, 2026:
    // +0.12 at 11:30am against practice's +0.74 at 12:23pm)
    return { verdict: "backtest ends before this trade closed", backtest: best.b,
             opened_gap_min: Math.round(best.dO / 60000),
             note: `the backtest's candles end ${best.b.closed}, while this trade was still open` };
  }
  return { verdict: verdict(t.profit, best.b.pnl), backtest: best.b,
           opened_gap_min: Math.round(best.dO / 60000), closed_gap_min: Math.round(best.dC / 60000),
           difference: t.profit != null && best.b.pnl != null ? +(best.b.pnl - t.profit).toFixed(2) : null };
}

/** Stored strategies' own answer for an id search that found no row — the
 *  text of its warning paragraph when that answer is about `id`, else null
 *  (still the previous search's). Oct 17, 2026: the app's explanation names
 *  the ROOM too ("#L8XAJAWT is FORM 15m lrslope ... #55D32617 switched it
 *  on"), and treating every other #name as a leftover made all 23 ids wait 3
 *  minutes and read "did not answer". It is this id's answer when it names
 *  this id. */
export function idAnswer(text, id) {
  const t = String(text || "").replace(/\s+/g, " ").trim();
  const named = [...t.matchAll(/#([A-Z0-9]{8})/g)].map((x) => x[1]);
  return named.includes(id) ? t : null;
}

/** A trade log from /api/v2/strategies/trades-by-id (`market_sweep.
 *  trades_for`, the replay a row click runs) in the shape the audit reads off
 *  the table that click draws: opened = entry time, closed = exit time,
 *  closed by = why, profit to the cent as the table's fmtMoney prints it
 *  (Oct 17, 2026: a strategy the list hides is read from its stored row). */
export function fromReplay(log) {
  return (log || []).map((t) => ({
    opened: t["entry time"], closed: t["exit time"], held: t.held ?? "—",
    side: t.side, closed_by: t.why,
    pnl: t["pnl $"] == null ? null : Number(Number(t["pnl $"]).toFixed(2)),
    opened_ms: parseWhen(t["entry time"]), closed_ms: parseWhen(t["exit time"]),
  }));
}

/** A verdict that did not check the trade: it must be looked at again. */
const UNCHECKED = /^(id not in Stored strategies|not checked)/;

/** Where the next ordinary run starts (its window keeps a trade that closed at
 *  or after this plus one minute): the newest trade this run settled, but
 *  never past a trade it could not check. Oct 17, 2026 6:21am checked none of
 *  its 60 trades and saved "Oct 16, 2026 7:03pm", which would have skipped all
 *  60 for good. Null when there is nothing to save. */
export function nextWatermark(trades) {
  let settled = null;
  let open = null;
  for (const t of trades || []) {
    const c = t.closed_ms;
    if (c == null) continue;
    if (UNCHECKED.test(String(t.verdict || ""))) open = open == null ? c : Math.min(open, c);
    else settled = settled == null ? c : Math.max(settled, c);
  }
  if (open == null) return settled;
  const before = open - 60_000;
  return settled == null ? before : Math.min(settled, before);
}

/** The start point to SAVE after a run, from the one saved before it: back to
 *  just before any trade this run left unchecked, else forward to the newest
 *  it settled — never backward for a run that checked everything (an old day
 *  run again). Oct 17, 2026's run had pushed it over 60 unchecked trades, and
 *  a point that only moves forward could never bring them back. */
export function nextSaved(prev, trades) {
  const w = nextWatermark(trades);
  if (w == null) return prev ?? null;
  if (prev == null) return w;
  const pending = (trades || []).some((t) => t.closed_ms != null && UNCHECKED.test(String(t.verdict || "")));
  return pending ? Math.min(prev, w) : Math.max(prev, w);
}


// ACCURACY, EVERY DAY (operator, Oct 18, 2026: "Do the /practice_backtest_audit
// for past 7 days and report to me how many percentage is accuracy, also moving
// forward when i trigger this skill you should automatically report me the
// percentage of accuracy each day"). A practice trade is JUDGED when the check
// set it against a backtest: the verdict says how the backtest answered, or
// that the backtest had no trade (or no row) for it - a miss either way, since
// the backtest did not show that trade. The rest could not be judged and are
// named beside the count: its list did not load, the step failed, the
// backtest's candles end first, closed by hand or by the move to Gate.
const JUDGED = new Set(["close", "not close", "not close (one won, one lost)", "no equivalent",
                        "backtest already in its own trade", "no stored backtest makes this id"]);

const dayStart = (ms) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };
const nextDay = (ms) => { const d = new Date(ms); d.setDate(d.getDate() + 1); return d.getTime(); };
const share = (close, judged) => (judged ? Math.round((1000 * close) / judged) / 10 : null);

/** "The past N days": today and the N - 1 days before it, from local midnight. */
export function pastDays(n, now = Date.now()) {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - (Math.max(1, Math.floor(n)) - 1));
  return { since: d.getTime(), until: now };
}

/** Close ÷ judged for every local day of [since, until), by the day each
 *  practice trade CLOSED (the calendar's rule), and for the whole window. A
 *  day with no trade still gets its line. */
export function dailyAccuracy(trades, since, until) {
  const days = [];
  for (let t = dayStart(since); t < until; t = nextDay(t)) {
    days.push({ day: fmtWhen(t).slice(0, 12), start: t, trades: 0, close: 0, judged: 0,
                pct: null, left_out: {} });
  }
  let n = 0;
  let close = 0;
  let judged = 0;
  for (const tr of trades || []) {
    if (tr.closed_ms == null) continue;
    const day = days.find((d) => d.start === dayStart(tr.closed_ms));
    if (!day) continue;
    day.trades += 1;
    n += 1;
    const v = String(tr.verdict || "");
    if (!JUDGED.has(v)) {
      day.left_out[v] = (day.left_out[v] || 0) + 1;
      continue;
    }
    day.judged += 1;
    judged += 1;
    if (v === "close") {
      day.close += 1;
      close += 1;
    }
  }
  for (const d of days) {
    d.pct = share(d.close, d.judged);
    delete d.start;
  }
  return { days, trades: n, close, judged, pct: share(close, judged) };
}

const listed = (o) => Object.entries(o).map(([k, v]) => `${v} ${k}`).join("; ");

/** The lines every run prints: what was divided by what first (CLAUDE.md rule
 *  24), then one line per day from that day's own counts, then the window. */
export function accuracyLines(daily) {
  const out = ["accuracy by the day a practice trade closed (the trades whose backtest came out "
               + "close, out of the practice trades set against a backtest; close = same result "
               + "and within 10% or 10 cents; a practice trade the backtest has no trade for is a miss):"];
  for (const d of daily.days) {
    if (!d.trades) out.push(`${d.day}: no practice trade closed`);
    else if (!d.judged) {
      out.push(`${d.day}: ${d.trades === 1 ? "its one trade" : `none of its ${d.trades} trades`} `
               + `could be set against a backtest (${listed(d.left_out)})`);
    } else {
      out.push(`${d.day}: ${d.close} of ${d.judged} close = ${d.pct.toFixed(1)}%`
               + (Object.keys(d.left_out).length ? ` (left out: ${listed(d.left_out)})` : ""));
    }
  }
  out.push(daily.judged
    ? `whole window: ${daily.close} of ${daily.judged} close = ${daily.pct.toFixed(1)}%`
    : "whole window: no practice trade could be set against a backtest");
  return out;
}
