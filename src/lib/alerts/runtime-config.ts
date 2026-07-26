export class AlertClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "AlertClientError";
  }
}

export function getAlertsApiBaseUrl(): string {
  const mode = process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE?.trim() || "demo";
  if (mode !== "live") {
    throw new AlertClientError(
      "Alerts workspace requires NEXT_PUBLIC_NEXOLAB_DATA_MODE=live. Demo alerts are intentionally disabled.",
      undefined,
      "configuration",
    );
  }

  const value = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
  if (!value) {
    throw new AlertClientError(
      "NEXT_PUBLIC_NEXOLAB_API_BASE_URL is required for the alerts workspace.",
      undefined,
      "configuration",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw new AlertClientError("Alerts API URL must be an absolute URL.", undefined, "configuration", {
      cause: error,
    });
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new AlertClientError("Alerts API URL must use HTTP or HTTPS.", undefined, "configuration");
  }

  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}
