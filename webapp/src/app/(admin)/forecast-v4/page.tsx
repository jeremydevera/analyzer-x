import type { Metadata } from "next";
import ForecastV4 from "@/components/forecast/ForecastV4";

export const metadata: Metadata = {
  title: "Forecast v4 | TradingAgents",
  description: "Streaks and the best switch-on rules, walked forward over Backtest v4's Claude-skill trades",
};

// AUTO TRADE -> FORECAST V4 (operator, Nov 10, 2026: "in auto trade can you create forecast v4 but
// this time use my backtest v4 data"). Every number is the server's (/api/forecast-v4*,
// tradingagents/forecast_v4.py).
export default function ForecastV4Page() {
  return <ForecastV4 />;
}
