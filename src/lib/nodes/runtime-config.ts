export class NodeClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "NodeClientError";
  }
}

export function getNodesApiBaseUrl(): string {
  const mode = process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE?.trim() || "demo";
  if (mode !== "live") {
    throw new NodeClientError(
      "Nodes workspace requires NEXT_PUBLIC_NEXOLAB_DATA_MODE=live.",
      undefined,
      "configuration",
    );
  }
  const value = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
  if (!value) {
    throw new NodeClientError(
      "NEXT_PUBLIC_NEXOLAB_API_BASE_URL is required for the nodes workspace.",
      undefined,
      "configuration",
    );
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw new NodeClientError("Nodes API URL must be absolute.", undefined, "configuration", {
      cause: error,
    });
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new NodeClientError("Nodes API URL must use HTTP or HTTPS.", undefined, "configuration");
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}
