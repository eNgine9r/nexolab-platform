/** Explicitly opted-in local browser API routing for a Pi with no site LAN.
 *
 * This never widens CORS or Docker host bindings. Backend authentication,
 * firewall and exact Origin allowlists remain independent release gates.
 */

export type OfflineBrowserLocation = { origin: string } | null;

export function currentOfflineBrowserLocation(): OfflineBrowserLocation {
  return typeof window === "undefined" ? null : { origin: window.location.origin };
}

function isPrivateIPv4(host: string): boolean {
  const parts = host.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^(0|[1-9][0-9]{0,2})$/.test(part))) {
    return false;
  }
  const octets = parts.map(Number);
  if (octets.some((value) => value > 255)) {
    return false;
  }
  const [first, second] = octets;
  return first === 10 || (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168);
}

function localBrowserHostname(location: OfflineBrowserLocation): string | null {
  if (!location) {
    // Server-rendered requests never derive a browser host from untrusted headers.
    return null;
  }
  let parsed: URL;
  try {
    parsed = new URL(location.origin);
  } catch {
    throw new Error("Invalid offline dashboard browser origin");
  }
  if (parsed.protocol !== "http:" || parsed.port !== "3000" ||
    parsed.username || parsed.password || parsed.pathname !== "/" ||
    parsed.search || parsed.hash ||
    !(parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" ||
      isPrivateIPv4(parsed.hostname))) {
    throw new Error("Offline dashboard requires an explicit private IPv4 or loopback origin on port 3000");
  }
  return parsed.hostname;
}

function resolveBrowserHost(
  configured: string,
  featureFlag: string | undefined,
  location: OfflineBrowserLocation,
  expectedProtocol: "http:" | "ws:",
  expectedPath: string,
): string {
  if (featureFlag !== "true") {
    return configured;
  }
  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error("Invalid configured offline API or WebSocket URL");
  }
  if (parsed.protocol !== expectedProtocol || parsed.port !== "8082" ||
    !["localhost", "127.0.0.1"].includes(parsed.hostname) ||
    parsed.username || parsed.password || parsed.pathname !== expectedPath ||
    parsed.search || parsed.hash) {
    throw new Error("Dual offline access requires pinned loopback API and WebSocket configuration");
  }
  const hostname = localBrowserHostname(location);
  if (!hostname) {
    return configured;
  }
  parsed.hostname = hostname;
  return parsed.toString().replace(/\\/$/, "");
}

export function resolveOfflineBrowserApiBaseUrl(
  configured: string,
  featureFlag: string | undefined,
  location: OfflineBrowserLocation = currentOfflineBrowserLocation(),
): string {
  return resolveBrowserHost(configured, featureFlag, location, "http:", "/");
}

export function resolveOfflineBrowserWebSocketUrl(
  configured: string,
  featureFlag: string | undefined,
  location: OfflineBrowserLocation = currentOfflineBrowserLocation(),
): string {
  return resolveBrowserHost(
    configured,
    featureFlag,
    location,
    "ws:",
    "/api/v1/telemetry/live",
  );
}
