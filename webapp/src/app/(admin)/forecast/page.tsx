import type { Metadata } from "next";
import RoomForecasts from "@/components/forecast/RoomForecasts";

export const metadata: Metadata = {
  title: "Forecast | TradingAgents",
  description: "Saved forecasts of which trading room is best, newest first",
};

// Auto Trade -> Forecast (operator, Oct 01, 2026: "create a forecast tab, then
// if i run this prompt make sure it will generate a new forecast / take note
// create forecast tab only for now").
export default function ForecastPage() {
  return <RoomForecasts />;
}
