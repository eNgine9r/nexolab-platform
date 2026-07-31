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
  connectionTimeoutMs?: number;
  heartbeatTimeoutMs?: number;
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000] as const;
const DEFAULT_CONNECTION_TIMEOUT_MS = 10_000;
const DEFAULT_HEARTBEAT_TIMEOUT_MS = 45_000;
const CLIENT_HEARTBEAT_TIMEOUT_CLOSE_CODE = 4000;
const CLIENT_AUTH_FAILURE_CLOSE_CODE = 4001;
const CLIENT_CONNECTION_TIMEOUT_CLOSE_CODE = 4002;

function buildUrl(baseUrl: string, filters: TelemetryFilters, after: string | null): string {
  const url = new URL(baseUrl);
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new TelemetryClientError(
      "websocket",
      "Telemetry WebSocket endpoint must use ws:// or wss://",
    );
  }
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

function terminalStateForClose(event: CloseEvent): TelemetryConnectionState | null {
  const reason = event.reason.toLowerCase();
  if (
    event.code === CLIENT_AUTH_FAILURE_CLOSE_CODE ||
    event.code === 4401 ||
    reason.includes("unauthorized") ||
    reason.includes("token") ||
    reason.includes("authentication failed")
  ) {
    return "unauthorized";
  }
  if (
    event.code === 1008 ||
    event.code === 4003 ||
    event.code === 4403 ||
    reason.includes("access denied") ||
    reason.includes("forbidden") ||
    reason.includes("organization required")
  ) {
    return "forbidden";
  }
  return null;
}

export class TelemetryWebSocketClient {
  private readonly createSocket: TelemetryWebSocketFactory;
  private readonly credentials: SecurityCredentialProvider | null;
  private readonly authenticationRequired: boolean;
  private readonly reconnectDelaysMs: readonly number[];
  private readonly maxSeenEventIds: number;
  private readonly connectionTimeoutMs: number;
  private readonly heartbeatTimeoutMs: number;

  constructor(
    private readonly websocketUrl: string,
    options: TelemetryWebSocketClientOptions = {},
  ) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.credentials = options.credentials ?? null;
    this.authenticationRequired = options.authenticationRequired ?? runtimeAuthenticationRequired();
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS;
    this.maxSeenEventIds = options.maxSeenEventIds ?? 10_000;
    this.connectionTimeoutMs = options.connectionTimeoutMs ?? DEFAULT_CONNECTION_TIMEOUT_MS;
    this.heartbeatTimeoutMs = options.heartbeatTimeoutMs ?? DEFAULT_HEARTBEAT_TIMEOUT_MS;
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connectionTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;
    let connectionGeneration = 0;
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

    const clearReconnectTimer = () => {
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const clearConnectionTimer = () => {
      if (connectionTimer !== null) {
        clearTimeout(connectionTimer);
        connectionTimer = null;
      }
    };

    const clearHeartbeatTimer = () => {
      if (heartbeatTimer !== null) {
        clearTimeout(heartbeatTimer);
        heartbeatTimer = null;
      }
    };

    const clearSocketTimers = () => {
      clearConnectionTimer();
      clearHeartbeatTimer();
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

    const armHeartbeatTimeout = (nextSocket: WebSocket, generation: number) => {
      clearHeartbeatTimer();
      heartbeatTimer = setTimeout(() => {
        if (closed || socket !== nextSocket || generation !== connectionGeneration) {
          return;
        }
        setState("reconnecting");
        handlers.onError?.(
          new TelemetryClientError("websocket", "Telemetry WebSocket heartbeat timed out"),
        );
        nextSocket.close(CLIENT_HEARTBEAT_TIMEOUT_CLOSE_CODE, "heartbeat timeout");
      }, this.heartbeatTimeoutMs);
    };

    const connect = () => {
      if (closed || terminalFailure) {
        return;
      }
      if (socket && (socket.readyState === 0 || socket.readyState === 1)) {
        return;
      }

      clearReconnectTimer();
      clearSocketTimers();
      const generation = ++connectionGeneration;
      setState(reconnectAttempt === 0 ? "connecting" : "reconnecting");

      let nextSocket: WebSocket;
      try {
        nextSocket = this.createSocket(
          buildUrl(this.websocketUrl, filters, lastCommittedCapturedAt),
        );
      } catch (error) {
        terminalFailure = true;
        setState("configuration_error");
        reportError(error, "Telemetry WebSocket endpoint is not configured correctly");
        return;
      }
      socket = nextSocket;
      connectionTimer = setTimeout(() => {
        if (closed || socket !== nextSocket || generation !== connectionGeneration) {
          return;
        }
        handlers.onError?.(
          new TelemetryClientError("websocket", "Telemetry WebSocket connection timed out"),
        );
        nextSocket.close(CLIENT_CONNECTION_TIMEOUT_CLOSE_CODE, "connection timeout");
      }, this.connectionTimeoutMs);

      nextSocket.addEventListener("open", () => {
        if (closed || socket !== nextSocket || generation !== connectionGeneration) {
          return;
        }
        if (!this.authenticationRequired) {
          clearConnectionTimer();
          clearReconnectTimer();
          reconnectAttempt = 0;
          setState("connected");
          armHeartbeatTimeout(nextSocket, generation);
          return;
        }
        if (!this.credentials) {
          terminalFailure = true;
          clearSocketTimers();
          setState("configuration_error");
          handlers.onError?.(
            new TelemetryClientError(
              "websocket",
              "Telemetry authentication is enabled but no credential provider is configured",
            ),
          );
          nextSocket.close(CLIENT_AUTH_FAILURE_CLOSE_CODE, "credential provider missing");
          return;
        }

        void Promise.resolve(this.credentials())
          .then((snapshot) => {
            if (closed || socket !== nextSocket || generation !== connectionGeneration) {
              return;
            }
            if (!snapshot.accessToken) {
              throw new TelemetryClientError(
                "websocket",
                "Telemetry WebSocket requires an authenticated user",
              );
            }
            if (!snapshot.organizationId) {
              throw new TelemetryClientError(
                "websocket",
                "Telemetry WebSocket requires a selected organization",
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
            if (closed || socket !== nextSocket || generation !== connectionGeneration) {
              return;
            }
            terminalFailure = true;
            clearSocketTimers();
            setState("unauthorized");
            reportError(error, "Telemetry WebSocket authentication failed");
            nextSocket.close(CLIENT_AUTH_FAILURE_CLOSE_CODE, "telemetry authentication failed");
          });
      });

      nextSocket.addEventListener("message", (event) => {
        if (closed || socket !== nextSocket || generation !== connectionGeneration) {
          return;
        }
        armHeartbeatTimeout(nextSocket, generation);
        try {
          const message = parseTelemetryLiveMessage(JSON.parse(String(event.data)) as unknown);
          if (message.kind === "authenticated") {
            clearConnectionTimer();
            clearReconnectTimer();
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
        if (closed || socket !== nextSocket || generation !== connectionGeneration) {
          return;
        }
        reportError(event, "Telemetry WebSocket transport error");
      });

      nextSocket.addEventListener("close", (event) => {
        if (generation !== connectionGeneration) {
          return;
        }
        clearSocketTimers();
        if (socket === nextSocket) {
          socket = null;
        }
        if (closed) {
          setState("disconnected");
          return;
        }
        if (terminalFailure) {
          return;
        }

        const closeEvent = event as CloseEvent;
        const terminalState = terminalStateForClose(closeEvent);
        if (terminalState !== null) {
          terminalFailure = true;
          setState(terminalState);
          handlers.onError?.(
            new TelemetryClientError(
              "websocket",
              closeEvent.reason || "Telemetry WebSocket access was denied",
            ),
          );
          return;
        }

        if (reconnectAttempt >= this.reconnectDelaysMs.length) {
          setState("offline");
          handlers.onError?.(
            new TelemetryClientError("websocket", "Telemetry WebSocket reconnect limit reached"),
          );
          return;
        }

        const delay = this.reconnectDelaysMs[reconnectAttempt];
        reconnectAttempt += 1;
        setState("reconnecting");
        clearReconnectTimer();
        reconnectTimer = setTimeout(connect, delay);
      });
    };

    connect();

    return {
      close: () => {
        if (closed) {
          return;
        }
        closed = true;
        connectionGeneration += 1;
        clearReconnectTimer();
        clearSocketTimers();
        const activeSocket = socket;
        socket = null;
        if (activeSocket && activeSocket.readyState !== 3) {
          activeSocket.close(1000, "dashboard subscription closed");
        }
        setState("disconnected");
      },
    };
  }
}
