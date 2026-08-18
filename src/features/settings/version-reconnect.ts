const VERSION_RECONNECT_DELAYS_MS = [1500, 3000, 5000, 8000, 10000] as const;

export function versionReconnectDelayMs(attempt: number): number {
  const safeAttempt = Number.isFinite(attempt) ? Math.max(0, Math.floor(attempt)) : 0;
  return VERSION_RECONNECT_DELAYS_MS[Math.min(safeAttempt, VERSION_RECONNECT_DELAYS_MS.length - 1)];
}
