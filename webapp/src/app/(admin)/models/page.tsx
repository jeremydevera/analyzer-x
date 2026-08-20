import type { Metadata } from "next";
import ModelsScreen from "@/components/models/ModelsScreen";

export const metadata: Metadata = {
  title: "LLM Models | Trading Agents",
  description: "The model catalog and its live health",
};

export default function ModelsPage() {
  return <ModelsScreen />;
}
