/** Server-only Telemetry API origin for privileged Next.js route handlers.
 *
 * The public browser origin may be a protected HTTPS gateway, whereas
 * server-side RBAC/session verification MUST call the private Telemetry API.
 * Explicit external staging fails closed when the server-only origin is absent.
 */
import { SAME_ORIGIN } from "@/lib/runtime/public-endpoints";

/** Exact Compose service name of the private API on the internal network (#1734). */
const PRIVATE_API_SERVICE_NAME = "telemetry-service";

export type ServerTelemetryApiEnv = Readonly<Record<string, string | undefined>>;

function allowedPrivateIPv4(host: string): boolean {
  const octets = host.split(".");
  if (octets.length !== 4 || !octets.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255)) {
    return false;
  }
  const [a, b] = octets.map(Number);
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

export function getServerTelemetryApiBaseUrl(env: ServerTelemetryApiEnv = process.env): URL {
  const privateOrigin = env.NEXOLAB_SERVER_API_BASE_URL?.trim();
  const externalStage = env.NEXOLAB_EXTERNAL_HTTPS_STAGE === "true";

  if (externalStage && !privateOrigin) {
    throw new Error("NEXOLAB external HTTPS stage requires a private server-only API origin");
  }

  if (privateOrigin) {
    let url: URL;
    try {
      url = new URL(privateOrigin);
    } catch {
      throw new Error("Invalid NEXOLAB private server API origin");
    }
    if (
      url.protocol !== "http:" ||
      url.port !== "8082" ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash ||
      !(
        url.hostname === "localhost" ||
        url.hostname === "[::1]" ||
        url.hostname === PRIVATE_API_SERVICE_NAME ||
        allowedPrivateIPv4(url.hostname)
      )
    ) {
      throw new Error("NEXOLAB private server API must use a trusted local address on port 8082");
    }
    return url;
  }

  // Compatibility with the accepted LAN deployment. No active runtime changes.
  const currentLanValue = env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
  if (!currentLanValue) {
    throw new Error("NEXOLAB API base URL is not configured");
  }
  if (currentLanValue === SAME_ORIGIN) {
    // The browser origin is a gateway, never the private API (#1734).
    throw new Error("NEXOLAB same-origin LAN mode requires a private server-only API origin");
  }
  return new URL(currentLanValue);
}
