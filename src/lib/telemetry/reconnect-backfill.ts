import type { TelemetryConnectionState } from "./types";

/**
 * Samples published while the WebSocket was down are never replayed by the
 * stream. After a reconnect the chart history must be reloaded for the current
 * window, otherwise the outage is silently drawn as a straight line or a hole
 * that never fills. Returns a state observer that fires `onReconnected` once
 * per recovered outage (not on the initial connection).
 */
export function createReconnectBackfillObserver(
  onReconnected: () => void,
): (state: TelemetryConnectionState) => void {
  let connectedOnce = false;
  let outage = false;
  return (state) => {
    if (state === "connected") {
      if (connectedOnce && outage) onReconnected();
      connectedOnce = true;
      outage = false;
      return;
    }
    if (connectedOnce && (state === "reconnecting" || state === "offline")) outage = true;
  };
}
