import type { Metadata } from "next";
import AutoTradeScreen from "@/components/trade/AutoTradeScreen";

export const metadata: Metadata = {
  title: "Auto Trade | Trading Agents",
  description: "The trading terminal: runner, strategies, positions, profit",
};

export default function TradePage() {
  return <AutoTradeScreen />;
}
