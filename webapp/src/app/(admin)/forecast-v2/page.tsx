import type { Metadata } from "next";
import ForecastV2 from "@/components/forecast/ForecastV2";
import { RoomBacktest, RoomsAndBacktest, RoomStrategiesSection } from "@/components/forecast/RoomForecasts";

export const metadata: Metadata = {
  title: "Forecast | TradingAgents",
  description: "Backtest a room, the room strategies prompt 4 kept, streaks, and the room rules predicted for this month",
};

// Auto Trade -> Forecast v2 (operator, Oct 01, 2026: "okay run that prompt and
// create Forecast v2"), and since Oct 02, 2026 THE Forecast page: "can i merge
// forecast to forecast v2 since they are almost the same? ... what matters to
// me is this prompt and ability to backtest a room strategy". The first
// Forecast's Backtest a room and Rooms table sit under Forecast v2; its own
// page (/forecast) stays reachable by its address, off the menu.
export default function ForecastV2Page() {
  return (
    <div className="flex flex-col gap-5">
      {/* Backtest a room sits above the Streaks (operator, Oct 05, 2026), and
          Room strategies directly under it (Oct 07, 2026: "put room
          strategies under backtest a room") */}
      <ForecastV2 beforeStreaks={<><RoomBacktest /><RoomStrategiesSection /></>} />
      <RoomsAndBacktest />
    </div>
  );
}
