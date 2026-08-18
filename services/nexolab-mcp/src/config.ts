const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);

function readPositiveInt(name: string, fallback: number, max: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0 || value > max) {
    throw new Error(`${name} must be an integer between 1 and ${max}.`);
  }
  return value;
}

function readUrl(name: string, fallback?: string): string {
  const raw = process.env[name]?.trim() || fallback;
  if (!raw) throw new Error(`${name} is required.`);
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(`${name} must be an absolute http(s) URL.`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`${name} must use http or https.`);
  }
  parsed.hash = "";
  parsed.search = "";
  parsed.pathname = parsed.pathname.replace(/\/$/, "");
  return parsed.toString().replace(/\/$/, "");
}

function csv(name: string): string[] {
  return (process.env[name] ?? "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
}

export type BackendAuthConfig =
  | { mode: "none" }
  | { mode: "bearer"; bearerToken: string }
  | { mode: "local"; username: string; passwordFile: string };

export type McpConfig = {
  host: string;
  port: number;
  telemetryApiUrl: string;
  nodesApiUrl: string;
  organizationId: string;
  backendAuth: BackendAuthConfig;
  mcpBearerToken?: string;
  allowedHosts: string[];
  allowedOrigins: string[];
  requestTimeoutMs: number;
  maxLatestItems: number;
  maxHistoryItems: number;
  maxHistoryHours: number;
};

export function loadConfig(): McpConfig {
  const host = process.env.NEXOLAB_MCP_HOST?.trim() || "127.0.0.1";
  const telemetryApiUrl = readUrl("NEXOLAB_TELEMETRY_API_URL");
  const nodesApiUrl = readUrl("NEXOLAB_NODES_API_URL", telemetryApiUrl);
  const organizationId = process.env.NEXOLAB_ORGANIZATION_ID?.trim();
  if (!organizationId) throw new Error("NEXOLAB_ORGANIZATION_ID is required.");
  const backendAuthMode = process.env.NEXOLAB_BACKEND_AUTH_MODE?.trim() || "none";
  let backendAuth: BackendAuthConfig;
  if (backendAuthMode === "none") {
    backendAuth = { mode: "none" };
  } else if (backendAuthMode === "bearer") {
    const bearerToken = process.env.NEXOLAB_BACKEND_BEARER_TOKEN?.trim();
    if (!bearerToken) throw new Error("NEXOLAB_BACKEND_BEARER_TOKEN is required in bearer auth mode.");
    backendAuth = { mode: "bearer", bearerToken };
  } else if (backendAuthMode === "local") {
    const username = process.env.NEXOLAB_BACKEND_USERNAME?.trim();
    const passwordFile = process.env.NEXOLAB_BACKEND_PASSWORD_FILE?.trim();
    if (!username) throw new Error("NEXOLAB_BACKEND_USERNAME is required in local auth mode.");
    if (!passwordFile) throw new Error("NEXOLAB_BACKEND_PASSWORD_FILE is required in local auth mode.");
    backendAuth = { mode: "local", username, passwordFile };
  } else {
    throw new Error("NEXOLAB_BACKEND_AUTH_MODE must be none, bearer, or local.");
  }
  const mcpBearerToken = process.env.NEXOLAB_MCP_BEARER_TOKEN?.trim() || undefined;

  const explicitAllowedHosts = csv("NEXOLAB_MCP_ALLOWED_HOSTS");
  const allowedHosts = explicitAllowedHosts.length
    ? explicitAllowedHosts
    : LOOPBACK_HOSTS.has(host)
      ? ["127.0.0.1", "localhost", "::1"]
      : [];

  if (!LOOPBACK_HOSTS.has(host) && !mcpBearerToken) {
    throw new Error(
      "Refusing a non-loopback MCP bind without NEXOLAB_MCP_BEARER_TOKEN. Prefer a secure tunnel and keep NEXOLAB_MCP_HOST=127.0.0.1.",
    );
  }
  if (!LOOPBACK_HOSTS.has(host) && allowedHosts.length === 0) {
    throw new Error("NEXOLAB_MCP_ALLOWED_HOSTS is required for a non-loopback MCP bind.");
  }

  return {
    host,
    port: readPositiveInt("NEXOLAB_MCP_PORT", 8787, 65_535),
    telemetryApiUrl,
    nodesApiUrl,
    organizationId,
    backendAuth,
    ...(mcpBearerToken ? { mcpBearerToken } : {}),
    allowedHosts,
    allowedOrigins: csv("NEXOLAB_MCP_ALLOWED_ORIGINS"),
    requestTimeoutMs: readPositiveInt("NEXOLAB_MCP_REQUEST_TIMEOUT_MS", 8_000, 60_000),
    maxLatestItems: readPositiveInt("NEXOLAB_MCP_MAX_LATEST_ITEMS", 200, 1_000),
    maxHistoryItems: readPositiveInt("NEXOLAB_MCP_MAX_HISTORY_ITEMS", 500, 5_000),
    maxHistoryHours: readPositiveInt("NEXOLAB_MCP_MAX_HISTORY_HOURS", 24 * 31, 24 * 366),
  };
}
