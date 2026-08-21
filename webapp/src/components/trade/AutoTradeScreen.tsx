"use client";
/** The terminal. The positions table owns its own fetch (it must poll faster
 * than the ribbon and it carries the close control), and a close bumps `tick`
 * so the ribbon's totals re-read instead of showing a position that is gone. */
import { useState } from "react";
import SummaryRibbon from "./SummaryRibbon";
import PositionsPanel from "./PositionsPanel";
import StrategiesGrid from "./StrategiesGrid";
import PnlPanel from "./PnlPanel";
import FeedPanel from "./FeedPanel";
import CredentialsPanel from "./CredentialsPanel";
import TradeHistory from "./TradeHistory";
import EquityCurve from "./EquityCurve";

export default function AutoTradeScreen() {
  const [tick, setTick] = useState(0);
  const bump = () => setTick((t) => t + 1);
  return (
    <div className="flex flex-col gap-5">
      <SummaryRibbon key={`ribbon-${tick}`} onChanged={bump} />
      <PositionsPanel onChanged={bump} />
      <EquityCurve />
      <StrategiesGrid />
      <CredentialsPanel />
      <TradeHistory />
      <PnlPanel />
      <FeedPanel />
    </div>
  );
}
