"use client";

import { useCallback, useMemo } from "react";

import {
  loadEnergyConsumption,
  type EnergyConsumptionResult,
  type EnergyConsumptionWindow,
} from "@/features/energy/energy-consumption";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const ENERGY_NODE_ID = process.env.NEXT_PUBLIC_NEXOLAB_ENERGY_NODE_ID?.trim() || "edge-01";

export interface EnergyConsumptionLoader {
  enabled: boolean;
  load: (
    unitId: number,
    window: EnergyConsumptionWindow,
    currentCumulative: TelemetrySample | null,
    signal?: AbortSignal,
  ) => Promise<EnergyConsumptionResult>;
}

function securedAdapter(organizationId: string | null): TelemetryAdapter {
  const config = getTelemetryRuntimeConfig();
  if (config.mode !== "live") {
    throw new Error("Energy consumption is available only in live mode");
  }
  const credentialProvider = createRuntimeCredentialProvider(organizationId);
  return createTelemetryAdapter(config, {
    rest: {
      fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider),
    },
    websocket: { credentials: credentialProvider },
  });
}

export function useEnergyConsumption({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): EnergyConsumptionLoader {
  const resolvedOrganizationId =
    organizationId?.trim() || process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null;
  const adapter = useMemo(() => {
    if (!enabled) return null;
    try {
      return securedAdapter(resolvedOrganizationId);
    } catch {
      return null;
    }
  }, [enabled, resolvedOrganizationId]);

  const load = useCallback<EnergyConsumptionLoader["load"]>(
    async (unitId, window, currentCumulative, signal) => {
      if (!enabled || !adapter) {
        return {
          status: "error",
          valueKwh: null,
          startSample: null,
          endSample: null,
          message: "Енергоспоживання недоступне без авторизованого локального live runtime.",
        };
      }
      const meter = ENERGY_METERS.find((item) => item.unitId === unitId);
      if (!meter) {
        return {
          status: "error",
          valueKwh: null,
          startSample: null,
          endSample: null,
          message: `Невідомий LE-01MP Unit ${unitId}.`,
        };
      }
      return loadEnergyConsumption(
        adapter,
        {
          nodeId: ENERGY_NODE_ID,
          meter,
          window,
          currentCumulative,
        },
        signal,
      );
    },
    [adapter, enabled],
  );

  return { enabled: enabled && adapter !== null, load };
}
