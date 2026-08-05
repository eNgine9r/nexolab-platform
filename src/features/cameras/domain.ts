export const CAMERA_STATES = [
  "configured",
  "online",
  "offline",
  "unavailable",
  "invalid",
] as const;

export type CameraState = (typeof CAMERA_STATES)[number];
export type CameraCapability = "snapshot" | "stream";
export type CameraSourceKind =
  | "snapshot-http"
  | "hls"
  | "webrtc"
  | "rtsp"
  | "unknown";

export interface CameraRecord {
  id: string;
  name: string;
  zone: string | null;
  sourceKind: CameraSourceKind;
  endpoint: string | null;
  state: CameraState;
  capabilities: CameraCapability[];
  lastObservedAt: string | null;
  reason: string | null;
}

export interface CameraInventoryResult {
  items: CameraRecord[];
  rejected: number;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isPrivateOrLocalHostname(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname.endsWith(".local") ||
    hostname.endsWith(".lan") ||
    /^127\./.test(hostname) ||
    /^10\./.test(hostname) ||
    /^192\.168\./.test(hostname) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname)
  );
}

export function sanitizeCameraEndpoint(value: unknown): string | null {
  const raw = asString(value);
  if (!raw) return null;

  try {
    const url = new URL(raw);
    if (url.username || url.password) return null;
    if (!isPrivateOrLocalHostname(url.hostname)) return null;
    if (!["http:", "https:", "rtsp:"].includes(url.protocol)) return null;
    return `${url.protocol}//${url.host}${url.pathname}`;
  } catch {
    return null;
  }
}

function parseCapabilities(value: unknown): CameraCapability[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(
      value.filter(
        (item): item is CameraCapability =>
          item === "snapshot" || item === "stream",
      ),
    ),
  );
}

function parseSourceKind(value: unknown): CameraSourceKind {
  return value === "snapshot-http" ||
    value === "hls" ||
    value === "webrtc" ||
    value === "rtsp"
    ? value
    : "unknown";
}

function parseState(value: unknown): CameraState {
  return CAMERA_STATES.includes(value as CameraState)
    ? (value as CameraState)
    : "configured";
}

export function parseCameraInventory(input: unknown): CameraInventoryResult {
  if (!Array.isArray(input)) return { items: [], rejected: 0 };

  const items: CameraRecord[] = [];
  let rejected = 0;

  for (const entry of input) {
    if (!entry || typeof entry !== "object") {
      rejected += 1;
      continue;
    }

    const raw = entry as Record<string, unknown>;
    const id = asString(raw.id);
    const name = asString(raw.name);
    if (!id || !name) {
      rejected += 1;
      continue;
    }

    const sourceKind = parseSourceKind(raw.sourceKind);
    const endpoint = sanitizeCameraEndpoint(raw.endpoint);
    let state = parseState(raw.state);
    let reason = asString(raw.reason);

    if (raw.endpoint != null && !endpoint) {
      state = "invalid";
      reason = "Endpoint configuration is malformed, unsafe or not local.";
    } else if (sourceKind === "rtsp" && state === "online") {
      state = "unavailable";
      reason = "Raw RTSP is not a browser playback contract.";
    }

    items.push({
      id,
      name,
      zone: asString(raw.zone),
      sourceKind,
      endpoint,
      state,
      capabilities: parseCapabilities(raw.capabilities),
      lastObservedAt: asString(raw.lastObservedAt),
      reason,
    });
  }

  return { items, rejected };
}

export function readCameraInventory(): CameraInventoryResult {
  return { items: [], rejected: 0 };
}
