import type { Metadata } from "next";
import StrategiesPanel from "@/components/backtest/StrategiesPanel";
import JobsPanel from "@/components/backtest/JobsPanel";
import BacktestStorage from "@/components/backtest/BacktestStorage";
import PortfolioForecast from "@/components/backtest/PortfolioForecast";

export const metadata: Metadata = {
  title: "Backtest v2 | TradingAgents",
  description:
    "Same signals, minute-exact exits — measured on this PC from the 1-minute candle store",
};

export default function BacktestV2Page() {
  return (
    <div className="flex flex-col gap-5">
      <JobsPanel store="v2" />
      <PortfolioForecast />
      <StrategiesPanel store="v2" />
      <BacktestStorage store="v2" />
    </div>
  );
}
