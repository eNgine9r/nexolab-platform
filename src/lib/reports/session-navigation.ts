import type { SessionApiClient } from "@/lib/sessions/api-client";
import type { LaboratorySession } from "@/lib/sessions/types";

export type ReportSessionTarget = { kind: "none" } | { kind: "invalid" } | { kind: "session"; id: string };
export const NO_REPORT_SESSION_TARGET: ReportSessionTarget = { kind: "none" };

export function parseReportSessionTarget(value: string | string[] | undefined): ReportSessionTarget {
  if (value === undefined) return NO_REPORT_SESSION_TARGET;
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  )
    return { kind: "invalid" };
  return { kind: "session", id: value.toLowerCase() };
}

export function reportSessionHref(sessionId: string): string {
  return `/reports?session=${encodeURIComponent(sessionId)}`;
}

export async function loadReportSessionContext(
  target: ReportSessionTarget,
  organizationId: string | null,
  client: Pick<SessionApiClient, "getSession" | "listSessions">,
  signal: AbortSignal,
): Promise<{ sessions: LaboratorySession[]; requested: LaboratorySession | null; error: string | null }> {
  if (target.kind === "none") {
    const [completed, archived] = await Promise.all([
      client.listSessions({ state: "completed", limit: 100 }, signal),
      client.listSessions({ state: "archived", limit: 100 }, signal),
    ]);
    return {
      sessions: [...completed.items, ...archived.items].sort((a, b) =>
        b.updated_at.localeCompare(a.updated_at),
      ),
      requested: null,
      error: null,
    };
  }
  const unavailable = {
    sessions: [],
    requested: null,
    error:
      "Вибране випробування недоступне для звіту в цій організації. Відкрийте його картку або поверніться до всіх звітів.",
  };
  if (target.kind === "invalid" || !organizationId) return unavailable;
  try {
    const session = await client.getSession(target.id, signal);
    if (
      session.id !== target.id ||
      session.organization_id !== organizationId ||
      (session.state !== "completed" && session.state !== "archived")
    )
      return unavailable;
    return { sessions: [session], requested: session, error: null };
  } catch (error) {
    if (signal.aborted) throw error;
    return unavailable;
  }
}
