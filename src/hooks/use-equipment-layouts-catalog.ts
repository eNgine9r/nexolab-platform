"use client";

import { useCallback, useMemo } from "react";

import {
  isLayoutCatalogAbort,
  loadLayoutCatalog,
  type LayoutCatalogItem,
} from "@/features/equipment-layouts/layout-catalog";
import { createEquipmentLayoutsRuntime } from "@/features/equipment-layouts/runtime";
import { RefrigerationEquipmentRepositoryError } from "@/features/refrigeration/equipment-repository";
import { useMonitoringReadModel } from "@/hooks/use-monitoring-read-model";

export type EquipmentLayoutsCatalogState = "idle" | "loading" | "refreshing" | "ready" | "error";

export type UseEquipmentLayoutsCatalogResult = {
  mode: "demo" | "live";
  state: EquipmentLayoutsCatalogState;
  items: LayoutCatalogItem[];
  error: string | null;
  retry: () => void;
};

const CATALOG_CACHE_KEY = "equipment-layouts:catalog";

export function useEquipmentLayoutsCatalog({
  enabled,
  organizationId,
}: {
  enabled: boolean;
  organizationId: string | null;
}): UseEquipmentLayoutsCatalogResult {
  const runtime = useMemo(() => createEquipmentLayoutsRuntime({ organizationId }), [organizationId]);
  const equipmentRepository = runtime.equipmentRepository;
  const layoutRepository = runtime.layoutRepository;
  const runtimeUnavailable = !equipmentRepository || !layoutRepository || !runtime.cacheScope;
  const load = useCallback(async (): Promise<LayoutCatalogItem[]> => {
    if (!equipmentRepository || !layoutRepository) return [];
    try {
      return await loadLayoutCatalog({
        equipmentRepository,
        layoutRepository,
        concurrency: 4,
      });
    } catch (error) {
      if (isLayoutCatalogAbort(error)) throw error;
      throw error;
    }
  }, [equipmentRepository, layoutRepository]);
  const catalog = useMonitoringReadModel({
    enabled: enabled && !runtimeUnavailable,
    scope: runtime.cacheScope ?? "equipment-layouts:unavailable",
    key: CATALOG_CACHE_KEY,
    load,
  });

  const effectiveState: EquipmentLayoutsCatalogState = !enabled
    ? "idle"
    : runtimeUnavailable
      ? "error"
      : mapState(catalog.status);
  const effectiveError = runtimeUnavailable
    ? (runtime.error ?? "Сховище схем обладнання не налаштоване.")
    : catalog.error
      ? catalogErrorMessage(catalog.error)
      : null;

  return {
    mode: runtime.mode,
    state: effectiveState,
    items: catalog.value ?? [],
    error: effectiveError,
    retry: catalog.retry,
  };
}

function mapState(status: ReturnType<typeof useMonitoringReadModel<LayoutCatalogItem[]>>["status"]): EquipmentLayoutsCatalogState {
  if (status === "idle") return "idle";
  if (status === "loading") return "loading";
  if (status === "ready") return "ready";
  if (status === "error") return "error";
  return "refreshing";
}

function catalogErrorMessage(error: unknown): string {
  if (error instanceof RefrigerationEquipmentRepositoryError) return error.message;
  return error instanceof Error ? error.message : "Не вдалося завантажити каталог схем обладнання.";
}
