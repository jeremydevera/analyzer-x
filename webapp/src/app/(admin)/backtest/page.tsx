import type { Metadata } from "next";
import StrategiesPanel from "@/components/backtest/StrategiesPanel";
import JobsPanel from "@/components/backtest/JobsPanel";
import HistoryPanel from "@/components/backtest/HistoryPanel";
import LogsPanel from "@/components/backtest/LogsPanel";
import BacktestStorage from "@/components/backtest/BacktestStorage";
import BacktestHistory from "@/components/backtest/BacktestHistory";

export const metadata: Metadata = {
  title: "Backtest | TradingAgents",
  // On Sep 05, 2026 the measuring moved to GitHub Actions and only the STORE
  // stayed on this machine. Saying which half went where is the whole point: a
  // page still describing itself as local-only would be a caption arguing with
  // its own buttons. (The old wording is not repeated here — a test greps this
  // file for it, and a comment quoting it would defeat that.)
  description:
    "Backtesting measured on GitHub Actions; candles, rows and history stored on this PC",
};

export default function BacktestPage() {
  return (
    <div className="flex flex-col gap-5">
      <JobsPanel />
      {/* LOGS, right under the buttons that produce them: what is still
          pending on this machine and every named error, from here and from
          the GitHub shards (operator, 2026-09-03). */}
      <LogsPanel />
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
