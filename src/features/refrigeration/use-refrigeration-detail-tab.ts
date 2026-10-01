"use client";

import { useCallback, useState, useSyncExternalStore } from "react";

export type RefrigerationDetailTab = "overview" | "scheme" | "graphs" | "controller" | "circuit";

const tabs: readonly RefrigerationDetailTab[] = ["overview", "scheme", "graphs", "controller", "circuit"];

export function refrigerationTabStorageKey(organizationId: string, equipmentId: string): string {
  const organization = encodeURIComponent(organizationId);
  const equipment = encodeURIComponent(equipmentId);
  return `nexolab:refrigeration-detail-tab:v2:${organization}:${equipment}`;
}

function readTab(scope: string | null): RefrigerationDetailTab {
  if (!scope) return "overview";
  try {
    const stored = window.localStorage.getItem(scope);
    return tabs.includes(stored as RefrigerationDetailTab) ? (stored as RefrigerationDetailTab) : "overview";
  } catch {
    return "overview";
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

function serverTab(): RefrigerationDetailTab {
  return "overview";
}

export function useRefrigerationDetailTab(scope: string | null) {
  const snapshot = useCallback(() => readTab(scope), [scope]);
  const storedTab = useSyncExternalStore(subscribe, snapshot, serverTab);
  const [selection, setSelection] = useState<{ scope: string | null; tab: RefrigerationDetailTab } | null>(
    null,
  );
  const activeTab = selection?.scope === scope ? selection.tab : storedTab;

  function setActiveTab(tab: RefrigerationDetailTab) {
    setSelection({ scope, tab });
    if (!scope) return;
    try {
      window.localStorage.setItem(scope, tab);
    } catch {
      // Tab navigation remains available in memory when browser persistence is unavailable.
    }
  }

  return { activeTab, setActiveTab };
}
