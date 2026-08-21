import type { Metadata } from "next";
import { Suspense } from "react";
import AnalysisScreen from "@/components/analysis/AnalysisScreen";

export const metadata: Metadata = {
  title: "Analysis | Trading Agents",
  description: "Run the analyst pipeline on a ticker",
};

export default function AnalysisPage() {
  return (
    <Suspense fallback={<p className="text-theme-sm text-gray-500">loading…</p>}>
      <AnalysisScreen />
    </Suspense>
  );
}
