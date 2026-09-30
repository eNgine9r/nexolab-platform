"use client";

import { createContext, useContext, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Topbar } from "@/components/dashboard/topbar";
import { hasPermission } from "@/features/security/security-session";
import { useDashboardSecurity, type DashboardSecurityModel } from "@/hooks/use-dashboard-security";

type RefrigerationAccount = {
  security: DashboardSecurityModel;
  selectOrganization: (organizationId: string) => void;
  signOut: () => void;
};

const RefrigerationAccountContext = createContext<RefrigerationAccount | null>(null);

export function useRefrigerationAccount() {
  return useContext(RefrigerationAccountContext);
}

export function RefrigerationSecurityBoundary({ children }: { children: ReactNode }) {
  const security = useDashboardSecurity();
  const router = useRouter();
  const pathname = usePathname();
  if (security.mode === "live" && security.state !== "ready") {
    return (
      <SecurityGate
        state={security.state === "demo" ? "error" : security.state}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  }

  const account: RefrigerationAccount = {
    security,
    selectOrganization: (organizationId) => {
      if (organizationId === security.membership?.organizationId) return;
      const available = security.session?.memberships.some((item) => item.organizationId === organizationId);
      security.selectOrganization(organizationId);
      if (available && pathname !== "/refrigeration") router.replace("/refrigeration");
    },
    signOut: () => {
      void security.signOut().then(() => router.replace("/login"));
    },
  };
  const scope = `${security.mode}:${security.membership?.organizationId ?? "demo"}`;
  return (
    <RefrigerationAccountContext.Provider key={scope} value={account}>
      {children}
    </RefrigerationAccountContext.Provider>
  );
}

export function RefrigerationAccountTopbar({ title, onMenuOpen }: { title: string; onMenuOpen: () => void }) {
  const account = useRefrigerationAccount();
  const security = account?.security;
  const canCreateSession = security
    ? security.mode === "demo" ||
      Boolean(
        security.session &&
        security.membership &&
        hasPermission(security.session, security.membership.organizationId, "sessions.manage"),
      )
    : false;
  return (
    <Topbar
      title={title}
      onMenuOpen={onMenuOpen}
      showCreateSession={canCreateSession}
      securitySession={security?.session}
      selectedMembership={security?.membership}
      onOrganizationChange={account?.selectOrganization}
      onSignOut={account?.signOut}
    />
  );
}
