import type { SecurityCredentialProvider } from "@/features/security/security-session";

import { parseTelemetryLiveMessage } from "./contract";
import { TelemetryClientError } from "./errors";
import type {
  TelemetryConnectionState,
  TelemetryFilters,
  TelemetryLiveHandlers,
  TelemetrySubscription,
} from "./types";

export type TelemetryWebSocketFactory = (url: string) => WebSocket;

export interface TelemetryWebSocketClientOptions {
  createSocket?: TelemetryWebSocketFactory;
  credentials?: SecurityCredentialProvider;
  authenticationRequired?: boolean;
  reconnectDelaysMs?: readonly number[];
  maxSeenEventIds?: number;
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000] as const;
const CLIENT_AUTH_FAILURE_CLOSE_CODE = 4001;

function buildUrl(baseUrl: string, filters: TelemetryFilters, after: string | null): string {
  const url = new URL(baseUrl);
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }
  if (after) {
    url.searchParams.set("after", after);
  }
  return url.toString();
}

function runtimeAuthenticationRequired(): boolean {
  return process.env.NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER !== "disabled";
}

export class TelemetryWebSocketClient {
  private readonly createSocket: TelemetryWebSocketFactory;
  private readonly credentials: SecurityCredentialProvider | null;
  private readonly authenticationRequired: boolean;
  private readonly reconnectDelaysMs: readonly number[];
  private readonly maxSeenEventIds: number;

  constructor(
    private readonly websocketUrl: string,
    options: TelemetryWebSocketClientOptions = {},
  ) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.credentials = options.credentials ?? null;
    this.authenticationRequired = options.authenticationRequired ?? runtimeAuthenticationRequired();
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS;
    this.maxSeenEventIds = options.maxSeenEventIds ?? 10_000;
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;
    let closed = false;
    let terminalFailure = false;
    let lastState: TelemetryConnectionState | null = null;
    let lastCommittedCapturedAt: string | null = null;
    const seenEventIds = new Set<string>();
    const seenOrder: string[] = [];

    const setState = (state: TelemetryConnectionState) => {
      if (state !== lastState) {
        lastState = state;
        handlers.onStateChange?.(state);
      }
    };

    const reportError = (error: unknown, message: string) => {
      handlers.onError?.(
        error instanceof Error ? error : new TelemetryClientError("websocket", message, { cause: error }),
      );
    };

    const remember = (eventId: string) => {
      seenEventIds.add(eventId);
      seenOrder.push(eventId);
      while (seenOrder.length > this.maxSeenEventIds) {
        const expired = seenOrder.shift();
        if (expired) {
          seenEventIds.delete(expired);
        }
      }
    };

    const connect = () => {
      if (closed || terminalFailure) {
        return;
      }

      setState(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      const nextSocket = this.createSocket(buildUrl(this.websocketUrl, filters, lastCommittedCapturedAt));
      socket = nextSocket;

      nextSocket.addEventListener("open", () => {
        if (!this.authenticationRequired || !this.credentials) {
          reconnectAttempt = 0;
          setState("connected");
          return;
        }

        void Promise.resolve(this.credentials())
          .then((snapshot) => {
            if (closed || socket !== nextSocket) {
              return;
            }
            if (!snapshot.accessToken || !snapshot.organizationId) {
              throw new TelemetryClientError(
                "websocket",
                "Telemetry WebSocket requires an authenticated user and selected organization",
              );
            }
            nextSocket.send(
              JSON.stringify({
                type: "authenticate",
                access_token: snapshot.accessToken,
                organization_id: snapshot.organizationId,
              }),
            );
          })
          .catch((error: unknown) => {
            terminalFailure = true;
            reportError(error, "Telemetry WebSocket authentication failed");
            nextSocket.close(CLIENT_AUTH_FAILURE_CLOSE_CODE, "telemetry authentication failed");
          });
      });

      nextSocket.addEventListener("message", (event) => {
        try {
          const message = parseTelemetryLiveMessage(JSON.parse(String(event.data)) as unknown);
          if (message.kind === "authenticated") {
            reconnectAttempt = 0;
            setState("connected");
            return;
          }
          if (message.kind === "heartbeat") {
            handlers.onHeartbeat?.(message.serverTime);
            return;
          }
          if (message.kind === "error") {
            handlers.onError?.(new TelemetryClientError("websocket", message.detail));
            return;
          }
          if (seenEventIds.has(message.sample.event_id)) {
            return;
          }

          handlers.onSample(message.sample);
          remember(message.sample.event_id);
          lastCommittedCapturedAt = message.sample.captured_at;
        } catch (error) {
          reportError(error, "Invalid WebSocket telemetry message");
        }
      });

      nextSocket.addEventListener("error", (event) => {
        reportError(event, "Telemetry WebSocket transport error");
      });

      nextSocket.addEventListener("close", (event) => {
        if (socket === nextSocket) {
          socket = null;
        }
        if (closed || terminalFailure) {
          setState("disconnected");
          return;
        }

        const closeEvent = event as CloseEvent;
        if (closeEvent.code === 1008) {
          setState("disconnected");
          handlers.onError?.(
            new TelemetryClientError(
              "websocket",
              closeEvent.reason || "Telemetry WebSocket access was denied",
            ),
          );
          return;
        }

        if (reconnectAttempt >= this.reconnectDelaysMs.length) {
          setState("disconnected");
          handlers.onError?.(
            new TelemetryClientError("websocket", "Telemetry WebSocket reconnect limit reached"),
          );
          return;
        }

        const delay = this.reconnectDelaysMs[reconnectAttempt];
        reconnectAttempt += 1;
        setState("reconnecting");
        reconnectTimer = setTimeout(connect, delay);
      });
    };

    connect();

    return {
      close: () => {
        closed = true;
        if (reconnectTimer !== null) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        socket?.close(1000, "dashboard subscription closed");
        socket = null;
        setState("disconnected");
      },
    };
  }
}
