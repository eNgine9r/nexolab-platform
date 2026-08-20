"use client";

import { useEffect, useMemo, useState } from "react";

import {
  isEquipmentRegistryAbort,
  loadEquipmentRegistry,
  type EquipmentRegistryAsset,
  type EquipmentRegistryFailure,
  type EquipmentRegistryLoadProgress,
} from "@/features/equipment/asset-registry";
import type { EquipmentDiscoveryRepository } from "@/features/equipment/discovery-repository";
import { createEquipmentRegistryRuntime } from "@/features/equipment/runtime";
import type { ClimateCatalogRepository } from "@/features/refrigeration/climate-catalog-repository";
import {
  RefrigerationEquipmentRepositoryError,
  type RefrigerationEquipmentRepository,
} from "@/features/refrigeration/equipment-repository";

export type EquipmentRegistryState = "idle" | "loading" | "refreshing" | "ready" | "error";

export type UseEquipmentRegistryResult = {
  mode: "demo" | "live";
  state: EquipmentRegistryState;
  assets: EquipmentRegistryAsset[];
  failures: EquipmentRegistryFailure[];
  error: string | null;
  progress: Pick<EquipmentRegistryLoadProgress, "completedChambers" | "totalChambers"> | null;
  equipmentRepository: RefrigerationEquipmentRepository | null;
  climateCatalogRepository: ClimateCatalogRepository | null;
  discoveryRepository: EquipmentDiscoveryRepository | null;
  retry: () => void;
};

export function useEquipmentRegistry({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): UseEquipmentRegistryResult {
  const runtime = useMemo(
    () => createEquipmentRegistryRuntime({ organizationId: organizationId ?? undefined }),
    [organizationId],
  );
  const equipmentRepository = runtime.equipmentRepository;
  const climateCatalogRepository = runtime.climateCatalogRepository;
  const [assets, setAssets] = useState<EquipmentRegistryAsset[]>([]);
  const [failures, setFailures] = useState<EquipmentRegistryFailure[]>([]);
  const [state, setState] = useState<EquipmentRegistryState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<Pick<
    EquipmentRegistryLoadProgress,
    "completedChambers" | "totalChambers"
  > | null>(null);
  const [epoch, setEpoch] = useState(0);
  const runtimeUnavailable = !equipmentRepository || !climateCatalogRepository;

  useEffect(() => {
    if (!enabled || !equipmentRepository || !climateCatalogRepository) return;

    const controller = new AbortController();
    const startId = window.setTimeout(() => {
      setState((current) => (current === "ready" ? "refreshing" : "loading"));
      setError(null);
      setProgress(null);

      void loadEquipmentRegistry({
        equipmentRepository,
        climateCatalogRepository,
        concurrency: 4,
        signal: controller.signal,
        onProgress: (next) => {
          if (controller.signal.aborted) return;
          setAssets(next.assets);
          setFailures(next.failures);
          setProgress({ completedChambers: next.completedChambers, totalChambers: next.totalChambers });
        },
      })
        .then((result) => {
          if (controller.signal.aborted) return;
          setAssets(result.assets);
          setFailures(result.failures);
          setProgress((current) =>
            current ? { ...current, completedChambers: current.totalChambers } : current,
          );
          setState("ready");
        })
        .catch((loadError: unknown) => {
          if (isEquipmentRegistryAbort(loadError)) return;
          setState("error");
          setError(registryErrorMessage(loadError));
        });
    }, 0);

    return () => {
      window.clearTimeout(startId);
      controller.abort();
    };
  }, [climateCatalogRepository, enabled, epoch, equipmentRepository]);

  const effectiveState: EquipmentRegistryState = !enabled ? "idle" : runtimeUnavailable ? "error" : state;
  const effectiveError = runtimeUnavailable
    ? (runtime.error ?? "Сховище реєстру обладнання не налаштоване.")
    : error;

  return {
    mode: runtime.mode,
    state: effectiveState,
    assets,
    failures,
    error: effectiveError,
    progress,
    equipmentRepository,
    climateCatalogRepository,
    discoveryRepository: runtime.discoveryRepository,
    retry: () => setEpoch((current) => current + 1),
  };
}

function registryErrorMessage(error: unknown): string {
  if (error instanceof RefrigerationEquipmentRepositoryError) return error.message;
  return error instanceof Error ? error.message : "Не вдалося завантажити реєстр обладнання.";
}
