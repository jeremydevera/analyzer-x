"use client";

import { useSidebar } from "@/context/SidebarContext";
import AppHeader from "@/layout/AppHeader";
import AppSidebar from "@/layout/AppSidebar";
import Backdrop from "@/layout/Backdrop";
import { newPage } from "@/lib/api";
import { usePathname } from "next/navigation";
import React from "react";

// THE PAGE CHANGED: tell the request queue BEFORE the new page renders, so the
// page just left gives up its queued and running reads (lib/api.ts newPage —
// operator, Oct 05, 2026: Errors and Forecast loaded only after a refresh).
// Done during render on purpose: a child's effects run before its parent's,
// so an effect here would run after the new page's first calls were made.
let _shown: string | null = null;
function PageChange() {
  const path = usePathname();
  if (_shown !== null && path !== _shown) newPage();
  _shown = path;
  return null;
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isExpanded, isHovered, isMobileOpen } = useSidebar();

  // Dynamic class for main content margin based on sidebar state
  const mainContentMargin = isMobileOpen
    ? "ml-0"
    : isExpanded || isHovered
    ? "lg:ml-[290px]"
    : "lg:ml-[90px]";

  return (
    <div className="min-h-screen xl:flex">
      <PageChange />
      {/* Sidebar and Backdrop */}
      <AppSidebar />
      <Backdrop />
      {/* Main Content Area */}
      {/* min-w-0: a flex child defaults to min-width:auto, so a wide table
          inside it grows the track and the whole page scrolls sideways. */}
      <div
        className={`min-w-0 flex-1 transition-all duration-300 ease-in-out ${mainContentMargin}`}
      >
        {/* Header */}
        <AppHeader />
        {/* Page Content */}
        <div className="p-4 mx-auto max-w-(--breakpoint-2xl) md:p-6">{children}</div>
      </div>
    </div>
  );
}
