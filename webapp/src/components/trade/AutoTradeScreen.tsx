"use client";
/** The terminal. One summary fetch feeds the ribbon and the positions table,
 * so the two can never show different position counts. */
import { useState } from "react";
import { TradeSummary } from "@/lib/api";
import SummaryRibbon from "./SummaryRibbon";
import PositionsPanel from "./PositionsPanel";
import StrategiesGrid from "./StrategiesGrid";
import PnlPanel from "./PnlPanel";
import FeedPanel from "./FeedPanel";

export default function AutoTradeScreen() {
  const [s, setS] = useState<TradeSummary | null>(null);
  return (
    <div className="flex flex-col gap-5">
      <SummaryRibbon onSummary={setS} />
      <PositionsPanel real={s?.open_positions ?? []} paper={s?.paper_positions ?? []} />
      <StrategiesGrid />
      <PnlPanel />
      <FeedPanel />
    </div>
  );
}
