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
      {/* Stored strategies BEFORE the forecast (operator, Sep 25, 2026: "put
          stored strategies section before Forecast for the account") */}
      <StrategiesPanel store="v2" />
      <PortfolioForecast />
      <BacktestStorage store="v2" />
    </div>
  );
}
