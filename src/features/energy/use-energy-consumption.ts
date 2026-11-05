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
import type { CommissionedEnergyMeter } from "@/features/energy/energy-commissioned-meters";
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
    selection: number | CommissionedEnergyMeter,
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

function unavailableCurrentBoundary(): EnergyConsumptionResult {
  return {
    status: "unavailable",
    valueKwh: null,
    startSample: null,
    endSample: null,
    message: "Поточний підтверджений показ накопичувального лічильника ще не отримано або він застарів.",
  };
}

export function useEnergyConsumption({
  enabled,
  organizationId,
  securityScopeId,
  commissionedMeters = [],
}: {
  enabled: boolean;
  organizationId: string | null;
  securityScopeId: string | null;
  commissionedMeters?: readonly CommissionedEnergyMeter[];
}): EnergyConsumptionLoader {
  const inventoryJSON = JSON.stringify(
    [...commissionedMeters].sort((left, right) =>
      `${left.nodeId}\u0000${left.equipmentId}`.localeCompare(`${right.nodeId}\u0000${right.equipmentId}`),
    ),
  );
  const meters = useMemo(() => JSON.parse(inventoryJSON) as CommissionedEnergyMeter[], [inventoryJSON]);
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
    async (selection, window, currentCumulative, signal) => {
      if (!enabled || !adapter) {
        return {
          status: "error",
          valueKwh: null,
          startSample: null,
          endSample: null,
          message: "Енергоспоживання недоступне без авторизованого локального live runtime.",
        };
      }
      const matches =
        typeof selection === "number"
          ? []
          : meters.filter(
              (item) =>
                item.nodeId === selection.nodeId &&
                item.equipmentId === selection.equipmentId &&
                item.unitId === selection.unitId,
            );
      const meter =
        typeof selection === "number"
          ? ENERGY_METERS.find((item) => item.unitId === selection)
          : matches.length === 1
            ? matches[0]
            : undefined;
      if (!meter) {
        return {
          status: "error",
          valueKwh: null,
          startSample: null,
          endSample: null,
          message: "Лічильник відсутній в авторизованому списку або його ідентичність неоднозначна.",
        };
      }

      try {
        const nodeId = "nodeId" in meter ? meter.nodeId : ENERGY_NODE_ID;
        signal?.throwIfAborted();
        const now = Date.now();
        const toAt = window.to.getTime();
        const endsAtCurrentBoundary =
          Number.isFinite(toAt) &&
          toAt <= now + 1_000 &&
          now - toAt <= ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS;
        let endSample = selectEnergyBoundarySample(
          currentCumulative ? [currentCumulative] : [],
          meter,
          window.to,
          ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
          nodeId,
        );

        if (endsAtCurrentBoundary && !endSample) {
          return unavailableCurrentBoundary();
        }

        const startSamples = await boundaryHistoryCache.load({
          adapter,
          scopeKey: cacheScopeKey,
          nodeId,
          boundary: window.from,
        });
        signal?.throwIfAborted();
        const startSample = selectEnergyBoundarySample(
          startSamples,
          meter,
          window.from,
          ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
          nodeId,
        );

        if (!endsAtCurrentBoundary && !endSample) {
          const endSamples = await boundaryHistoryCache.load({
            adapter,
            scopeKey: cacheScopeKey,
            nodeId,
            boundary: window.to,
          });
          signal?.throwIfAborted();
          endSample = selectEnergyBoundarySample(
            endSamples,
            meter,
            window.to,
            ENERGY_CONSUMPTION_ANCHOR_TOLERANCE_MS,
            nodeId,
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
    [adapter, cacheScopeKey, enabled, meters],
  );

  const consumptionEnabled = enabled && adapter !== null;
  return useMemo(() => ({ enabled: consumptionEnabled, load }), [consumptionEnabled, load]);
}
