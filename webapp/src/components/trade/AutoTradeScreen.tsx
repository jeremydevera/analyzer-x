"use client";
/** The terminal. The positions table owns its own fetch (it must poll faster
 * than the ribbon and it carries the close control), and a close bumps `tick`
 * so the ribbon's totals re-read instead of showing a position that is gone. */
import { useEffect, useState } from "react";
import { begin } from "@/lib/loading";
import LoadingCard from "./LoadingCard";
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
  // the spinner card's watchlist — each panel reports when its data lands
  useEffect(() => {
    begin(["summary", "positions", "strategies", "MEXC keys",
           "trade history", "profit", "runner feed"]);
  }, []);
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <LoadingCard />
      <SummaryRibbon key={`ribbon-${tick}`} onChanged={bump} />
      <PositionsPanel onChanged={bump} />
      <StrategiesGrid />
      <CredentialsPanel />
      <TradeHistory />
      <PnlPanel />
      <FeedPanel />
    </div>
  );
}
