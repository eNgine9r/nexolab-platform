import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";

import { getNodesApiBaseUrl, NodeClientError } from "./runtime-config";
import type {
  CentralNode,
  NodeBrokerControl,
  NodeHealth,
  NodeOperationalState,
  NodeStatus,
  ProvisionNodeResponse,
  RotateNodeCredentialResponse,
} from "./types";

export type NodeFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type NodeApiClientOptions = {
  fetch?: NodeFetch;
  timeoutMs?: number;
};

type RequestOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorDetail(body: unknown, fallback: string): { message: string; code?: string } {
  if (!isRecord(body)) return { message: fallback };
  const detail = body.detail;
  if (typeof detail === "string") return { message: detail };
  if (!isRecord(detail)) return { message: fallback };
  return {
    message: typeof detail.message === "string" ? detail.message : fallback,
    code: typeof detail.code === "string" ? detail.code : undefined,
  };
}

function parseObject<T>(value: unknown, label: string): T {
  if (!isRecord(value)) {
    throw new NodeClientError(`${label} returned an invalid object.`, undefined, "contract");
  }
  return value as T;
}

function parseArray<T>(value: unknown, label: string): T[] {
  if (!Array.isArray(value)) {
    throw new NodeClientError(`${label} returned an invalid array.`, undefined, "contract");
  }
  return value as T[];
}

export function createNodeIdempotencyKey(action: string, nodeId: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `nexolab-ui:nodes:${action}:${nodeId}:${random}`;
}

export class NodeApiClient {
  private readonly fetchImpl: NodeFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: NodeApiClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 15_000;
  }

  listNodes(signal?: AbortSignal): Promise<CentralNode[]> {
    return this.requestJson("/api/v1/nodes", { signal }, (body) =>
      parseArray<CentralNode>(body, "Nodes list"),
    );
  }

  getOperationalState(nodeId: string, signal?: AbortSignal): Promise<NodeOperationalState> {
    return this.requestJson(
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/operational-state`,
      { signal },
      (body) => parseObject<NodeOperationalState>(body, "Node operational state"),
    );
  }

  getBrokerControl(nodeId: string, signal?: AbortSignal): Promise<NodeBrokerControl> {
    return this.requestJson(
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/broker-control`,
      { signal },
      (body) => parseObject<NodeBrokerControl>(body, "Node broker control"),
    );
  }

  getHealthHistory(nodeId: string, limit = 100, signal?: AbortSignal): Promise<NodeHealth[]> {
    return this.requestJson(
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/health-history?limit=${encodeURIComponent(String(limit))}`,
      { signal },
      (body) => parseArray<NodeHealth>(body, "Node health history"),
    );
  }

  getStatusHistory(nodeId: string, limit = 100, signal?: AbortSignal): Promise<NodeStatus[]> {
    return this.requestJson(
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/status-history?limit=${encodeURIComponent(String(limit))}`,
      { signal },
      (body) => parseArray<NodeStatus>(body, "Node status history"),
    );
  }

  provisionNode(
    payload: {
      nodeId: string;
      displayName: string;
      clockWarningMs: number;
      clockCriticalMs: number;
    },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ProvisionNodeResponse> {
    return this.requestJson(
      "/api/v1/nodes",
      {
        method: "POST",
        body: {
          node_id: payload.nodeId,
          display_name: payload.displayName,
          clock_warning_ms: payload.clockWarningMs,
          clock_critical_ms: payload.clockCriticalMs,
        },
        idempotencyKey,
        signal,
      },
      (body) => parseObject<ProvisionNodeResponse>(body, "Node provisioning"),
    );
  }

  changeState(
    nodeId: string,
    action: "activate" | "suspend" | "revoke",
    reason: string,
    signal?: AbortSignal,
  ): Promise<CentralNode> {
    return this.requestJson(
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/${action}`,
      { method: "POST", body: { reason: reason.trim() }, signal },
      (body) => parseObject<CentralNode>(body, "Node lifecycle update"),
    );
  }

  rotateCredential(
    nodeId: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<RotateNodeCredentialResponse> {
    return this.requestJson(
      `/api/v1/nodes/${encodeURIComponent(nodeId)}/credentials/rotate`,
      {
        method: "POST",
        body: { reason: reason.trim() },
        idempotencyKey,
        signal,
      },
      (body) => parseObject<RotateNodeCredentialResponse>(body, "Node credential rotation"),
    );
  }

  private async requestJson<T>(
    path: string,
    options: RequestOptions,
    parser: (body: unknown) => T,
  ): Promise<T> {
    const response = await this.performRequest(path, options);
    const body = await this.readJson(response);
    if (!response.ok) {
      const detail = errorDetail(body, `Nodes API returned HTTP ${response.status}.`);
      throw new NodeClientError(detail.message, response.status, detail.code);
    }
    return parser(body);
  }

  private async performRequest(path: string, options: RequestOptions): Promise<Response> {
    const controller = new AbortController();
    let timedOut = false;
    const onAbort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) onAbort();
    else options.signal?.addEventListener("abort", onAbort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("Request timed out", "TimeoutError"));
    }, this.timeoutMs);

    try {
      return await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          Accept: "application/json",
          ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
          ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) {
        throw new NodeClientError(
          timedOut ? `Nodes request exceeded ${this.timeoutMs} ms.` : "Nodes request was aborted.",
          undefined,
          timedOut ? "timeout" : "aborted",
          { cause: error },
        );
      }
      throw new NodeClientError("Nodes API request failed.", undefined, "network", {
        cause: error,
      });
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }

  private async readJson(response: Response): Promise<unknown> {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text) as unknown;
    } catch (error) {
      if (response.ok) {
        throw new NodeClientError("Nodes API returned invalid JSON.", response.status, "contract", {
          cause: error,
        });
      }
      return null;
    }
  }
}

export function createNodeApiClient(options: NodeApiClientOptions = {}): NodeApiClient {
  const fetchImpl = options.fetch ?? fetch.bind(globalThis);
  return new NodeApiClient(getNodesApiBaseUrl(), {
    ...options,
    fetch: createAuthenticatedFetch(fetchImpl, createRuntimeCredentialProvider(null)),
  });
}
