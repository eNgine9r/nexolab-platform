"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import type {
  CommissioningConnectionInventory,
  CommissioningRepository,
  CommissioningSessionWrite,
} from "./commissioning-repository";

export function reconcileLiveConnection(
  draft: CommissioningSessionWrite,
  inventory: CommissioningConnectionInventory,
): CommissioningSessionWrite {
  if (!draft.busId) return draft;
  if (
    inventory.nodeId === draft.nodeId &&
    inventory.connections.some(
      (item) =>
        item.present &&
        item.busId === draft.busId &&
        item.stableTransportIdentifier === draft.stableTransportIdentifier,
    )
  )
    return draft;
  return { ...draft, nodeId: null, busId: null, stableTransportIdentifier: null, unitId: null };
}

export function useLiveConnections(
  repository: CommissioningRepository | null,
  enabled: boolean,
  onInventory: (inventory: CommissioningConnectionInventory) => void,
  onError: (cause: unknown) => void,
) {
  const current = useRef({ repository, onInventory, onError });
  useLayoutEffect(() => {
    current.current = { repository, onInventory, onError };
  }, [repository, onInventory, onError]);

  useEffect(() => {
    if (!repository || !enabled) return;
    let stopped = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let request: AbortController | null = null;
    const tabVisible = () => document.visibilityState !== "hidden";
    const refresh = async () => {
      if (stopped || inFlight || !tabVisible()) return;
      clearTimeout(timer);
      inFlight = true;
      const controller = new AbortController();
      request = controller;
      const deadline = setTimeout(() => controller.abort(), 5000);
      try {
        const inventory = await repository.listConnections(controller.signal);
        if (!stopped && current.current.repository === repository) current.current.onInventory(inventory);
      } catch (cause) {
        if (!stopped && current.current.repository === repository) current.current.onError(cause);
      } finally {
        clearTimeout(deadline);
        inFlight = false;
        if (request === controller) request = null;
        if (!stopped && tabVisible()) {
          timer = setTimeout(() => void refresh(), 2000);
        }
      }
    };
    const resume = () => {
      clearTimeout(timer);
      if (tabVisible()) void refresh();
    };
    void refresh();
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      stopped = true;
      clearTimeout(timer);
      request?.abort();
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [repository, enabled]);
}
