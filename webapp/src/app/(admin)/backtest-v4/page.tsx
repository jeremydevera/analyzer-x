import type { Metadata } from "next";
import V4Strategies from "@/components/backtest-v4/V4Strategies";

export const metadata: Metadata = {
  title: "Backtest v4 | TradingAgents",
  description: "Every strategy the Claude skills measured on every coin and timeframe, with every trade, filtered like Backtest v2",
};

// BACKTEST V4 (operator, Nov 10, 2026: "can you do backtest v4 i want the strategies stored there, then
// follow the format like backtest v2 where i can see winrate and filter by day etc"). The list is the
// server's (/api/v4/strategies, tradingagents/v4_store.py).
export default function BacktestV4Page() {
  return <V4Strategies />;
}
