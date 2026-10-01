"use client";

import { useState, type ReactNode } from "react";
import { Sidebar } from "@/components/dashboard/sidebar";
import {
  PlatformAccountBoundary,
  PlatformAccountTopbar,
} from "@/components/dashboard/platform-account-boundary";

export function SessionsShell({ children }: { children: ReactNode }) {
  return (
    <PlatformAccountBoundary organizationHome="/sessions">
      <SessionsShellContent>{children}</SessionsShellContent>
    </PlatformAccountBoundary>
  );
}
function SessionsShellContent({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Сесії випробувань"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <PlatformAccountTopbar title="Сесії випробувань" onMenuOpen={() => setSidebarOpen(true)} />
        <main className="relative overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="relative mx-auto max-w-[1800px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
