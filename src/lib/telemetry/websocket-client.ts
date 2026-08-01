import type {
  SecurityCredentialProvider,
  SecurityCredentialSnapshot,
} from "@/features/security/security-session";

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
  connectionTimeoutMs?: number;
  authenticationTimeoutMs?: number;
  heartbeatTimeoutMs?: number;
  maxSeenEventIds?: number;
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000] as const;
const DEFAULT_CONNECTION_TIMEOUT_MS = 15_000;
const DEFAULT_AUTHENTICATION_TIMEOUT_MS = 10_000;
const DEFAULT_HEARTBEAT_TIMEOUT_MS = 45_000;

const CLIENT_HEARTBEAT_TIMEOUT_CLOSE_CODE = 4000;
const CLIENT_AUTH_FAILURE_CLOSE_CODE = 4001;
const CLIENT_CONNECTION_TIMEOUT_CLOSE_CODE = 4002;
const CLIENT_FORBIDDEN_CLOSE_CODE = 4003;
const CLIENT_CONFIGURATION_CLOSE_CODE = 4004;
const SERVER_UNAUTHORIZED_CLOSE_CODE = 4401;
const SERVER_FORBIDDEN_CLOSE_CODE = 4403;
const SERVER_CONFIGURATION_CLOSE_CODE = 4400;

function buildUrl(baseUrl: string, filters: TelemetryFilters, after: string | null): string {
  const url = new URL(baseUrl);
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  if (after) url.searchParams.set("after", after);
  return url.toString();
}

function validateWebSocketUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch (error) {
    throw new TelemetryClientError("configuration", "Telemetry WebSocket URL must be absolute", {
      cause: error,
    });
  }
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new TelemetryClientError("configuration", "Telemetry WebSocket URL must use ws: or wss:");
  }
  return url.toString();
}

function sanitizedUrl(value: string): string {
  const url = new URL(value);
  for (const key of ["access_token", "token", "authorization"]) {
    url.searchParams.delete(key);
  }
  return url.toString();
}

function runtimeAuthenticationRequired(): boolean {
  const provider = process.env.NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER?.trim();
  return Boolean(provider && provider !== "disabled");
}

function serverErrorState(code: string, detail: string): TelemetryConnectionState | null {
  const normalized = `${code} ${detail}`.toLowerCase();
  if (
    normalized.includes("organization_header_required") ||
    normalized.includes("organization required") ||
    normalized.includes("configuration")
  ) {
    return "configuration_error";
  }
  if (
    normalized.includes("membership") ||
    normalized.includes("permission") ||
    normalized.includes("forbidden") ||
    normalized.includes("access denied")
  ) {
    return "forbidden";
  }
  if (
    normalized.includes("token") ||
    normalized.includes("authentication") ||
    normalized.includes("unauthorized") ||
    normalized.includes("session")
  ) {
    return "unauthorized";
  }
  return null;
}

function closeState(code: number, reason: string): TelemetryConnectionState | null {
  if (code === SERVER_CONFIGURATION_CLOSE_CODE || code === CLIENT_CONFIGURATION_CLOSE_CODE) {
    return "configuration_error";
  }
  if (code === SERVER_UNAUTHORIZED_CLOSE_CODE || code === CLIENT_AUTH_FAILURE_CLOSE_CODE) {
    return "unauthorized";
  }
  if (code === SERVER_FORBIDDEN_CLOSE_CODE || code === CLIENT_FORBIDDEN_CLOSE_CODE) {
    return "forbidden";
  }
  if (code === 1008) return serverErrorState("policy_violation", reason) ?? "forbidden";
  return null;
}

function closeCodeFor(state: TelemetryConnectionState): number {
  if (state === "unauthorized") return CLIENT_AUTH_FAILURE_CLOSE_CODE;
  if (state === "forbidden") return CLIENT_FORBIDDEN_CLOSE_CODE;
  return CLIENT_CONFIGURATION_CLOSE_CODE;
}

function credentialsError(snapshot: SecurityCredentialSnapshot): {
  state: TelemetryConnectionState;
  message: string;
} | null {
  if (!snapshot.accessToken) {
    return {
      state: "unauthorized",
      message: "Telemetry WebSocket requires an authenticated user session",
    };
  }
  if (!snapshot.organizationId) {
    return {
      state: "configuration_error",
      message: "Telemetry WebSocket requires a selected organization",
    };
  }
  return null;
}

export class TelemetryWebSocketClient {
  private readonly createSocket: TelemetryWebSocketFactory;
  private readonly credentials: SecurityCredentialProvider | null;
  private readonly authenticationRequired: boolean;
  private readonly reconnectDelaysMs: readonly number[];
  private readonly connectionTimeoutMs: number;
  private readonly authenticationTimeoutMs: number;
  private readonly heartbeatTimeoutMs: number;
  private readonly maxSeenEventIds: number;
  private readonly websocketUrl: string;

  constructor(websocketUrl: string, options: TelemetryWebSocketClientOptions = {}) {
    this.websocketUrl = validateWebSocketUrl(websocketUrl);
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.credentials = options.credentials ?? null;
    this.authenticationRequired = options.authenticationRequired ?? runtimeAuthenticationRequired();
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS;
    this.connectionTimeoutMs = options.connectionTimeoutMs ?? DEFAULT_CONNECTION_TIMEOUT_MS;
    this.authenticationTimeoutMs = options.authenticationTimeoutMs ?? DEFAULT_AUTHENTICATION_TIMEOUT_MS;
    this.heartbeatTimeoutMs = options.heartbeatTimeoutMs ?? DEFAULT_HEARTBEAT_TIMEOUT_MS;
    this.maxSeenEventIds = options.maxSeenEventIds ?? 10_000;
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connectionTimer: ReturnType<typeof setTimeout> | null = null;
    let authenticationTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;
    let closed = false;
    let terminalState: TelemetryConnectionState | null = null;
    let lastState: TelemetryConnectionState | null = null;
    let lastCommittedCapturedAt: string | null = null;
    let lastMessageAt: string | null = null;
    const seenEventIds = new Set<string>();
    const seenOrder: string[] = [];

    const setState = (state: TelemetryConnectionState) => {
      if (state === lastState) return;
      lastState = state;
      handlers.onStateChange?.(state);
    };

    const reportError = (error: unknown, message: string) => {
      handlers.onError?.(
        error instanceof Error ? error : new TelemetryClientError("websocket", message, { cause: error }),
      );
    };

    const clearTimer = (timer: ReturnType<typeof setTimeout> | null) => {
      if (timer !== null) clearTimeout(timer);
    };
    const clearReconnectTimer = () => {
      clearTimer(reconnectTimer);
      reconnectTimer = null;
    };
    const clearConnectionTimer = () => {
      clearTimer(connectionTimer);
      connectionTimer = null;
    };
    const clearAuthenticationTimer = () => {
      clearTimer(authenticationTimer);
      authenticationTimer = null;
    };
    const clearHeartbeatTimer = () => {
      clearTimer(heartbeatTimer);
      heartbeatTimer = null;
    };
    const clearAttemptTimers = () => {
      clearConnectionTimer();
      clearAuthenticationTimer();
      clearHeartbeatTimer();
    };

    const remember = (eventId: string) => {
      seenEventIds.add(eventId);
      seenOrder.push(eventId);
      while (seenOrder.length > this.maxSeenEventIds) {
        const expired = seenOrder.shift();
        if (expired) seenEventIds.delete(expired);
      }
    };

    const markMessage = (messageKind: "authenticated" | "heartbeat" | "sample" | "error") => {
      lastMessageAt = new Date().toISOString();
      handlers.onDiagnostic?.({ type: "message", receivedAt: lastMessageAt, messageKind });
    };

    const armHeartbeatTimeout = (nextSocket: WebSocket) => {
      clearHeartbeatTimer();
      if (this.heartbeatTimeoutMs <= 0 || closed || socket !== nextSocket) return;
      heartbeatTimer = setTimeout(() => {
        heartbeatTimer = null;
        if (closed || terminalState || socket !== nextSocket) return;
        handlers.onDiagnostic?.({
          type: "heartbeat_timeout",
          timeoutMs: this.heartbeatTimeoutMs,
          lastMessageAt,
        });
        setState("reconnecting");
        nextSocket.close(CLIENT_HEARTBEAT_TIMEOUT_CLOSE_CODE, "heartbeat timeout");
      }, this.heartbeatTimeoutMs);
    };

    const markConnected = (nextSocket: WebSocket, organizationId: string | null, attempt: number) => {
      if (closed || socket !== nextSocket) return;
      clearReconnectTimer();
      clearConnectionTimer();
      clearAuthenticationTimer();
      reconnectAttempt = 0;
      setState("connected");
      handlers.onDiagnostic?.({
        type: "connected",
        url: sanitizedUrl(nextSocket.url || this.websocketUrl),
        reconnectAttempt: attempt,
        organizationId,
      });
      armHeartbeatTimeout(nextSocket);
    };

    const failTerminal = (
      state: TelemetryConnectionState,
      error: unknown,
      message: string,
      nextSocket?: WebSocket,
    ) => {
      terminalState = state;
      clearReconnectTimer();
      clearAttemptTimers();
      setState(state);
      reportError(error, message);
      if (nextSocket && socket === nextSocket) {
        nextSocket.close(closeCodeFor(state), message.slice(0, 120));
      }
    };

    const scheduleReconnect = (connect: () => void) => {
      if (closed || terminalState || reconnectTimer !== null) return;
      if (reconnectAttempt >= this.reconnectDelaysMs.length) {
        setState("offline");
        reportError(
          new TelemetryClientError("websocket", "Telemetry WebSocket reconnect limit reached"),
          "Telemetry WebSocket reconnect limit reached",
        );
        return;
      }
      const delayMs = this.reconnectDelaysMs[reconnectAttempt];
      reconnectAttempt += 1;
      setState("reconnecting");
      handlers.onDiagnostic?.({
        type: "reconnect_scheduled",
        reconnectAttempt,
        delayMs,
        lastMessageAt,
      });
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delayMs);
    };

    const connect = () => {
      if (closed || terminalState) return;
      clearReconnectTimer();
      clearAttemptTimers();
      const attempt = reconnectAttempt;
      setState(attempt === 0 ? "connecting" : "reconnecting");

      void Promise.resolve()
        .then(async () => {
          let credentials: SecurityCredentialSnapshot | null = null;
          if (this.authenticationRequired) {
            if (!this.credentials) {
              failTerminal(
                "configuration_error",
                new TelemetryClientError(
                  "configuration",
                  "Telemetry WebSocket authentication is enabled without a credential provider",
                ),
                "Telemetry WebSocket credential provider is not configured",
              );
              return;
            }
            try {
              credentials = await this.credentials();
            } catch (error) {
              failTerminal("unauthorized", error, "Telemetry WebSocket could not refresh the user session");
              return;
            }
            const issue = credentialsError(credentials);
            if (issue) {
              failTerminal(issue.state, new TelemetryClientError("websocket", issue.message), issue.message);
              return;
            }
          }

          if (closed || terminalState) return;
          const url = buildUrl(this.websocketUrl, filters, lastCommittedCapturedAt);
          handlers.onDiagnostic?.({
            type: "connect_start",
            url: sanitizedUrl(url),
            reconnectAttempt: attempt,
            organizationId: credentials?.organizationId ?? null,
          });

          let nextSocket: WebSocket;
          try {
            nextSocket = this.createSocket(url);
          } catch (error) {
            reportError(error, "Telemetry WebSocket transport could not be created");
            scheduleReconnect(connect);
            return;
          }

          const previousSocket = socket;
          socket = nextSocket;
          if (previousSocket && previousSocket !== nextSocket) {
            previousSocket.close(1000, "superseded telemetry connection");
          }

          if (this.connectionTimeoutMs > 0) {
            connectionTimer = setTimeout(() => {
              connectionTimer = null;
              if (closed || terminalState || socket !== nextSocket) return;
              reportError(
                new TelemetryClientError("websocket", "Telemetry WebSocket connection timed out"),
                "Telemetry WebSocket connection timed out",
              );
              nextSocket.close(CLIENT_CONNECTION_TIMEOUT_CLOSE_CODE, "telemetry connection timeout");
            }, this.connectionTimeoutMs);
          }

          nextSocket.addEventListener("open", () => {
            if (closed || socket !== nextSocket) return;
            clearConnectionTimer();
            if (!this.authenticationRequired) {
              armHeartbeatTimeout(nextSocket);
              return;
            }

            const snapshot = credentials;
            if (!snapshot?.accessToken || !snapshot.organizationId) {
              failTerminal(
                "configuration_error",
                new TelemetryClientError("websocket", "Telemetry credentials disappeared before connect"),
                "Telemetry WebSocket credentials are incomplete",
                nextSocket,
              );
              return;
            }

            nextSocket.send(
              JSON.stringify({
                type: "authenticate",
                access_token: snapshot.accessToken,
                organization_id: snapshot.organizationId,
              }),
            );
            clearAuthenticationTimer();
            authenticationTimer = setTimeout(() => {
              authenticationTimer = null;
              if (closed || terminalState || socket !== nextSocket) return;
              failTerminal(
                "unauthorized",
                new TelemetryClientError(
                  "websocket",
                  "Telemetry WebSocket authentication acknowledgement timed out",
                ),
                "Telemetry WebSocket authentication timed out",
                nextSocket,
              );
            }, this.authenticationTimeoutMs);
          });

          nextSocket.addEventListener("message", (event) => {
            if (closed || socket !== nextSocket) return;
            try {
              const message = parseTelemetryLiveMessage(JSON.parse(String(event.data)) as unknown);
              markMessage(message.kind);

              if (message.kind === "authenticated") {
                const expectedOrganizationId = credentials?.organizationId ?? null;
                if (expectedOrganizationId && message.organizationId !== expectedOrganizationId) {
                  failTerminal(
                    "forbidden",
                    new TelemetryClientError(
                      "websocket",
                      "Telemetry WebSocket organization acknowledgement does not match the selected organization",
                    ),
                    "Telemetry WebSocket organization scope mismatch",
                    nextSocket,
                  );
                  return;
                }
                markConnected(nextSocket, message.organizationId, attempt);
                return;
              }

              if (message.kind === "heartbeat") {
                if (lastState !== "connected") {
                  markConnected(nextSocket, credentials?.organizationId ?? null, attempt);
                } else {
                  armHeartbeatTimeout(nextSocket);
                }
                handlers.onHeartbeat?.(message.serverTime);
                return;
              }

              if (message.kind === "error") {
                const state = serverErrorState(message.code, message.detail);
                const error = new TelemetryClientError("websocket", message.detail);
                if (state) failTerminal(state, error, message.detail, nextSocket);
                else {
                  handlers.onError?.(error);
                  armHeartbeatTimeout(nextSocket);
                }
                return;
              }

              if (lastState !== "connected") {
                markConnected(nextSocket, credentials?.organizationId ?? null, attempt);
              } else {
                armHeartbeatTimeout(nextSocket);
              }
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
            if (socket !== nextSocket) return;
            socket = null;
            clearAttemptTimers();
            const closeEvent = event as CloseEvent;

            if (closed) {
              setState("idle");
              return;
            }
            if (terminalState) {
              handlers.onDiagnostic?.({
                type: "closed",
                code: closeEvent.code,
                reason: closeEvent.reason,
                state: terminalState,
                lastMessageAt,
              });
              setState(terminalState);
              return;
            }

            const failureState = closeState(closeEvent.code, closeEvent.reason);
            if (failureState) {
              terminalState = failureState;
              setState(failureState);
              handlers.onDiagnostic?.({
                type: "closed",
                code: closeEvent.code,
                reason: closeEvent.reason,
                state: failureState,
                lastMessageAt,
              });
              handlers.onError?.(
                new TelemetryClientError(
                  "websocket",
                  closeEvent.reason || "Telemetry WebSocket access was denied",
                ),
              );
              return;
            }

            handlers.onDiagnostic?.({
              type: "closed",
              code: closeEvent.code,
              reason: closeEvent.reason,
              state: "reconnecting",
              lastMessageAt,
            });
            scheduleReconnect(connect);
          });
        })
        .catch((error: unknown) => {
          if (closed || terminalState) return;
          reportError(error, "Telemetry WebSocket connection failed");
          scheduleReconnect(connect);
        });
    };

    setState("idle");
    connect();

    return {
      close: () => {
        if (closed) return;
        closed = true;
        terminalState = null;
        clearReconnectTimer();
        clearAttemptTimers();
        const currentSocket = socket;
        socket = null;
        currentSocket?.close(1000, "dashboard subscription closed");
        setState("idle");
      },
    };
  }
}
