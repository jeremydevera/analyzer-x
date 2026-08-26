import type { Metadata } from "next";
import StrategiesPanel from "@/components/backtest/StrategiesPanel";
import JobsPanel from "@/components/backtest/JobsPanel";
import HistoryPanel from "@/components/backtest/HistoryPanel";
import BacktestStorage from "@/components/backtest/BacktestStorage";
import BacktestHistory from "@/components/backtest/BacktestHistory";

export const metadata: Metadata = {
  title: "Backtest | TradingAgents",
  description:
    "Pure-local backtesting: candles, strategies, jobs and history on this Mac",
};

export default function BacktestPage() {
  return (
    <div className="flex flex-col gap-5">
      <JobsPanel />
      {/* Stored strategies FIRST: the operator reads the measured results
          before the store's bookkeeping (asked 2026-08-26). */}
      <StrategiesPanel />
      {/* how current the measured store is */}
      <BacktestStorage />
      <HistoryPanel />
      {/* LAST, and laid out like Deployment history above it — the operator
          reads the two as the same kind of record */}
      <BacktestHistory />
    </div>
  );
}
