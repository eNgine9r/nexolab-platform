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
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000] as const;
const DEFAULT_CONNECTION_TIMEOUT_MS = 15_000;
const CLIENT_AUTH_FAILURE_CLOSE_CODE = 4001;
const CLIENT_CONFIGURATION_FAILURE_CLOSE_CODE = 4002;

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

function classifyClose(code: number): TelemetryConnectionState | null {
  if (code === 4001 || code === 4401) return "unauthorized";
  if (code === 1008 || code === 4403) return "forbidden";
  if (code === 4002 || code === 4400) return "configuration_error";
  return null;
}

export class TelemetryWebSocketClient {
  private readonly createSocket: TelemetryWebSocketFactory;
  private readonly credentials: SecurityCredentialProvider | null;
  private readonly authenticationRequired: boolean;
  private readonly reconnectDelaysMs: readonly number[];
  private readonly maxSeenEventIds: number;
  private readonly connectionTimeoutMs: number;

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
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connectionTimer: ReturnType<typeof setTimeout> | null = null;
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
        if (expired) seenEventIds.delete(expired);
      }
    };

    const scheduleReconnect = () => {
      if (closed || terminalFailure || reconnectTimer !== null) return;
      if (reconnectAttempt >= this.reconnectDelaysMs.length) {
        setState("offline");
        reportError(
          new TelemetryClientError("websocket", "Telemetry WebSocket reconnect limit reached"),
          "Telemetry WebSocket reconnect limit reached",
        );
        return;
      }
      const delay = this.reconnectDelaysMs[reconnectAttempt];
      reconnectAttempt += 1;
      setState("reconnecting");
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (closed || terminalFailure) return;
      clearReconnectTimer();
      clearConnectionTimer();

      let socketUrl: string;
      try {
        socketUrl = buildUrl(this.websocketUrl, filters, lastCommittedCapturedAt);
      } catch (error) {
        terminalFailure = true;
        setState("configuration_error");
        reportError(error, "Telemetry WebSocket endpoint is invalid");
        return;
      }

      setState(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      const nextSocket = this.createSocket(socketUrl);
      socket = nextSocket;

      connectionTimer = setTimeout(() => {
        if (closed || socket !== nextSocket || lastState === "connected") return;
        reportError(
          new TelemetryClientError("websocket", "Telemetry WebSocket connection timed out"),
          "Telemetry WebSocket connection timed out",
        );
        nextSocket.close(4000, "telemetry connection timeout");
      }, this.connectionTimeoutMs);

      nextSocket.addEventListener("open", () => {
        if (closed || socket !== nextSocket) return;
        if (!this.authenticationRequired) {
          clearConnectionTimer();
          clearReconnectTimer();
          reconnectAttempt = 0;
          setState("connected");
          return;
        }
        if (!this.credentials) {
          terminalFailure = true;
          clearConnectionTimer();
          setState("configuration_error");
          reportError(
            new TelemetryClientError("websocket", "Telemetry credentials provider is not configured"),
            "Telemetry credentials provider is not configured",
          );
          nextSocket.close(CLIENT_CONFIGURATION_FAILURE_CLOSE_CODE, "telemetry credentials missing");
          return;
        }

        void Promise.resolve(this.credentials())
          .then((snapshot) => {
            if (closed || socket !== nextSocket) return;
            if (!snapshot.accessToken) {
              terminalFailure = true;
              setState("unauthorized");
              throw new TelemetryClientError("websocket", "Telemetry session is not authenticated");
            }
            if (!snapshot.organizationId) {
              terminalFailure = true;
              setState("configuration_error");
              throw new TelemetryClientError("websocket", "No active organization is selected");
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
            clearConnectionTimer();
            if (lastState !== "configuration_error") setState("unauthorized");
            reportError(error, "Telemetry WebSocket authentication failed");
            nextSocket.close(CLIENT_AUTH_FAILURE_CLOSE_CODE, "telemetry authentication failed");
          });
      });

      nextSocket.addEventListener("message", (event) => {
        if (closed || socket !== nextSocket) return;
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
            clearConnectionTimer();
            clearReconnectTimer();
            reconnectAttempt = 0;
            setState("connected");
            handlers.onHeartbeat?.(message.serverTime);
            return;
          }
          if (message.kind === "error") {
            handlers.onError?.(new TelemetryClientError("websocket", message.detail));
            return;
          }
          clearConnectionTimer();
          clearReconnectTimer();
          reconnectAttempt = 0;
          setState("connected");
          if (seenEventIds.has(message.sample.event_id)) return;
          handlers.onSample(message.sample);
          remember(message.sample.event_id);
          lastCommittedCapturedAt = message.sample.captured_at;
        } catch (error) {
          reportError(error, "Invalid WebSocket telemetry message");
        }
      });

      nextSocket.addEventListener("error", (event) => {
        if (!closed && socket === nextSocket) {
          reportError(event, "Telemetry WebSocket transport error");
        }
      });

      nextSocket.addEventListener("close", (event) => {
        clearConnectionTimer();
        if (socket === nextSocket) socket = null;
        if (closed) {
          setState("disconnected");
          return;
        }

        const closeEvent = event as CloseEvent;
        const classified = classifyClose(closeEvent.code);
        if (terminalFailure || classified) {
          terminalFailure = true;
          const state = classified ?? lastState ?? "offline";
          setState(state);
          if (closeEvent.reason) {
            reportError(
              new TelemetryClientError("websocket", closeEvent.reason),
              closeEvent.reason,
            );
          }
          return;
        }
        scheduleReconnect();
      });
    };

    setState("idle");
    connect();

    return {
      close: () => {
        if (closed) return;
        closed = true;
        clearReconnectTimer();
        clearConnectionTimer();
        const activeSocket = socket;
        socket = null;
        if (activeSocket) activeSocket.close(1000, "dashboard subscription closed");
        setState("disconnected");
      },
    };
  }
}
