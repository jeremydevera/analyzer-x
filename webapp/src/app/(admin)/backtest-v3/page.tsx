import type { Metadata } from "next";
import V3Runner from "@/components/backtest-v3/V3Runner";
import V3Forward from "@/components/backtest-v3/V3Forward";

export const metadata: Metadata = {
  title: "Backtest v3 | TradingAgents",
  description: "One coin and one idea run the v3 way: waiting orders, each idea's own exit, the same risk on every trade, every cost",
};

// BACKTEST V3 (operator, Oct 23, 2026: "i dont see it in ui where is it i said
// to create backtest v3 tab", then "Tab now, fill it later"). The run is the
// server's (/api/v3/run, tradingagents/v3_page.py); the tested-ideas section
// fills when the GitHub test of every idea on every coin has run.
export default function BacktestV3Page() {
  return (
    <div className="flex flex-col gap-5">
      <V3Runner />
      {/* the forward test (operator, Nov 05, 2026: "go") - tradingagents/v3_forward.py */}
      <V3Forward />
    </div>
  );
}
