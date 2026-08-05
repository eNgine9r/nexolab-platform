"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { CamerasWorkspace } from "@/components/cameras/cameras-workspace";
import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { readCameraInventory } from "@/features/cameras/domain";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";

export function CamerasScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const inventory = readCameraInventory();

  if (security.mode === "demo") {
    return (
      <SecurityGate
        state="forbidden"
        error="Камери не підміняються демонстраційними LIVE-сценами. Потрібна перевірена live session."
        errorCode={null}
        diagnostics={null}
        onRetry={security.retry}
      />
    );
  }

  if (
    security.state === "loading" ||
    security.state === "unauthenticated" ||
    security.state === "forbidden" ||
    security.state === "error"
  ) {
    return (
      <SecurityGate
        state={security.state}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Камери"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Камери"
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => {
            void security.signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="mx-auto max-w-[1900px]">
            <CamerasWorkspace items={inventory.items} rejected={inventory.rejected} />
          </div>
        </main>
      </div>
    </div>
  );
}
