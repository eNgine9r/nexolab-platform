"use client";

import { useEffect, useMemo, useState } from "react";

import {
  isLayoutCatalogAbort,
  loadLayoutCatalog,
  type LayoutCatalogItem,
} from "@/features/equipment-layouts/layout-catalog";
import { createEquipmentLayoutsRuntime } from "@/features/equipment-layouts/runtime";
import { RefrigerationEquipmentRepositoryError } from "@/features/refrigeration/equipment-repository";

export type EquipmentLayoutsCatalogState = "idle" | "loading" | "refreshing" | "ready" | "error";

export type UseEquipmentLayoutsCatalogResult = {
  mode: "demo" | "live";
  state: EquipmentLayoutsCatalogState;
  items: LayoutCatalogItem[];
  error: string | null;
  retry: () => void;
};

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
  const [items, setItems] = useState<LayoutCatalogItem[]>([]);
  const [state, setState] = useState<EquipmentLayoutsCatalogState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const runtimeUnavailable = !equipmentRepository || !layoutRepository;

  useEffect(() => {
    if (!enabled || !equipmentRepository || !layoutRepository) return;

    const controller = new AbortController();
    const startId = window.setTimeout(() => {
      setState((current) => (current === "ready" ? "refreshing" : "loading"));
      setError(null);

      void loadLayoutCatalog({
        equipmentRepository,
        layoutRepository,
        concurrency: 4,
        signal: controller.signal,
      })
        .then((loadedItems) => {
          if (controller.signal.aborted) return;
          setItems(loadedItems);
          setState("ready");
        })
        .catch((loadError: unknown) => {
          if (isLayoutCatalogAbort(loadError)) return;
          setState("error");
          setError(catalogErrorMessage(loadError));
        });
    }, 0);

    return () => {
      window.clearTimeout(startId);
      controller.abort();
    };
  }, [enabled, epoch, equipmentRepository, layoutRepository]);

  const effectiveState: EquipmentLayoutsCatalogState = !enabled
    ? "idle"
    : runtimeUnavailable
      ? "error"
      : state;
  const effectiveError = runtimeUnavailable
    ? (runtime.error ?? "Сховище схем обладнання не налаштоване.")
    : error;

  return {
    mode: runtime.mode,
    state: effectiveState,
    items,
    error: effectiveError,
    retry: () => setEpoch((current) => current + 1),
  };
}

function catalogErrorMessage(error: unknown): string {
  if (error instanceof RefrigerationEquipmentRepositoryError) return error.message;
  return error instanceof Error ? error.message : "Не вдалося завантажити каталог схем обладнання.";
}
