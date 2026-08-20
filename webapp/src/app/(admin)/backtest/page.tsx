import type { Metadata } from "next";
import StoragePanel from "@/components/backtest/StoragePanel";
import StrategiesPanel from "@/components/backtest/StrategiesPanel";
import JobsPanel from "@/components/backtest/JobsPanel";
import HistoryPanel from "@/components/backtest/HistoryPanel";

export const metadata: Metadata = {
  title: "Backtest | TradingAgents",
  description:
    "Pure-local backtesting: candles, strategies, jobs and history on this Mac",
};

export default function BacktestPage() {
  return (
    <div className="flex flex-col gap-5">
      <JobsPanel />
      <StrategiesPanel />
      <StoragePanel />
      <HistoryPanel />
    </div>
  );
}
