import type { Metadata } from "next";
import DeployedTabsErrors from "@/components/errors/DeployedTabsErrors";

export const metadata: Metadata = {
  title: "Errors | TradingAgents",
  description: "What went wrong in each trading room, grouped and paged by the server",
};

// Auto Trade -> Errors (operator, Oct 01, 2026: "can you create a tab called
// 'Errors' then create a section Named 'Deployed Tabs' there i should see
// errors", first under Backtest, then "make it udner auto trade instead").
export default function ErrorsPage() {
  return (
    <div className="flex flex-col gap-5">
      <DeployedTabsErrors />
    </div>
  );
}
