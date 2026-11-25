/**
 * Browser-facing Telemetry API and WebSocket endpoints (#1734).
 *
 * A LOCAL_LAN build may set NEXT_PUBLIC_NEXOLAB_API_BASE_URL and
 * NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL to the literal `same-origin`. The browser
 * then talks to the origin that served the page (a LAN gateway proxies
 * `/api/v1/` to the private API), so one build works on any interface,
 * DHCP address or host name and never compiles a host IP into the bundle.
 *
 * Absolute URLs keep their existing behaviour. `same-origin` cannot be
 * resolved without a browser location: server code must use the private
 * server-only origin instead (see server-telemetry-api-origin.ts).
 */
export const SAME_ORIGIN = "same-origin";
export const TELEMETRY_WEBSOCKET_PATH = "/api/v1/telemetry/live";

export interface BrowserLocationLike {
  readonly protocol: string;
  readonly host: string;
  readonly origin: string;
}

function browserLocation(): BrowserLocationLike | null {
  return typeof window === "undefined" ? null : window.location;
}

export function isSameOrigin(value: string | undefined): boolean {
  return value?.trim() === SAME_ORIGIN;
}

/** Resolved API base URL, or undefined when unset or not resolvable here. */
export function resolvePublicApiBaseUrl(
  raw: string | undefined = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL,
  location: BrowserLocationLike | null = browserLocation(),
): string | undefined {
  const value = raw?.trim();
  if (!value) return undefined;
  if (value !== SAME_ORIGIN) return value;
  if (!location || (location.protocol !== "http:" && location.protocol !== "https:")) return undefined;
  return location.origin;
}

/** Resolved telemetry WebSocket URL, or undefined when unset or not resolvable here. */
export function resolvePublicWebSocketUrl(
  raw: string | undefined = process.env.NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL,
  location: BrowserLocationLike | null = browserLocation(),
): string | undefined {
  const value = raw?.trim();
  if (!value) return undefined;
  if (value !== SAME_ORIGIN) return value;
  if (!location || (location.protocol !== "http:" && location.protocol !== "https:")) return undefined;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}${TELEMETRY_WEBSOCKET_PATH}`;
}
