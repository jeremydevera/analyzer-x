"use client";
/** The terminal. The positions table owns its own fetch (it must poll faster
 * than the ribbon and it carries the close control), and a close bumps `tick`
 * so the ribbon's totals re-read instead of showing a position that is gone. */
import { useEffect, useState } from "react";
import { LATE_MS, begin } from "@/lib/loading";
import LoadingOverlay, { useWaitlist } from "./LoadingCard";
import SummaryRibbon from "./SummaryRibbon";
import PositionsPanel from "./PositionsPanel";
import StrategiesGrid from "./StrategiesGrid";
import PnlPanel from "./PnlPanel";
import FeedPanel from "./FeedPanel";
import CredentialsPanel from "./CredentialsPanel";
import TradeHistory from "./TradeHistory";

export default function AutoTradeScreen() {
  const [tick, setTick] = useState(0);
  const bump = () => setTick((t) => t + 1);
  // the watch SUBSCRIBES first, begin() fires second — effects run in the
  // order the hooks are declared, and the other order left the screen
  // unblurred for its first second (begin's notify hit zero listeners, so
  // the overlay waited for the 1s tick — measured 355ms names=0, 1365ms
  // names=7 on Sep 09, 2026)
  const waitlist = useWaitlist();
  // the spinner card's watchlist — each panel reports when its data lands.
  // `started` covers the FIRST paint: the server-rendered frame has an empty
  // watchlist (begin runs in an effect), and without it the screen flashed
  // sharp for ~1s before the blur landed (measured 396ms, Sep 09, 2026)
  const [started, setStarted] = useState(false);
  useEffect(() => {
    begin(["summary", "positions", "strategies", "MEXC keys",
           "trade history", "profit", "runner feed"]);
    setStarted(true);
  }, []);
  // BLURRED until fully loaded (the operator's design) — but a name stuck
  // past LATE_MS drops the blur: the loaded panels are usable and the stuck
  // one is red, on the overlay and in its own panel. Frosted glass must
  // never become a lock.
  const blurred = !started
    || (waitlist.length > 0 && waitlist.every((w) => w.waitedMs <= LATE_MS));
  return (
    <div className="relative">
      <LoadingOverlay waitlist={waitlist} />
      <div aria-busy={waitlist.length > 0}
           className={`flex min-w-0 flex-col gap-5 ${blurred
             ? "pointer-events-none select-none blur-sm"
             : ""}`}>
      <SummaryRibbon key={`ribbon-${tick}`} onChanged={bump} />
      <PositionsPanel onChanged={bump} />
      <StrategiesGrid />
      <CredentialsPanel />
      <TradeHistory />
      <PnlPanel />
      <FeedPanel />
      </div>
    </div>
  );
}
