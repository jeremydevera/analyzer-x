import type { Metadata } from "next";
import AnalysisScreen from "@/components/analysis/AnalysisScreen";

export const metadata: Metadata = {
  title: "Analysis | Trading Agents",
  description: "Run the analyst pipeline on a ticker",
};

export default function AnalysisPage() {
  return <AnalysisScreen />;
}
