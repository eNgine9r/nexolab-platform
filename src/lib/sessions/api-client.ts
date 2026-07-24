import { getSessionsApiBaseUrl, SessionClientError } from "./runtime-config";
import type {
  AttributedTelemetryCollection,
  LaboratorySession,
  LimitSetMutationResponse,
  ProductionBindingsResponse,
  SessionAction,
  SessionAuditPage,
  SessionCommandInput,
  SessionConfiguration,
  SessionCreateInput,
  SessionEventPage,
  SessionMutationResponse,
  SessionNoteResponse,
  SessionNotesPage,
  SessionPage,
  SessionStage,
  StageAdvanceResponse,
} from "./types";
import type {
  LimitSetInput,
  ProductionBindingsInput,
  SessionHistoryQuery,
  SessionNoteInput,
  SessionTelemetryQuery,
  StageAdvanceInput,
} from "./inputs";

export type SessionFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface SessionApiClientOptions {
  fetch?: SessionFetch;
  timeoutMs?: number;
}

export interface SessionListQuery {
  state?: string;
  nodeId?: string;
  limit?: number;
  offset?: number;
}

interface ManagedSignal {
  signal: AbortSignal;
  cleanup: () => void;
  didTimeout: () => boolean;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function createManagedSignal(externalSignal: AbortSignal | undefined, timeoutMs: number): ManagedSignal {
  const controller = new AbortController();
  let timedOut = false;

  const onAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) {
    onAbort();
  } else {
    externalSignal?.addEventListener("abort", onAbort, { once: true });
  }

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException("Request timed out", "TimeoutError"));
  }, timeoutMs);

  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    cleanup: () => {
      clearTimeout(timer);
      externalSignal?.removeEventListener("abort", onAbort);
    },
  };
}

function timestamp(value: string | Date): string {
  return value instanceof Date ? value.toISOString() : value;
}

function withQuery(path: string, values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertObject<T>(value: unknown, label: string): T {
  if (!isRecord(value)) {
    throw new SessionClientError(`${label} returned an invalid object.`, undefined, "contract");
  }
  return value as T;
}

function assertArray<T>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) {
    throw new SessionClientError(`${label} returned an invalid array.`, undefined, "contract");
  }
  return value as T[];
}

function errorDetail(body: unknown, fallback: string): { message: string; code?: string } {
  if (!isRecord(body)) return { message: fallback };
  const detail = body.detail;
  if (typeof detail === "string") return { message: detail };
  if (isRecord(detail)) {
    return {
      message: typeof detail.message === "string" ? detail.message : fallback,
      code: typeof detail.code === "string" ? detail.code : undefined,
    };
  }
  return { message: fallback };
}

export function createIdempotencyKey(scope: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `nexolab-ui:${scope}:${random}`;
}

export function createOperatorCommand(reason?: string): SessionCommandInput {
  return {
    actor_id: "dashboard-operator",
    actor_source: "nexolab-dashboard",
    occurred_at: new Date().toISOString(),
    reason: reason?.trim() || null,
  };
}

export class SessionApiClient {
  private readonly fetchImpl: SessionFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: SessionApiClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  listSessions(query: SessionListQuery = {}, signal?: AbortSignal): Promise<SessionPage> {
    return this.request(
      withQuery("/api/v1/sessions", {
        state: query.state,
        node_id: query.nodeId,
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
      }),
      { signal },
      (body) => assertObject<SessionPage>(body, "Sessions list"),
    );
  }

  getSession(sessionId: string, signal?: AbortSignal): Promise<LaboratorySession> {
    return this.request(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, { signal }, (body) =>
      assertObject<LaboratorySession>(body, "Session"),
    );
  }

  createSession(
    payload: SessionCreateInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionMutationResponse> {
    return this.request(
      "/api/v1/sessions",
      { method: "POST", body: payload, idempotencyKey, signal },
      (body) => assertObject<SessionMutationResponse>(body, "Session create"),
    );
  }

  transition(
    sessionId: string,
    action: SessionAction,
    payload: SessionCommandInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionMutationResponse> {
    return this.request(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/${action}`,
      { method: "POST", body: payload, idempotencyKey, signal },
      (body) => assertObject<SessionMutationResponse>(body, "Session transition"),
    );
  }

  getConfiguration(sessionId: string, signal?: AbortSignal): Promise<SessionConfiguration> {
    return this.request(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/configuration`,
      { signal },
      (body) => assertObject<SessionConfiguration>(body, "Session configuration"),
    );
  }

  addProductionBindings(
    sessionId: string,
    payload: ProductionBindingsInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ProductionBindingsResponse> {
    return this.request(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/bindings/production`,
      { method: "POST", body: payload, idempotencyKey, signal },
      (body) => assertObject<ProductionBindingsResponse>(body, "Production bindings"),
    );
  }

  addLimitSet(
    sessionId: string,
    payload: LimitSetInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<LimitSetMutationResponse> {
    return this.request(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/limits`,
      { method: "POST", body: payload, idempotencyKey, signal },
      (body) => assertObject<LimitSetMutationResponse>(body, "Session limits"),
    );
  }

  listEvents(sessionId: string, signal?: AbortSignal): Promise<SessionEventPage> {
    return this.request(
      withQuery(`/api/v1/sessions/${encodeURIComponent(sessionId)}/events`, { limit: 200, offset: 0 }),
      { signal },
      (body) => assertObject<SessionEventPage>(body, "Session events"),
    );
  }

  listStages(sessionId: string, signal?: AbortSignal): Promise<SessionStage[]> {
    return this.request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/stages`, { signal }, (body) =>
      assertArray<SessionStage>(body, "Session stages"),
    );
  }

  advanceStage(
    sessionId: string,
    payload: StageAdvanceInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<StageAdvanceResponse> {
    return this.request(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/stages/advance`,
      { method: "POST", body: payload, idempotencyKey, signal },
      (body) => assertObject<StageAdvanceResponse>(body, "Stage transition"),
    );
  }

  listNotes(sessionId: string, signal?: AbortSignal): Promise<SessionNotesPage> {
    return this.request(
      withQuery(`/api/v1/sessions/${encodeURIComponent(sessionId)}/notes`, { limit: 200, offset: 0 }),
      { signal },
      (body) => assertObject<SessionNotesPage>(body, "Session notes"),
    );
  }

  addNote(
    sessionId: string,
    payload: SessionNoteInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SessionNoteResponse> {
    return this.request(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/notes`,
      { method: "POST", body: payload, idempotencyKey, signal },
      (body) => assertObject<SessionNoteResponse>(body, "Session note"),
    );
  }

  listAudit(sessionId: string, signal?: AbortSignal): Promise<SessionAuditPage> {
    return this.request(
      withQuery(`/api/v1/sessions/${encodeURIComponent(sessionId)}/audit`, { limit: 200, offset: 0 }),
      { signal },
      (body) => assertObject<SessionAuditPage>(body, "Session audit"),
    );
  }

  latestTelemetry(
    sessionId: string,
    query: SessionTelemetryQuery = {},
    signal?: AbortSignal,
  ): Promise<AttributedTelemetryCollection> {
    return this.request(
      withQuery(`/api/v1/sessions/${encodeURIComponent(sessionId)}/telemetry/latest`, {
        stage_id: query.stage_id,
        node_id: query.node_id,
        equipment_id: query.equipment_id,
        channel_id: query.channel_id,
        metric: query.metric,
        quality: query.quality,
        alarm: query.alarm,
        limit: query.limit ?? 500,
        offset: query.offset ?? 0,
      }),
      { signal },
      (body) => assertObject<AttributedTelemetryCollection>(body, "Session latest telemetry"),
    );
  }

  historyTelemetry(
    sessionId: string,
    query: SessionHistoryQuery,
    signal?: AbortSignal,
  ): Promise<AttributedTelemetryCollection> {
    return this.request(
      withQuery(`/api/v1/sessions/${encodeURIComponent(sessionId)}/telemetry/history`, {
        from: timestamp(query.from),
        to: timestamp(query.to),
        stage_id: query.stage_id,
        node_id: query.node_id,
        equipment_id: query.equipment_id,
        channel_id: query.channel_id,
        metric: query.metric,
        quality: query.quality,
        alarm: query.alarm,
        limit: query.limit ?? 500,
        offset: query.offset ?? 0,
      }),
      { signal },
      (body) => assertObject<AttributedTelemetryCollection>(body, "Session telemetry history"),
    );
  }

  private async request<T>(path: string, options: RequestOptions, parser: (body: unknown) => T): Promise<T> {
    const managed = createManagedSignal(options.signal, this.timeoutMs);
    let response: Response;

    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          Accept: "application/json",
          ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: managed.signal,
      });
    } catch (error) {
      if (managed.signal.aborted) {
        throw new SessionClientError(
          managed.didTimeout()
            ? `Sessions request exceeded ${this.timeoutMs} ms.`
            : "Sessions request was aborted.",
          undefined,
          managed.didTimeout() ? "timeout" : "aborted",
          { cause: error },
        );
      }
      throw new SessionClientError("Sessions API request failed.", undefined, "network", { cause: error });
    } finally {
      managed.cleanup();
    }

    let body: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch (error) {
        if (response.ok) {
          throw new SessionClientError("Sessions API returned invalid JSON.", response.status, "contract", {
            cause: error,
          });
        }
      }
    }

    if (!response.ok) {
      const detail = errorDetail(body, `Sessions API returned ${response.status}.`);
      throw new SessionClientError(detail.message, response.status, detail.code ?? "http");
    }

    return parser(body);
  }
}

export function createSessionApiClient(options: SessionApiClientOptions = {}): SessionApiClient {
  return new SessionApiClient(getSessionsApiBaseUrl(), options);
}
