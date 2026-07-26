from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    if old not in content:
        raise RuntimeError(f"Expected content was not found in {path}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "services/telemetry-service/app/config.py",
    "    websocket_send_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)\n    websocket_resume_limit: int = Field(default=1000, ge=1, le=10_000)\n",
    "    websocket_send_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)\n    websocket_auth_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)\n    websocket_resume_limit: int = Field(default=1000, ge=1, le=10_000)\n",
)

replace_once(
    "infrastructure/compose/compose.central.yaml",
    "  WEBSOCKET_SEND_TIMEOUT_SECONDS: ${WEBSOCKET_SEND_TIMEOUT_SECONDS:-5}\n  WEBSOCKET_RESUME_LIMIT: ${WEBSOCKET_RESUME_LIMIT:-1000}\n",
    "  WEBSOCKET_SEND_TIMEOUT_SECONDS: ${WEBSOCKET_SEND_TIMEOUT_SECONDS:-5}\n  WEBSOCKET_AUTH_TIMEOUT_SECONDS: ${WEBSOCKET_AUTH_TIMEOUT_SECONDS:-5}\n  WEBSOCKET_RESUME_LIMIT: ${WEBSOCKET_RESUME_LIMIT:-1000}\n",
)

replace_once(
    "services/telemetry-service/app/main.py",
    "            heartbeat_seconds=resolved.websocket_heartbeat_seconds,\n            send_timeout_seconds=resolved.websocket_send_timeout_seconds,\n            resume_limit=resolved.websocket_resume_limit,\n",
    "            heartbeat_seconds=resolved.websocket_heartbeat_seconds,\n            send_timeout_seconds=resolved.websocket_send_timeout_seconds,\n            auth_timeout_seconds=resolved.websocket_auth_timeout_seconds,\n            resume_limit=resolved.websocket_resume_limit,\n            security_dependencies=security_dependencies,\n",
)

path = "services/telemetry-service/app/security/dependencies.py"
content = read(path)
content = content.replace(
    "        self._default_organization_id = default_organization_id\n\n    def current_session(\n",
    "        self._default_organization_id = default_organization_id\n\n    @property\n    def authentication_required(self) -> bool:\n        return self._mode == \"jwt\"\n\n    def current_session(\n",
    1,
)
start = content.index("    def authorized_request(")
end = content.index("    def _verify(", start)
new_authorization = '''    def authorized_request(
        self,
        permission: Permission,
    ) -> Callable[..., AuthorizedRequest]:
        def dependency(
            authorization: str | None = Header(default=None, alias="Authorization"),
            selected_organization_id: str | None = Header(
                default=None,
                alias="X-Organization-ID",
            ),
        ) -> AuthorizedRequest:
            return self.authorize_credentials(
                authorization,
                selected_organization_id,
                permission,
            )

        return dependency

    def authorize_credentials(
        self,
        authorization: str | None,
        selected_organization_id: str | None,
        permission: Permission,
    ) -> AuthorizedRequest:
        resolved_organization_id = self._resolve_organization_id(
            selected_organization_id
        )
        if self._mode == "disabled":
            principal = AuthenticatedPrincipal(
                subject="development-system",
                organization_id=resolved_organization_id,
                roles=frozenset({Role.ADMINISTRATOR}),
                display_name="Development system",
                provider="disabled",
            )
            identity_id: str | None = None
        else:
            claims = self._verify(authorization)
            try:
                identity_id, principal = self._repository.resolve_principal(
                    claims,
                    organization_id=resolved_organization_id,
                )
            except IdentityNotProvisionedError as error:
                raise _forbidden(error.code, str(error)) from error
            except OrganizationMembershipNotFoundError as error:
                raise _forbidden(error.code, str(error)) from error

        decision = authorize(
            principal,
            permission,
            resource_organization_id=resolved_organization_id,
        )
        if not decision.allowed:
            raise _forbidden(
                decision.code,
                f"permission {permission.value!r} is required",
            )
        return AuthorizedRequest(identity_id=identity_id, principal=principal)

'''
write(path, content[:start] + new_authorization + content[end:])

write(
    "services/telemetry-service/app/live_api.py",
    '''from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.db import Database, TelemetryQuery, TelemetrySample
from app.live import OVERFLOW, SHUTDOWN, LiveTelemetryFilter, LiveTelemetryHub
from app.security.authorization import Permission
from app.security.dependencies import SecurityDependencies
from app.state import RuntimeState

ALLOWED_QUALITIES = {
    "valid",
    "sensor_error",
    "communication_error",
    "unknown",
}
ALLOWED_ALARMS = {"low", "high"}


def _sample_payload(sample: TelemetrySample) -> dict[str, Any]:
    payload = dict(sample.raw_payload)
    payload.update(
        {
            "event_id": sample.event_id,
            "node_id": sample.node_id,
            "captured_at": sample.captured_at.isoformat(),
            "metric": sample.metric,
            "value": sample.value,
            "unit": sample.unit,
            "quality": sample.quality,
            "source": sample.source,
            "equipment_id": sample.equipment_id,
            "channel_id": sample.channel_id,
            "alarm": sample.alarm,
            "raw_value": sample.raw_value,
            "raw_status": sample.raw_status,
        }
    )
    return payload


def _parse_after(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    return parsed.astimezone(UTC)


def _http_error(error: HTTPException) -> tuple[str, str]:
    if isinstance(error.detail, dict):
        code = str(error.detail.get("code") or "websocket_access_denied")
        message = str(error.detail.get("message") or "WebSocket access denied")
        return code, message
    return "websocket_access_denied", str(error.detail)


async def _authenticate_websocket(
    websocket: WebSocket,
    security_dependencies: SecurityDependencies | None,
    *,
    timeout_seconds: float,
) -> bool:
    if security_dependencies is None or not security_dependencies.authentication_required:
        return True

    try:
        payload = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        await websocket.send_json(
            {
                "type": "error",
                "code": "websocket_authentication_timeout",
                "detail": "Telemetry authentication message was not received in time",
            }
        )
        await websocket.close(code=1008, reason="authentication timeout")
        return False
    except WebSocketDisconnect:
        return False
    except Exception:
        await websocket.send_json(
            {
                "type": "error",
                "code": "invalid_websocket_authentication",
                "detail": "Telemetry authentication payload must be valid JSON",
            }
        )
        await websocket.close(code=1008, reason="invalid authentication payload")
        return False

    if not isinstance(payload, dict) or payload.get("type") != "authenticate":
        await websocket.send_json(
            {
                "type": "error",
                "code": "invalid_websocket_authentication",
                "detail": "The first WebSocket message must authenticate the session",
            }
        )
        await websocket.close(code=1008, reason="authentication required")
        return False

    access_token = payload.get("access_token")
    organization_id = payload.get("organization_id")
    if not isinstance(access_token, str) or not access_token.strip():
        await websocket.send_json(
            {
                "type": "error",
                "code": "missing_bearer_token",
                "detail": "A non-empty access token is required",
            }
        )
        await websocket.close(code=1008, reason="authentication required")
        return False
    if not isinstance(organization_id, str) or not organization_id.strip():
        await websocket.send_json(
            {
                "type": "error",
                "code": "organization_header_required",
                "detail": "A selected organization is required",
            }
        )
        await websocket.close(code=1008, reason="organization required")
        return False

    try:
        authorized = security_dependencies.authorize_credentials(
            f"Bearer {access_token.strip()}",
            organization_id.strip(),
            Permission.READ_TELEMETRY,
        )
    except HTTPException as error:
        code, message = _http_error(error)
        await websocket.send_json(
            {
                "type": "error",
                "code": code,
                "detail": message,
            }
        )
        await websocket.close(code=1008, reason="access denied")
        return False

    await websocket.send_json(
        {
            "type": "authenticated",
            "subject": authorized.principal.subject,
            "organization_id": authorized.principal.organization_id,
        }
    )
    return True


def create_live_router(
    database: Database,
    hub: LiveTelemetryHub,
    state: RuntimeState,
    *,
    heartbeat_seconds: float,
    send_timeout_seconds: float,
    auth_timeout_seconds: float = 5.0,
    resume_limit: int,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry-live"])

    @router.websocket("/live")
    async def live(websocket: WebSocket) -> None:
        params = websocket.query_params
        quality = params.get("quality")
        alarm = params.get("alarm")

        await websocket.accept()
        if not await _authenticate_websocket(
            websocket,
            security_dependencies,
            timeout_seconds=auth_timeout_seconds,
        ):
            return

        if quality is not None and quality not in ALLOWED_QUALITIES:
            await websocket.send_json(
                {"type": "error", "detail": "unsupported quality filter"}
            )
            await websocket.close(code=1008, reason="invalid quality filter")
            return
        if alarm is not None and alarm not in ALLOWED_ALARMS:
            await websocket.send_json(
                {"type": "error", "detail": "unsupported alarm filter"}
            )
            await websocket.close(code=1008, reason="invalid alarm filter")
            return

        try:
            after = _parse_after(params.get("after"))
        except ValueError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1008, reason="invalid resume timestamp")
            return

        filters = LiveTelemetryFilter(
            node_id=params.get("node_id"),
            equipment_id=params.get("equipment_id"),
            channel_id=params.get("channel_id"),
            metric=params.get("metric"),
            quality=quality,
            alarm=alarm,
        )
        client = hub.register(filters)
        replayed_event_ids: set[str] = set()

        async def send(payload: dict[str, Any]) -> None:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=send_timeout_seconds,
            )

        try:
            if after is not None:
                replay_rows = database.history_samples(
                    query=TelemetryQuery(
                        node_id=filters.node_id,
                        equipment_id=filters.equipment_id,
                        channel_id=filters.channel_id,
                        metric=filters.metric,
                        quality=filters.quality,
                        alarm=filters.alarm,
                        from_at=after,
                    ),
                    limit=resume_limit + 1,
                    offset=0,
                )
                if len(replay_rows) > resume_limit:
                    await send(
                        {
                            "type": "error",
                            "detail": (
                                "resume result exceeds limit; reconnect with a "
                                "newer after timestamp"
                            ),
                        }
                    )
                    await websocket.close(code=1008, reason="resume limit exceeded")
                    return

                for sample in reversed(replay_rows):
                    payload = _sample_payload(sample)
                    await send(payload)
                    replayed_event_ids.add(sample.event_id)
                    state.increment("websocket_resume_total")

            while True:
                try:
                    item = await asyncio.wait_for(
                        client.queue.get(),
                        timeout=heartbeat_seconds,
                    )
                except TimeoutError:
                    await send(
                        {
                            "type": "heartbeat",
                            "server_time": datetime.now(UTC).isoformat(),
                        }
                    )
                    state.increment("websocket_heartbeat_total")
                    continue

                if item is OVERFLOW:
                    await websocket.close(code=1013, reason="slow consumer")
                    return
                if item is SHUTDOWN:
                    await websocket.close(code=1012, reason="service restart")
                    return

                payload = item
                if not isinstance(payload, dict):
                    continue
                event_id = str(payload.get("event_id", ""))
                if event_id in replayed_event_ids:
                    continue
                await send(payload)
        except TimeoutError:
            state.increment("websocket_send_timeout_total")
            await websocket.close(code=1013, reason="send timeout")
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(client)

    return router
''',
)

path = "src/lib/telemetry/contract.ts"
content = read(path)
content = content.replace(
    '  | { kind: "heartbeat"; serverTime: string }\n  | { kind: "error"; detail: string };',
    '  | { kind: "authenticated"; subject: string; organizationId: string }\n  | { kind: "heartbeat"; serverTime: string }\n  | { kind: "error"; detail: string };',
    1,
)
content = content.replace(
    '  if (record.type === "heartbeat") {\n',
    '  if (record.type === "authenticated") {\n    return {\n      kind: "authenticated",\n      subject: asString(record.subject, "live.subject"),\n      organizationId: asString(record.organization_id, "live.organization_id"),\n    };\n  }\n  if (record.type === "heartbeat") {\n',
    1,
)
write(path, content)

write(
    "src/lib/telemetry/websocket-client.ts",
    '''import type { SecurityCredentialProvider } from "@/features/security/security-session";

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
  reconnectDelaysMs?: readonly number[];
  maxSeenEventIds?: number;
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000] as const;

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

export class TelemetryWebSocketClient {
  private readonly createSocket: TelemetryWebSocketFactory;
  private readonly credentials: SecurityCredentialProvider | null;
  private readonly reconnectDelaysMs: readonly number[];
  private readonly maxSeenEventIds: number;

  constructor(
    private readonly websocketUrl: string,
    options: TelemetryWebSocketClientOptions = {},
  ) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    this.credentials = options.credentials ?? null;
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS;
    this.maxSeenEventIds = options.maxSeenEventIds ?? 10_000;
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;
    let closed = false;
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
      if (closed) {
        return;
      }

      setState(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      const nextSocket = this.createSocket(buildUrl(this.websocketUrl, filters, lastCommittedCapturedAt));
      socket = nextSocket;

      nextSocket.addEventListener("open", () => {
        if (!this.credentials) {
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
            reportError(error, "Telemetry WebSocket authentication failed");
            nextSocket.close(1008, "telemetry authentication failed");
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
        if (closed) {
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
''',
)

path = "src/hooks/use-dashboard-telemetry.ts"
content = read(path)
content = content.replace(
    'import { kpis as demoKpis } from "@/data/dashboard";\n',
    'import { kpis as demoKpis } from "@/data/dashboard";\nimport { createAuthenticatedFetch } from "@/features/security/security-session";\nimport { createSupabaseCredentialProvider } from "@/features/security/supabase-auth";\n',
    1,
)
content = content.replace(
    "    const controller = new AbortController();\n    const adapter = createTelemetryAdapter(config);\n",
    "    const controller = new AbortController();\n    const organizationId = process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null;\n    const credentialProvider = createSupabaseCredentialProvider(organizationId);\n    const adapter = createTelemetryAdapter(config, {\n      rest: {\n        fetch: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider),\n      },\n      websocket: { credentials: credentialProvider },\n    });\n",
    1,
)
write(path, content)

write(
    "src/lib/telemetry/websocket-client.test.ts",
    '''import { afterEach, describe, expect, it, vi } from "vitest";

import type { TelemetryConnectionState, TelemetrySample } from "./types";
import { TelemetryWebSocketClient } from "./websocket-client";

const sample: TelemetrySample = {
  event_id: "event-1",
  node_id: "edge-01",
  captured_at: "2026-07-23T18:00:00Z",
  metric: "temperature",
  value: 4.2,
  unit: "degC",
  quality: "valid",
  source: "modbus",
  equipment_id: "xjp60d-106",
  channel_id: "106-03",
  alarm: null,
  raw_value: 42,
  raw_status: null,
};

class MockWebSocket extends EventTarget {
  readonly send = vi.fn();
  readonly close = vi.fn((code = 1000, reason = "") => {
    this.dispatchEvent(new CloseEvent("close", { code, reason }));
  });

  constructor(readonly url: string) {
    super();
  }

  open(): void {
    this.dispatchEvent(new Event("open"));
  }

  message(payload: unknown): void {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }

  disconnect(code = 1006, reason = ""): void {
    this.dispatchEvent(new CloseEvent("close", { code, reason }));
  }
}

describe("TelemetryWebSocketClient", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("filters, reconnects with last committed timestamp and ignores duplicates", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const samples: TelemetrySample[] = [];
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://127.0.0.1:8082/api/v1/telemetry/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [50, 100],
    });

    const subscription = client.subscribe(
      { node_id: "edge-01", channel_id: "106-03" },
      {
        onSample: (value) => samples.push(value),
        onStateChange: (state) => states.push(state),
      },
    );

    expect(sockets[0].url).toBe(
      "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01&channel_id=106-03",
    );
    sockets[0].open();
    sockets[0].message(sample);
    sockets[0].message(sample);
    expect(samples).toEqual([sample]);

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(50);

    expect(sockets).toHaveLength(2);
    const resumedUrl = new URL(sockets[1].url);
    expect(resumedUrl.searchParams.get("after")).toBe(sample.captured_at);
    sockets[1].open();
    sockets[1].message(sample);
    expect(samples).toEqual([sample]);
    expect(states).toContain("reconnecting");

    subscription.close();
  });

  it("authenticates after open, waits for server acknowledgement and refreshes on reconnect", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const states: TelemetryConnectionState[] = [];
    const credentials = vi
      .fn()
      .mockResolvedValueOnce({ accessToken: "jwt-one", organizationId: "org-1" })
      .mockResolvedValueOnce({ accessToken: "jwt-two", organizationId: "org-1" });
    const client = new TelemetryWebSocketClient("wss://central/api/v1/telemetry/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      credentials,
      reconnectDelaysMs: [10],
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onStateChange: (state) => states.push(state),
      },
    );

    sockets[0].open();
    await Promise.resolve();
    await Promise.resolve();
    expect(sockets[0].url).not.toContain("jwt-one");
    expect(sockets[0].send).toHaveBeenCalledWith(
      JSON.stringify({
        type: "authenticate",
        access_token: "jwt-one",
        organization_id: "org-1",
      }),
    );
    expect(states.at(-1)).toBe("connecting");

    sockets[0].message({
      type: "authenticated",
      subject: "viewer-user",
      organization_id: "org-1",
    });
    expect(states.at(-1)).toBe("connected");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    sockets[1].open();
    await Promise.resolve();
    await Promise.resolve();
    expect(sockets[1].send).toHaveBeenCalledWith(
      expect.stringContaining("jwt-two"),
    );
    expect(credentials).toHaveBeenCalledTimes(2);
  });

  it("handles heartbeat and bounded reconnect exhaustion", async () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const heartbeat = vi.fn();
    const onError = vi.fn();
    const states: TelemetryConnectionState[] = [];
    const client = new TelemetryWebSocketClient("ws://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [10],
    });

    client.subscribe(
      {},
      {
        onSample: vi.fn(),
        onHeartbeat: heartbeat,
        onError,
        onStateChange: (state) => states.push(state),
      },
    );

    sockets[0].message({
      type: "heartbeat",
      server_time: "2026-07-23T18:00:02Z",
    });
    expect(heartbeat).toHaveBeenCalledWith("2026-07-23T18:00:02Z");

    sockets[0].disconnect();
    await vi.advanceTimersByTimeAsync(10);
    sockets[1].disconnect();

    expect(states.at(-1)).toBe("disconnected");
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "websocket",
        message: "Telemetry WebSocket reconnect limit reached",
      }),
    );
  });

  it("does not retry an authorization policy violation", () => {
    vi.useFakeTimers();
    const sockets: MockWebSocket[] = [];
    const onError = vi.fn();
    const client = new TelemetryWebSocketClient("wss://central/live", {
      createSocket: (url) => {
        const socket = new MockWebSocket(url);
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      reconnectDelaysMs: [10],
    });

    client.subscribe({}, { onSample: vi.fn(), onError });
    sockets[0].disconnect(1008, "access denied");
    vi.advanceTimersByTime(100);

    expect(sockets).toHaveLength(1);
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: "access denied" }),
    );
  });
});
''',
)

path = "src/lib/telemetry/contract.test.ts"
content = read(path)
content = content.replace(
    '  it("parses heartbeat and service error messages", () => {\n',
    '  it("parses authenticated acknowledgement, heartbeat and service errors", () => {\n    expect(\n      parseTelemetryLiveMessage({\n        type: "authenticated",\n        subject: "viewer-user",\n        organization_id: "org-1",\n      }),\n    ).toEqual({\n      kind: "authenticated",\n      subject: "viewer-user",\n      organizationId: "org-1",\n    });\n',
    1,
)
write(path, content)

write(
    "services/telemetry-service/tests/test_websocket_security.py",
    '''from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import Role

SECRET = "test-only-websocket-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@example.test",
            "name": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def app_for(tmp_path: Path):
    return create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'secure-live.db'}",
            auto_create_schema=True,
            mqtt_enabled=False,
            auth_mode="jwt",
            auth_default_organization_id=ORGANIZATION_ID,
            auth_jwt_public_key=SECRET,
            auth_jwt_algorithm="HS256",
            auth_jwt_issuer=ISSUER,
            auth_jwt_audience=AUDIENCE,
            auth_jwt_provider="test-oidc",
            websocket_auth_timeout_seconds=0.25,
            websocket_heartbeat_seconds=30,
        )
    )


def provision(app, *, subject: str, roles: set[Role]) -> None:
    repository = app.state.security_repository
    repository.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repository.provision_organization(
        organization_id=OTHER_ORGANIZATION_ID,
        slug="other-lab",
        name="Other Laboratory",
    )
    repository.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=VerifiedIdentityClaims(
            provider="test-oidc",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject,
        ),
        roles=roles,
    )


def authentication(subject: str, organization_id: str = ORGANIZATION_ID) -> dict[str, str]:
    return {
        "type": "authenticate",
        "access_token": token(subject),
        "organization_id": organization_id,
    }


def temperature_event(captured_at: datetime) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=4.2,
        unit="degC",
        quality="valid",
        source="dixell-xjp60d",
        equipment_id="K106",
        channel_id="106-03",
        alarm=None,
        raw_value=42,
        raw_status=4354,
    )


def test_authenticated_viewer_receives_ack_before_replay(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    subject = "viewer-user"
    captured_at = datetime(2026, 7, 26, 6, 0, tzinfo=UTC)
    sample = temperature_event(captured_at)

    with TestClient(app) as client:
        provision(app, subject=subject, roles={Role.VIEWER})
        assert app.state.database.persist(sample, sample.normalized_payload())
        query = urlencode(
            {
                "channel_id": "106-03",
                "after": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        )

        with client.websocket_connect(f"/api/v1/telemetry/live?{query}") as websocket:
            assert app.state.runtime.snapshot()["websocket_clients"] == 0
            websocket.send_json(authentication(subject))
            acknowledgement = websocket.receive_json()
            replay = websocket.receive_json()

        assert acknowledgement == {
            "type": "authenticated",
            "subject": subject,
            "organization_id": ORGANIZATION_ID,
        }
        assert replay["event_id"] == str(sample.event_id)
        assert replay["channel_id"] == "106-03"


def test_missing_websocket_token_is_rejected_before_registration(tmp_path: Path) -> None:
    app = app_for(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/telemetry/live") as websocket:
            websocket.send_json(
                {
                    "type": "authenticate",
                    "access_token": "",
                    "organization_id": ORGANIZATION_ID,
                }
            )
            response = websocket.receive_json()

        assert response["type"] == "error"
        assert response["code"] == "missing_bearer_token"
        assert app.state.runtime.snapshot()["websocket_clients"] == 0


def test_cross_organization_websocket_is_denied(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    subject = "viewer-user"

    with TestClient(app) as client:
        provision(app, subject=subject, roles={Role.VIEWER})
        with client.websocket_connect("/api/v1/telemetry/live") as websocket:
            websocket.send_json(authentication(subject, OTHER_ORGANIZATION_ID))
            response = websocket.receive_json()

        assert response["type"] == "error"
        assert response["code"] == "organization_membership_not_found"
        assert app.state.runtime.snapshot()["websocket_clients"] == 0
''',
)

write(
    "docs/authenticated-live-telemetry.md",
    '''# Authenticated live telemetry

The production dashboard uses the verified user session introduced by the NEXOLAB RBAC gate for both REST and WebSocket telemetry.

## REST

Every `/api/v1/telemetry/latest` and `/api/v1/telemetry/history` request carries:

- `Authorization: Bearer <access token>`;
- `X-Organization-ID: <selected membership>`.

The backend resolves the JWT subject against PostgreSQL memberships and requires `telemetry.read`.

## WebSocket handshake

Bearer tokens are never placed in the WebSocket URL or query string. After the TLS WebSocket opens, the browser sends one authentication message before any replay or live subscription is registered:

```json
{
  "type": "authenticate",
  "access_token": "<short-lived user JWT>",
  "organization_id": "<selected organization UUID>"
}
```

The server verifies the JWT, membership and `telemetry.read` permission. A successful session receives:

```json
{
  "type": "authenticated",
  "subject": "verified-oidc-subject",
  "organization_id": "<selected organization UUID>"
}
```

Only then does the server register the bounded client queue and perform resume replay. Policy violations close with WebSocket code `1008` and are not retried automatically. Transport failures still use bounded reconnect backoff, and each reconnect obtains refreshed credentials from Supabase Auth.

## Security properties

- bearer tokens are absent from URLs, server access logs and acceptance evidence;
- browser roles are ignored;
- organization selection is checked against PostgreSQL membership;
- cross-organization subscriptions are denied before replay;
- no telemetry client is registered before authentication succeeds;
- development mode remains compatible with unauthenticated local tests when `AUTH_MODE=disabled`.

## Required public frontend variables

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://api.example.test
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://api.example.test/api/v1/telemetry/live
NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=<organization UUID>
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>
```

Service-role keys, JWT signing secrets and private keys must never use the `NEXT_PUBLIC_` prefix.
''',
)
