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
