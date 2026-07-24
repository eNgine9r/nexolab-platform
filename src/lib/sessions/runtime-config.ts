export class SessionClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "SessionClientError";
  }
}

export function getSessionsApiBaseUrl(): string {
  const mode = process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE?.trim() || "demo";
  if (mode !== "live") {
    throw new SessionClientError(
      "Sessions workspace requires NEXT_PUBLIC_NEXOLAB_DATA_MODE=live. Demo sessions are intentionally disabled.",
      undefined,
      "configuration",
    );
  }

  const value = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
  if (!value) {
    throw new SessionClientError(
      "NEXT_PUBLIC_NEXOLAB_API_BASE_URL is required for the sessions workspace.",
      undefined,
      "configuration",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw new SessionClientError("Sessions API URL must be an absolute URL.", undefined, "configuration", {
      cause: error,
    });
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new SessionClientError("Sessions API URL must use HTTP or HTTPS.", undefined, "configuration");
  }

  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}
