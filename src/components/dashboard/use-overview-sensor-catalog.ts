"use client";

import { useEffect, useState } from "react";
import {
  HttpClimateCatalogRepository,
  type ClimateCatalogRepository,
  type ClimateChamberEquipment,
} from "@/features/refrigeration/climate-catalog-repository";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

export async function readOverviewSensorCatalog(
  repository: Pick<ClimateCatalogRepository, "listChambers" | "getEquipment">,
  nodeId: string,
  signal: AbortSignal,
): Promise<ClimateChamberEquipment[]> {
  const chambers = (await repository.listChambers()).filter((item) => item.transportNodeId === nodeId);
  const result: ClimateChamberEquipment[] = [];
  for (let index = 0; index < chambers.length; index += 2) {
    signal.throwIfAborted();
    const equipment = await Promise.all(
      chambers.slice(index, index + 2).map(async (chamber) => {
        const item = await repository.getEquipment(chamber.id);
        if (
          item.climateChamber.id !== chamber.id ||
          item.climateChamber.transportNodeId !== nodeId ||
          item.climateChamber.busId !== chamber.busId
        ) {
          throw new Error("Прив’язку каталогу до камери не підтверджено.");
        }
        return item;
      }),
    );
    result.push(...equipment);
  }
  signal.throwIfAborted();
  return result;
}

export function useOverviewSensorCatalog(
  organizationId: string | null,
  nodeId: string | null,
): {
  equipment: ClimateChamberEquipment[];
  loading: boolean;
  error: string | null;
} {
  const [state, setState] = useState<{
    organizationId: string | null;
    nodeId: string | null;
    equipment: ClimateChamberEquipment[];
    loading: boolean;
    error: string | null;
  }>({ organizationId, nodeId, equipment: [], loading: Boolean(organizationId && nodeId), error: null });
  useEffect(() => {
    if (!organizationId || !nodeId) return;
    let active = true;
    const controller = new AbortController();
    void Promise.resolve()
      .then(async () => {
        const runtime = getTelemetryRuntimeConfig();
        if (runtime.mode !== "live" || !runtime.apiBaseUrl) throw new Error("Live-каталог не підключено.");
        const authenticatedFetch = createAuthenticatedFetch(
          fetch.bind(globalThis),
          createRuntimeCredentialProvider(runtime.apiBaseUrl, organizationId),
        );
        const repository = new HttpClimateCatalogRepository({
          apiBaseUrl: runtime.apiBaseUrl,
          fetchImpl: (input, init) => authenticatedFetch(input, { ...init, signal: controller.signal }),
        });
        return readOverviewSensorCatalog(repository, nodeId, controller.signal);
      })
      .then((equipment) => {
        if (active) setState({ organizationId, nodeId, equipment, loading: false, error: null });
      })
      .catch((cause) => {
        if (!active || controller.signal.aborted) return;
        setState({
          organizationId,
          nodeId,
          equipment: [],
          loading: false,
          error: cause instanceof Error ? cause.message : "Каталог камер недоступний.",
        });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [organizationId, nodeId]);
  return state.organizationId === organizationId && state.nodeId === nodeId
    ? state
    : { equipment: [], loading: Boolean(organizationId && nodeId), error: null };
}
