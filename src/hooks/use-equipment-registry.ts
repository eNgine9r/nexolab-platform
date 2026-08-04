"use client";

import { useEffect, useMemo, useState } from "react";

import {
  isEquipmentRegistryAbort,
  loadEquipmentRegistry,
  type EquipmentRegistryAsset,
  type EquipmentRegistryFailure,
} from "@/features/equipment/asset-registry";
import { createEquipmentRegistryRuntime } from "@/features/equipment/runtime";
import { RefrigerationEquipmentRepositoryError } from "@/features/refrigeration/equipment-repository";

export type EquipmentRegistryState = "idle" | "loading" | "refreshing" | "ready" | "error";

export type UseEquipmentRegistryResult = {
  mode: "demo" | "live";
  state: EquipmentRegistryState;
  assets: EquipmentRegistryAsset[];
  failures: EquipmentRegistryFailure[];
  error: string | null;
  retry: () => void;
};

export function useEquipmentRegistry({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): UseEquipmentRegistryResult {
  const runtime = useMemo(() => createEquipmentRegistryRuntime({ organizationId }), [organizationId]);
  const equipmentRepository = runtime.equipmentRepository;
  const climateCatalogRepository = runtime.climateCatalogRepository;
  const [assets, setAssets] = useState<EquipmentRegistryAsset[]>([]);
  const [failures, setFailures] = useState<EquipmentRegistryFailure[]>([]);
  const [state, setState] = useState<EquipmentRegistryState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const runtimeUnavailable = !equipmentRepository || !climateCatalogRepository;

  useEffect(() => {
    if (!enabled || !equipmentRepository || !climateCatalogRepository) return;

    const controller = new AbortController();
    const startId = window.setTimeout(() => {
      setState((current) => (current === "ready" ? "refreshing" : "loading"));
      setError(null);

      void loadEquipmentRegistry({
        equipmentRepository,
        climateCatalogRepository,
        concurrency: 4,
        signal: controller.signal,
      })
        .then((result) => {
          if (controller.signal.aborted) return;
          setAssets(result.assets);
          setFailures(result.failures);
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
    retry: () => setEpoch((current) => current + 1),
  };
}

function registryErrorMessage(error: unknown): string {
  if (error instanceof RefrigerationEquipmentRepositoryError) return error.message;
  return error instanceof Error ? error.message : "Не вдалося завантажити реєстр обладнання.";
}
