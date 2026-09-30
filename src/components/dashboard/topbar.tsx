import Link from "next/link";
import { Bell, LogOut, Menu, Plus } from "lucide-react";

import type { SecurityMembership, SecuritySession } from "@/features/security/security-session";

interface TopbarProps {
  title: string;
  onMenuOpen: () => void;
  onCreateSession?: () => void;
  createSessionHref?: string;
  showCreateSession?: boolean;
  securitySession?: SecuritySession | null;
  selectedMembership?: SecurityMembership | null;
  onOrganizationChange?: (organizationId: string) => void;
  onSignOut?: () => void;
}

export function Topbar({
  title,
  onMenuOpen,
  onCreateSession,
  createSessionHref = "/sessions/new",
  showCreateSession = true,
  securitySession = null,
  selectedMembership = null,
  onOrganizationChange,
  onSignOut,
}: TopbarProps) {
  const createClasses =
    "inline-flex h-10 shrink-0 items-center gap-2 rounded-xl bg-blue-600 px-3.5 text-[11px] font-semibold text-white transition hover:bg-blue-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300";
  const createContent = (
    <>
      <Plus className="h-4 w-4" aria-hidden="true" />
      <span className="hidden sm:inline">Нова сесія</span>
    </>
  );
  const identityLabel = securitySession
    ? (securitySession.identity.displayName ??
      securitySession.identity.email ??
      securitySession.identity.subject)
    : null;

  return (
    <header
      data-testid="platform-topbar"
      className="sticky top-0 z-30 flex min-h-[78px] flex-wrap items-center gap-x-3 gap-y-2 border-b border-white/[0.055] bg-[#07172e]/90 px-4 py-3 backdrop-blur-xl sm:px-5 xl:px-6"
    >
      <button
        type="button"
        className="icon-button inline-grid shrink-0 lg:hidden"
        onClick={onMenuOpen}
        aria-label="Відкрити меню"
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>
      <p className="min-w-0 flex-1 truncate text-sm font-semibold text-white">{title}</p>

      {securitySession ? (
        <div
          data-organization-id={selectedMembership?.organizationId}
          className="order-last flex w-full min-w-0 items-center gap-3 md:order-none md:w-auto"
        >
          <span className="min-w-0 flex-1 text-left md:max-w-36">
            <span className="block truncate text-[11px] font-medium text-slate-100">{identityLabel}</span>
            {selectedMembership ? (
              <span className="block truncate text-[10px] text-slate-400">
                {selectedMembership.roles.join(", ")}
              </span>
            ) : null}
          </span>
          {selectedMembership ? (
            onOrganizationChange && securitySession.memberships.length > 1 ? (
              <label className="flex min-w-0 items-center">
                <span className="sr-only">Організація</span>
                <select
                  value={selectedMembership.organizationId}
                  onChange={(event) => onOrganizationChange(event.target.value)}
                  className="h-10 max-w-48 rounded-xl border border-white/10 bg-[#07172e] px-2 text-xs text-slate-200 focus-visible:outline-2 focus-visible:outline-cyan-300"
                >
                  {securitySession.memberships.map((membership) => (
                    <option key={membership.organizationId} value={membership.organizationId}>
                      {membership.organizationName}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <span className="max-w-48 truncate text-xs text-slate-400">
                {selectedMembership.organizationName}
              </span>
            )
          ) : null}
        </div>
      ) : null}

      <div className="flex shrink-0 items-center gap-2">
        <Link
          href="/alerts"
          className="icon-button inline-grid"
          aria-label="Відкрити тривоги"
          title="Тривоги"
        >
          <Bell className="h-[18px] w-[18px]" aria-hidden="true" />
        </Link>
        {showCreateSession ? (
          onCreateSession ? (
            <button type="button" onClick={onCreateSession} className={createClasses} aria-label="Нова сесія">
              {createContent}
            </button>
          ) : (
            <Link href={createSessionHref} className={createClasses} aria-label="Нова сесія">
              {createContent}
            </Link>
          )
        ) : null}
        {onSignOut ? (
          <button
            type="button"
            onClick={onSignOut}
            className="icon-button inline-grid"
            aria-label="Вийти з NEXOLAB"
            title="Вийти з NEXOLAB"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
          </button>
        ) : null}
      </div>
    </header>
  );
}
