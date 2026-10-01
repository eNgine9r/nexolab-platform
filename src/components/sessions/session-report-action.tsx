"use client";

import Link from "next/link";
import { FileCheck2 } from "lucide-react";
import { usePlatformAccount } from "@/components/dashboard/platform-account-boundary";
import { hasPermission } from "@/features/security/security-session";
import { reportSessionHref } from "@/lib/reports/session-navigation";
import type { LaboratorySession } from "@/lib/sessions/types";

export function SessionReportAction({ session, pending }: { session: LaboratorySession; pending: boolean }) {
  const account = usePlatformAccount();
  const security = account?.security;
  const organizationId = security?.membership?.organizationId;
  if (
    !security?.session ||
    !organizationId ||
    session.organization_id !== organizationId ||
    (session.state !== "completed" && session.state !== "archived") ||
    !hasPermission(security.session, organizationId, "reports.read")
  )
    return null;
  const label = hasPermission(security.session, organizationId, "reports.generate")
    ? "Сформувати звіт"
    : "Переглянути звіти";
  if (pending || account?.operationPending)
    return (
      <button type="button" disabled className="secondary-button gap-2">
        <FileCheck2 className="h-4 w-4" />
        {label}
      </button>
    );
  return (
    <Link href={reportSessionHref(session.id)} className="secondary-button gap-2">
      <FileCheck2 className="h-4 w-4" />
      {label}
    </Link>
  );
}
