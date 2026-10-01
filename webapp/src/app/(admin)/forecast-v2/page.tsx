import type { Metadata } from "next";
import ForecastV2 from "@/components/forecast/ForecastV2";

export const metadata: Metadata = {
  title: "Forecast v2 | TradingAgents",
  description: "Streaks, coins to avoid, where the money goes, and the room rules predicted for this month",
};

// Auto Trade -> Forecast v2 (operator, Oct 01, 2026: "okay run that prompt and
// create Forecast v2"). The first Forecast page stays as it was.
export default function ForecastV2Page() {
  return <ForecastV2 />;
}
