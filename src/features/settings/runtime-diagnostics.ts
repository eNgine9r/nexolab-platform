export type SettingsConfigurationState = "ready" | "incomplete" | "unsafe";

export type SettingsDataMode = "live" | "demo" | "invalid";
export type SettingsAuthProvider = "local" | "supabase" | "disabled" | "custom" | "missing";
export type SettingsDiagnosticSeverity = "info" | "warning" | "critical";
export type SettingsEndpointKind = "api" | "websocket" | "browser";

export type SettingsRuntimeInput = {
  profile?: string;
  dataMode?: string;
  authProvider?: string;
  apiBaseUrl?: string;
  websocketUrl?: string;
  browserOrigin?: string | null;
};

export type SanitizedSettingsEndpoint = {
  kind: SettingsEndpointKind;
  configured: boolean;
  valid: boolean;
  displayValue: string | null;
  origin: string | null;
  pathname: string | null;
  protocol: string | null;
  redactions: string[];
  error: string | null;
};

export type SettingsDiagnosticIssue = {
  code: string;
  severity: SettingsDiagnosticSeverity;
  title: string;
  message: string;
};

export type SettingsRuntimeDiagnostics = {
  profile: string;
  dataMode: SettingsDataMode;
  authProvider: SettingsAuthProvider;
  authProviderLabel: string;
  status: SettingsConfigurationState;
  api: SanitizedSettingsEndpoint;
  websocket: SanitizedSettingsEndpoint;
  browser: SanitizedSettingsEndpoint;
  issues: SettingsDiagnosticIssue[];
  offlineFirst: true;
};

const SAFE_PROVIDER_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/i;

export function readSettingsRuntimeInput(browserOrigin: string | null): SettingsRuntimeInput {
  return {
    profile: "LOCAL_LAN",
    dataMode: process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE,
    authProvider: process.env.NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER,
    apiBaseUrl: process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL,
    websocketUrl: process.env.NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL,
    browserOrigin,
  };
}

export function buildSettingsRuntimeDiagnostics(input: SettingsRuntimeInput): SettingsRuntimeDiagnostics {
  const profile = input.profile?.trim() || "LOCAL_LAN";
  const dataMode = normalizeDataMode(input.dataMode);
  const auth = normalizeAuthProvider(input.authProvider);
  const api = sanitizeEndpoint(input.apiBaseUrl, "api", ["http:", "https:"]);
  const websocket = sanitizeEndpoint(input.websocketUrl, "websocket", ["ws:", "wss:"]);
  const browser = sanitizeEndpoint(input.browserOrigin ?? undefined, "browser", ["http:", "https:"]);
  const issues: SettingsDiagnosticIssue[] = [];

  if (profile !== "LOCAL_LAN") {
    issues.push({
      code: "PROFILE_MISMATCH",
      severity: "warning",
      title: "Неочікуваний профіль",
      message: `Очікується LOCAL_LAN, але налаштовано ${profile}.`,
    });
  }

  if (dataMode === "invalid") {
    issues.push({
      code: "INVALID_DATA_MODE",
      severity: "critical",
      title: "Невідомий режим даних",
      message: "NEXT_PUBLIC_NEXOLAB_DATA_MODE має бути live або demo.",
    });
  } else if (dataMode === "demo") {
    issues.push({
      code: "DEMO_MODE",
      severity: "warning",
      title: "Увімкнено demo mode",
      message: "Demo mode не замінює перевірений live runtime і не використовується як fallback.",
    });
  }

  if (auth.provider === "missing") {
    issues.push({
      code: "MISSING_AUTH_PROVIDER",
      severity: "warning",
      title: "Auth provider не вказано",
      message: "Вкажіть явний provider для контрольованого live deployment.",
    });
  } else if (auth.provider === "disabled" && dataMode === "live") {
    issues.push({
      code: "LIVE_AUTH_DISABLED",
      severity: "critical",
      title: "Автентифікацію вимкнено в live mode",
      message: "Live deployment не повинен мовчки працювати без перевіреної операторської сесії.",
    });
  }

  appendEndpointIssues(issues, api, dataMode === "live", "API NEXOLAB");
  appendEndpointIssues(issues, websocket, dataMode === "live", "Telemetry WebSocket");

  if (browser.configured && !browser.valid) {
    issues.push({
      code: "INVALID_BROWSER_ORIGIN",
      severity: "critical",
      title: "Некоректний browser origin",
      message: browser.error ?? "Browser origin не відповідає URL contract.",
    });
  }

  if (hasPublicUrlSecrets(api) || hasPublicUrlSecrets(websocket)) {
    issues.push({
      code: "PUBLIC_URL_SECRET_MATERIAL",
      severity: "critical",
      title: "Небезпечні дані у публічному URL",
      message:
        "Credentials, query parameters або fragments не повинні входити до client-visible runtime URL. Відображення очищене, але deployment configuration потрібно виправити.",
    });
  }

  if (isMixedContent(browser, api, websocket)) {
    issues.push({
      code: "MIXED_CONTENT",
      severity: "critical",
      title: "Несумісна схема підключення",
      message: "HTTPS dashboard не може безпечно звертатися до HTTP API або WS endpoint.",
    });
  }

  if (!browser.configured) {
    issues.push({
      code: "BROWSER_ORIGIN_PENDING",
      severity: "info",
      title: "Browser origin ще визначається",
      message: "Origin буде додано після клієнтської ініціалізації сторінки.",
    });
  }

  return {
    profile,
    dataMode,
    authProvider: auth.provider,
    authProviderLabel: auth.label,
    status: deriveStatus(issues),
    api,
    websocket,
    browser,
    issues,
    offlineFirst: true,
  };
}

export function sanitizeEndpoint(
  value: string | undefined,
  kind: SettingsEndpointKind,
  allowedProtocols: readonly string[],
): SanitizedSettingsEndpoint {
  const trimmed = value?.trim();
  if (!trimmed) {
    return {
      kind,
      configured: false,
      valid: false,
      displayValue: null,
      origin: null,
      pathname: null,
      protocol: null,
      redactions: [],
      error: null,
    };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return {
      kind,
      configured: true,
      valid: false,
      displayValue: null,
      origin: null,
      pathname: null,
      protocol: null,
      redactions: [],
      error: "Значення має бути абсолютним URL.",
    };
  }

  if (!allowedProtocols.includes(parsed.protocol)) {
    return {
      kind,
      configured: true,
      valid: false,
      displayValue: null,
      origin: null,
      pathname: null,
      protocol: parsed.protocol,
      redactions: [],
      error: `Дозволені схеми: ${allowedProtocols.join(", ")}.`,
    };
  }

  const redactions: string[] = [];
  if (parsed.username || parsed.password) redactions.push("credentials");
  if (parsed.search) redactions.push("query");
  if (parsed.hash) redactions.push("fragment");

  parsed.username = "";
  parsed.password = "";
  parsed.search = "";
  parsed.hash = "";

  const pathname = normalizePathname(parsed.pathname);
  const origin = parsed.origin;
  return {
    kind,
    configured: true,
    valid: true,
    displayValue: `${origin}${pathname === "/" ? "" : pathname}`,
    origin,
    pathname,
    protocol: parsed.protocol,
    redactions,
    error: null,
  };
}

function normalizeDataMode(value: string | undefined): SettingsDataMode {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "live" || normalized === "demo") return normalized;
  return "invalid";
}

function normalizeAuthProvider(value: string | undefined): {
  provider: SettingsAuthProvider;
  label: string;
} {
  const normalized = value?.trim().toLowerCase();
  if (!normalized) return { provider: "missing", label: "Не вказано" };
  if (normalized === "local") return { provider: "local", label: "Local" };
  if (normalized === "supabase") return { provider: "supabase", label: "Supabase" };
  if (normalized === "disabled") return { provider: "disabled", label: "Вимкнено" };
  if (SAFE_PROVIDER_PATTERN.test(normalized)) {
    return { provider: "custom", label: normalized };
  }
  return { provider: "custom", label: "Некоректне значення" };
}

function appendEndpointIssues(
  issues: SettingsDiagnosticIssue[],
  endpoint: SanitizedSettingsEndpoint,
  required: boolean,
  label: string,
): void {
  if (!endpoint.configured) {
    if (required) {
      issues.push({
        code: `MISSING_${endpoint.kind.toUpperCase()}_URL`,
        severity: "warning",
        title: `${label} не налаштовано`,
        message: `Для live mode потрібен client-visible ${label} URL.`,
      });
    }
    return;
  }

  if (!endpoint.valid) {
    issues.push({
      code: `INVALID_${endpoint.kind.toUpperCase()}_URL`,
      severity: "critical",
      title: `${label} має некоректний URL`,
      message: endpoint.error ?? "URL не відповідає runtime contract.",
    });
  }
}

function hasPublicUrlSecrets(endpoint: SanitizedSettingsEndpoint): boolean {
  return endpoint.redactions.length > 0;
}

function isMixedContent(
  browser: SanitizedSettingsEndpoint,
  api: SanitizedSettingsEndpoint,
  websocket: SanitizedSettingsEndpoint,
): boolean {
  if (!browser.valid || browser.protocol !== "https:") return false;
  return api.protocol === "http:" || websocket.protocol === "ws:";
}

function deriveStatus(issues: SettingsDiagnosticIssue[]): SettingsConfigurationState {
  if (issues.some((issue) => issue.severity === "critical")) return "unsafe";
  if (issues.some((issue) => issue.severity === "warning")) return "incomplete";
  return "ready";
}

function normalizePathname(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}
