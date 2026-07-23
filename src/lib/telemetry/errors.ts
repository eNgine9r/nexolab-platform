export type TelemetryErrorCode =
  | "configuration"
  | "timeout"
  | "aborted"
  | "network"
  | "http"
  | "contract"
  | "websocket";

export interface TelemetryClientErrorOptions {
  status?: number;
  cause?: unknown;
}

export class TelemetryClientError extends Error {
  readonly code: TelemetryErrorCode;
  readonly status?: number;

  constructor(
    code: TelemetryErrorCode,
    message: string,
    options: TelemetryClientErrorOptions = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "TelemetryClientError";
    this.code = code;
    this.status = options.status;
  }
}

export function asTelemetryError(
  error: unknown,
  fallbackMessage: string,
): TelemetryClientError {
  if (error instanceof TelemetryClientError) {
    return error;
  }

  return new TelemetryClientError("network", fallbackMessage, {
    cause: error,
  });
}
