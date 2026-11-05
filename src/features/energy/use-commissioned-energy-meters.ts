"use client";

import { useEffect, useState } from "react";
import { HttpCommissioningRepository } from "@/features/equipment/commissioning-repository";
import { commissionedEnergyMeters, type CommissionedEnergyMeter } from "./energy-commissioned-meters";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

type Inventory = { scope: string; status: "loading" | "ready" | "error"; meters: CommissionedEnergyMeter[] };
const EMPTY_METERS: CommissionedEnergyMeter[] = [];

/** Uses only the existing local, organization-scoped commissioning read endpoint. */
export function useCommissionedEnergyMeters(
  enabled: boolean,
  organizationId: string | null,
  securityScopeId: string | null,
) {
  const scope =
    enabled && organizationId && securityScopeId ? JSON.stringify([organizationId, securityScopeId]) : null;
  const [inventory, setInventory] = useState<Inventory | null>(null);
  useEffect(() => {
    if (!scope || !organizationId) return;
    const abort = new AbortController();
    const load = async () => {
      try {
        const config = getTelemetryRuntimeConfig();
        if (config.mode !== "live" || !config.apiBaseUrl) throw new Error("Live runtime unavailable");
        const credentials = createRuntimeCredentialProvider(organizationId);
        const repository = new HttpCommissioningRepository({
          apiBaseUrl: config.apiBaseUrl,
          fetchImpl: createAuthenticatedFetch(fetch.bind(globalThis), credentials),
        });
        const sessions = await repository.listSessions(abort.signal);
        if (!abort.signal.aborted)
          setInventory({ scope, status: "ready", meters: commissionedEnergyMeters(sessions) });
      } catch {
        if (!abort.signal.aborted) setInventory({ scope, status: "error", meters: [] });
      }
    };
    void load();
    return () => abort.abort();
  }, [scope, organizationId]);

  if (!scope) return { status: "disabled" as const, meters: EMPTY_METERS };
  if (!inventory || inventory.scope !== scope) return { status: "loading" as const, meters: EMPTY_METERS };
  return { status: inventory.status, meters: inventory.meters };
}
