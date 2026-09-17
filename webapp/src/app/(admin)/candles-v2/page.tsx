import type { Metadata } from "next";
import DownloadScreen from "@/components/candles/DownloadScreen";

export const metadata: Metadata = {
  title: "Candles v2 | Trading Agents",
  description: "1-minute candles for Backtest v2 — downloaded and extended on this PC",
};

export default function CandlesV2Page() {
  return <DownloadScreen store="v2" />;
}
