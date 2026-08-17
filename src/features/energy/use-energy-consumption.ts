"use client";

import { useCallback, useMemo } from "react";

import {
  ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
  deriveEnergyConsumption,
  type EnergyConsumptionResult,
  type EnergyConsumptionWindow,
} from "@/features/energy/energy-consumption";
import {
  createEnergyBoundaryHistoryCache,
  selectEnergyBoundarySample,
} from "@/features/energy/energy-consumption-cache";
import { ENERGY_METERS } from "@/features/energy/energy-telemetry";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { createTelemetryAdapter } from "@/lib/telemetry/create-adapter";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

const ENERGY_NODE_ID = process.env.NEXT_PUBLIC_NEXOLAB_ENERGY_NODE_ID?.trim() || "edge-01";
const boundaryHistoryCache = createEnergyBoundaryHistoryCache();

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
  securityScopeId,
}: {
  enabled: boolean;
  organizationId: string | null;
  securityScopeId: string | null;
}): EnergyConsumptionLoader {
  const resolvedOrganizationId =
    organizationId?.trim() || process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null;
  const resolvedSecurityScopeId = securityScopeId?.trim() || "anonymous";
  const adapter = useMemo(() => {
    if (!enabled) return null;
    try {
      return securedAdapter(resolvedOrganizationId);
    } catch {
      return null;
    }
  }, [enabled, resolvedOrganizationId]);
  const cacheScopeKey = `${resolvedSecurityScopeId}:${resolvedOrganizationId ?? "no-organization"}`;

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

      try {
        signal?.throwIfAborted();
        const startSamples = await boundaryHistoryCache.load({
          adapter,
          scopeKey: cacheScopeKey,
          nodeId: ENERGY_NODE_ID,
          boundary: window.from,
        });
        signal?.throwIfAborted();
        const startSample = selectEnergyBoundarySample(startSamples, meter, window.from);

        let endSample = selectEnergyBoundarySample(
          currentCumulative ? [currentCumulative] : [],
          meter,
          window.to,
        );
        if (!endSample) {
          const endSamples = await boundaryHistoryCache.load({
            adapter,
            scopeKey: cacheScopeKey,
            nodeId: ENERGY_NODE_ID,
            boundary: window.to,
          });
          signal?.throwIfAborted();
          endSample = selectEnergyBoundarySample(
            endSamples,
            meter,
            window.to,
            ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
          );
        }

        return deriveEnergyConsumption(startSample, endSample, meter);
      } catch (error) {
        if (signal?.aborted) throw error;
        return {
          status: "error",
          valueKwh: null,
          startSample: null,
          endSample: null,
          message: error instanceof Error ? error.message : "Не вдалося завантажити дані споживання.",
        };
      }
    },
    [adapter, cacheScopeKey, enabled],
  );

  const consumptionEnabled = enabled && adapter !== null;
  return useMemo(() => ({ enabled: consumptionEnabled, load }), [consumptionEnabled, load]);
}
