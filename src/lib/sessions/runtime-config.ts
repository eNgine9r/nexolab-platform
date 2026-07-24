export class SessionClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "SessionClientError";
  }
}

export function getSessionsApiBaseUrl(): string {
  const mode = process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE?.trim() || "demo";
  if (mode !== "live") {
    throw new SessionClientError(
      "Sessions workspace requires NEXT_PUBLIC_NEXOLAB_DATA_MODE=live. Demo sessions are intentionally disabled.",
    );
  }

  const value = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
  if (!value) {
    throw new SessionClientError(
      "NEXT_PUBLIC_NEXOLAB_API_BASE_URL is required for the sessions workspace.",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw new SessionClientError("Sessions API URL must be an absolute URL.", undefined, {
      cause: error,
    } as ErrorOptions);
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new SessionClientError("Sessions API URL must use HTTP or HTTPS.");
  }

  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}
