"use client";

import { useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { hasPermission } from "@/features/security/security-session";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { SecurityGate } from "./security-gate";
import { canSeePlatformDestination, platformDestinationForPath, Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

export function RouteAccessBoundary({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const destination = platformDestinationForPath(pathname);
  if (!destination) return children;
  return <ProtectedDestination destination={destination}>{children}</ProtectedDestination>;
}

function ProtectedDestination({ destination, children }: { destination: string; children: ReactNode }) {
  const security = useDashboardSecurity();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  if (security.mode === "demo") return children;
  if (security.state !== "ready" || !security.session || !security.membership) {
    const state = security.state === "demo" || security.state === "ready" ? "error" : security.state;
    return (
      <SecurityGate
        state={state}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  }
  if (canSeePlatformDestination(security, destination)) return children;

  const canCreateSession = hasPermission(
    security.session,
    security.membership.organizationId,
    "sessions.manage",
  );
  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar security={security} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Доступ обмежено"
          onMenuOpen={() => setMenuOpen(true)}
          showCreateSession={canCreateSession}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => {
            void security.signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="p-6" role="alert">
          <h1 className="text-xl font-semibold">Доступ до сторінки не надано</h1>
          <p className="mt-3 text-sm text-slate-400">
            Оберіть доступний розділ у меню або зверніться до адміністратора.
          </p>
        </main>
      </div>
    </div>
  );
}
