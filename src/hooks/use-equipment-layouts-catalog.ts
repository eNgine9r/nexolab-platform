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
  const [items, setItems] = useState<LayoutCatalogItem[]>([]);
  const [state, setState] = useState<EquipmentLayoutsCatalogState>("idle");
  const [error, setError] = useState<string | null>(runtime.error);
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setState("idle");
      return;
    }
    if (!runtime.equipmentRepository || !runtime.layoutRepository) {
      setState("error");
      setError(runtime.error ?? "Сховище схем обладнання не налаштоване.");
      return;
    }

    const controller = new AbortController();
    setState((current) => (current === "ready" ? "refreshing" : "loading"));
    setError(null);

    void loadLayoutCatalog({
      equipmentRepository: runtime.equipmentRepository,
      layoutRepository: runtime.layoutRepository,
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

    return () => controller.abort();
  }, [enabled, epoch, runtime]);

  return {
    mode: runtime.mode,
    state,
    items,
    error,
    retry: () => setEpoch((current) => current + 1),
  };
}

function catalogErrorMessage(error: unknown): string {
  if (error instanceof RefrigerationEquipmentRepositoryError) return error.message;
  return error instanceof Error ? error.message : "Не вдалося завантажити каталог схем обладнання.";
}
