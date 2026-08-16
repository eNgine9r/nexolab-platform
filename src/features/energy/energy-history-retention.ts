import type { TelemetrySample } from "@/lib/telemetry/types";

export const ENERGY_HISTORY_RETENTION_TTL_MS = 15 * 60 * 1_000;
export const ENERGY_HISTORY_RECONCILIATION_OVERLAP_MS = 5 * 60 * 1_000;

export interface EnergyHistoryRetentionKey {
  securityScope: string;
  nodeId: string;
  metric: string;
  range: string;
}

export interface EnergyHistoryRetentionWindow {
  from: string;
  to: string;
}

export interface RetainedEnergyHistory {
  window: EnergyHistoryRetentionWindow;
  loadedThrough: string;
  samples: TelemetrySample[];
}

interface RetainedEnergyHistoryEntry extends RetainedEnergyHistory {
  securityScope: string;
  retainedAt: number;
}

const retainedHistory = new Map<string, RetainedEnergyHistoryEntry>();

export function energyHistoryRetentionKey(key: EnergyHistoryRetentionKey): string {
  return JSON.stringify({
    securityScope: key.securityScope,
    nodeId: key.nodeId,
    metric: key.metric,
    range: key.range,
  });
}

export function readRetainedEnergyHistory(
  key: EnergyHistoryRetentionKey,
  now = Date.now(),
): RetainedEnergyHistory | null {
  const serialized = energyHistoryRetentionKey(key);
  const entry = retainedHistory.get(serialized);
  if (!entry) return null;

  if (now - entry.retainedAt > ENERGY_HISTORY_RETENTION_TTL_MS) {
    retainedHistory.delete(serialized);
    return null;
  }

  return cloneEntry(entry);
}

export function retainEnergyHistory(
  key: EnergyHistoryRetentionKey,
  value: RetainedEnergyHistory,
  now = Date.now(),
): void {
  retainedHistory.set(energyHistoryRetentionKey(key), {
    securityScope: key.securityScope,
    retainedAt: now,
    window: { ...value.window },
    loadedThrough: value.loadedThrough,
    samples: value.samples.map((sample) => ({ ...sample })),
  });
}

export function invalidateRetainedEnergyHistory(key: EnergyHistoryRetentionKey): void {
  retainedHistory.delete(energyHistoryRetentionKey(key));
}

export function invalidateIncompatibleRetainedEnergyHistory(securityScope: string): void {
  for (const [key, entry] of retainedHistory) {
    if (entry.securityScope !== securityScope) retainedHistory.delete(key);
  }
}

export function resetRetainedEnergyHistoryForTests(): void {
  retainedHistory.clear();
}

function cloneEntry(entry: RetainedEnergyHistoryEntry): RetainedEnergyHistory {
  return {
    window: { ...entry.window },
    loadedThrough: entry.loadedThrough,
    samples: entry.samples.map((sample) => ({ ...sample })),
  };
}
