import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";

import { getReportsApiBaseUrl, ReportClientError } from "./runtime-config";
import type { ReportDownload, ReportGenerationResponse, ReportPage, TestReport } from "./types";

export type ReportFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface ReportApiClientOptions {
  fetch?: ReportFetch;
  timeoutMs?: number;
}

export interface ReportListQuery {
  sessionId?: string;
  limit?: number;
  offset?: number;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertObject<T>(value: unknown, label: string): T {
  if (!isRecord(value)) {
    throw new ReportClientError(`${label} returned an invalid object.`, undefined, "contract");
  }
  return value as T;
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

function withQuery(path: string, values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function filenameFromDisposition(value: string | null, fallback: string): string {
  if (!value) return fallback;
  const encoded = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      return fallback;
    }
  }
  const quoted = value.match(/filename="([^"]+)"/i)?.[1];
  return quoted?.trim() || fallback;
}

export function createReportIdempotencyKey(sessionId: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `nexolab-ui:reports:${sessionId}:${random}`;
}

export class ReportApiClient {
  private readonly fetchImpl: ReportFetch;
  private readonly timeoutMs: number;

  constructor(
    private readonly apiBaseUrl: string,
    options: ReportApiClientOptions = {},
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 15_000;
  }

  listReports(query: ReportListQuery = {}, signal?: AbortSignal): Promise<ReportPage> {
    return this.requestJson(
      withQuery("/api/v1/reports", {
        session_id: query.sessionId,
        limit: query.limit ?? 200,
        offset: query.offset ?? 0,
      }),
      { signal },
      (body) => assertObject<ReportPage>(body, "Reports list"),
    );
  }

  getReport(reportId: string, signal?: AbortSignal): Promise<TestReport> {
    return this.requestJson(
      `/api/v1/reports/${encodeURIComponent(reportId)}`,
      { signal },
      (body) => assertObject<TestReport>(body, "Report detail"),
    );
  }

  generateReport(
    sessionId: string,
    reason: string,
    idempotencyKey: string,
    expectedSourceSha256?: string,
    signal?: AbortSignal,
  ): Promise<ReportGenerationResponse> {
    return this.requestJson(
      `/api/v1/reports/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "POST",
        body: {
          reason: reason.trim() || null,
          expected_source_sha256: expectedSourceSha256?.trim() || null,
        },
        idempotencyKey,
        signal,
      },
      (body) => assertObject<ReportGenerationResponse>(body, "Report generation"),
    );
  }

  async downloadArtifact(
    reportId: string,
    artifactName: string,
    signal?: AbortSignal,
  ): Promise<ReportDownload> {
    const response = await this.performRequest(
      `/api/v1/reports/${encodeURIComponent(reportId)}/artifacts/${encodeURIComponent(artifactName)}`,
      { signal },
    );
    if (!response.ok) {
      const body = await this.readJson(response);
      const detail = errorDetail(body, `Reports API returned HTTP ${response.status}.`);
      throw new ReportClientError(detail.message, response.status, detail.code);
    }
    return {
      blob: await response.blob(),
      filename: filenameFromDisposition(response.headers.get("Content-Disposition"), artifactName),
      mediaType: response.headers.get("Content-Type") ?? "application/octet-stream",
      sha256: response.headers.get("X-Content-SHA256"),
    };
  }

  private async requestJson<T>(
    path: string,
    options: RequestOptions,
    parser: (body: unknown) => T,
  ): Promise<T> {
    const response = await this.performRequest(path, options);
    const body = await this.readJson(response);
    if (!response.ok) {
      const detail = errorDetail(body, `Reports API returned HTTP ${response.status}.`);
      throw new ReportClientError(detail.message, response.status, detail.code);
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
        throw new ReportClientError(
          timedOut ? `Reports request exceeded ${this.timeoutMs} ms.` : "Reports request was aborted.",
          undefined,
          timedOut ? "timeout" : "aborted",
          { cause: error },
        );
      }
      throw new ReportClientError("Reports API request failed.", undefined, "network", { cause: error });
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
        throw new ReportClientError("Reports API returned invalid JSON.", response.status, "contract", {
          cause: error,
        });
      }
      return null;
    }
  }
}

export function createReportApiClient(options: ReportApiClientOptions = {}): ReportApiClient {
  const fetchImpl = options.fetch ?? fetch.bind(globalThis);
  return new ReportApiClient(getReportsApiBaseUrl(), {
    ...options,
    fetch: createAuthenticatedFetch(fetchImpl, createRuntimeCredentialProvider(null)),
  });
}
