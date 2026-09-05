import type { Metadata } from "next";
import DownloadScreen from "@/components/candles/DownloadScreen";

export const metadata: Metadata = {
  title: "Candles | Trading Agents",
  description: "Download and inspect the candle store on this PC",
};

export default function CandlesPage() {
  return <DownloadScreen />;
}
