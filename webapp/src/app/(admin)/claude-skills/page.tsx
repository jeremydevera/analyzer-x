import type { Metadata } from "next";
import ClaudeSkills from "@/components/skills/ClaudeSkills";

export const metadata: Metadata = {
  title: "Claude skills | TradingAgents",
  description: "Every Claude skill in this app, grouped by what it is for, in plain words",
};

// Claude skills (operator, Oct 15, 2026: "can you create a tab called
// 'Claude skills' then categorize them for their function and what do they
// do"). The list is read from .claude/skills on the server.
export default function ClaudeSkillsPage() {
  return (
    <div className="flex flex-col gap-5">
      <ClaudeSkills />
    </div>
  );
}
