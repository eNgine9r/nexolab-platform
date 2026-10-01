"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { SecurityGate } from "./security-gate";
import { Topbar } from "./topbar";
import { hasPermission } from "@/features/security/security-session";
import { useDashboardSecurity, type DashboardSecurityModel } from "@/hooks/use-dashboard-security";

type PlatformAccount = {
  security: DashboardSecurityModel;
  selectOrganization: (organizationId: string) => void;
  signOut: () => void;
  operationPending: boolean;
  beginOperation: () => () => void;
};
const PlatformAccountContext = createContext<PlatformAccount | null>(null);
export function usePlatformAccount() {
  return useContext(PlatformAccountContext);
}

export function PlatformAccountBoundary({
  children,
  organizationHome,
}: {
  children: ReactNode;
  organizationHome?: string;
}) {
  const security = useDashboardSecurity();
  const router = useRouter();
  const pathname = usePathname();
  const applyOrganization = security.selectOrganization;
  const [pendingOrganization, setPendingOrganization] = useState<string | null>(null);
  const operationPendingRef = useRef(0);
  const [operationPending, setOperationPendingState] = useState(false);
  const beginOperation = useCallback(() => {
    operationPendingRef.current += 1;
    setOperationPendingState(true);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      operationPendingRef.current -= 1;
      setOperationPendingState(operationPendingRef.current > 0);
    };
  }, []);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const switchingOrganization = Boolean(
    security.state === "ready" &&
    pendingOrganization &&
    pendingOrganization !== security.membership?.organizationId,
  );
  useEffect(() => {
    if (switchingOrganization && pendingOrganization && pathname === organizationHome) {
      applyOrganization(pendingOrganization);
    }
  }, [applyOrganization, organizationHome, pathname, pendingOrganization, switchingOrganization]);

  const selectOrganization = (organizationId: string) => {
    if (operationPendingRef.current) return;
    if (
      organizationId === security.membership?.organizationId ||
      !security.session?.memberships.some((item) => item.organizationId === organizationId)
    )
      return;
    if (organizationHome && pathname !== organizationHome) {
      setPendingOrganization(organizationId);
      router.replace(organizationHome);
    } else {
      applyOrganization(organizationId);
    }
  };
  const signOut = () => {
    if (operationPendingRef.current) return;
    setSigningOut(true);
    setSignOutError(null);
    void security
      .signOut()
      .then(() => {
        setSigningOut(false);
        router.replace("/login");
      })
      .catch(() => {
        setSigningOut(false);
        setSignOutError("Не вдалося завершити вихід. Повторіть спробу.");
      });
  };
  if (signOutError) {
    return (
      <SecurityGate
        state="error"
        error={signOutError}
        errorCode="SESSION_API_ERROR"
        diagnostics={null}
        onRetry={signOut}
      />
    );
  }
  if (signingOut || switchingOrganization) {
    return (
      <SecurityGate
        state="loading"
        error={null}
        errorCode={null}
        diagnostics={null}
        onRetry={security.retry}
      />
    );
  }
  if (security.mode === "live" && (security.state !== "ready" || !security.session || !security.membership)) {
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
  const scope =
    security.mode +
    ":" +
    (security.session?.identity.id ?? "anonymous") +
    ":" +
    (security.membership?.organizationId ?? "demo");
  return (
    <PlatformAccountContext.Provider
      key={scope}
      value={{ security, selectOrganization, signOut, operationPending, beginOperation }}
    >
      {children}
    </PlatformAccountContext.Provider>
  );
}
export function PlatformAccountTopbar({ title, onMenuOpen }: { title: string; onMenuOpen: () => void }) {
  const account = usePlatformAccount();
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
      accountActionsDisabled={account?.operationPending}
      accountActionNotice={
        account?.operationPending
          ? "Операція з випробуванням триває. Зміна організації та вихід будуть доступні після завершення."
          : undefined
      }
    />
  );
}
