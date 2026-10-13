import { ENERGY_METRICS, type EnergyMetricId } from "./energy-telemetry";

export const ENERGY_EXPORT_STEPS = [0, 10, 30, 60, 300, 600, 900, 1800, 3600] as const;
export type EnergyExportStep = (typeof ENERGY_EXPORT_STEPS)[number];
export type EnergyExportStatistic = "avg" | "min" | "max";
export type EnergyExportFormat = "xlsx" | "csv";
export type EnergyExportSeries = {
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: EnergyMetricId;
  unit: string;
};
export type EnergyExportCatalogSeries = EnergyExportSeries & {
  equipment_name: string;
  meter_label: string;
  parameter_name: string;
};
export type EnergyExportCatalog = { items: EnergyExportCatalogSeries[]; retention_days: number };
export type EnergyExportOptions = {
  series: EnergyExportSeries[];
  from: string;
  to: string;
  step_seconds: EnergyExportStep;
  statistics: EnergyExportStatistic[];
  format: EnergyExportFormat;
};
export type EnergyExportJob = {
  job_id: string;
  status: "queued" | "running" | "preview_ready" | "ready" | "failed" | "canceled" | "expired";
  phase: "preview" | "render";
  created_at: string;
  expires_at: string;
  options: EnergyExportOptions;
  progress: { processed: number; total: number | null; unit: "source_events" | "output_rows" };
  preview: {
    source_events: number;
    output_rows: number | null;
    estimated_bytes: number | null;
    available_steps: EnergyExportStep[];
    actual_first_utc: string | null;
    actual_last_utc: string | null;
    snapshot_at: string;
    retention_days: number;
    warnings: string[];
  } | null;
  artifact: { output_rows: number; bytes: number; sha256: string; data_sheets: number | null } | null;
  error: { code: string; message: string } | null;
};

function invalid(): never {
  throw new Error("Некоректна відповідь сервісу експорту.");
}
function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : invalid();
}
function string(value: unknown): string {
  return typeof value === "string" && value.length > 0 && value.length <= 4096 ? value : invalid();
}
function count(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : invalid();
}
function instant(value: unknown): string {
  const text = string(value);
  return /(?:Z|[+-]\d{2}:\d{2})$/.test(text) && Number.isFinite(Date.parse(text)) ? text : invalid();
}
function member<T extends string | number>(value: unknown, values: readonly T[]): T {
  return values.includes(value as T) ? (value as T) : invalid();
}
function array(value: unknown, maximum: number): unknown[] {
  return Array.isArray(value) && value.length <= maximum ? value : invalid();
}
function series(value: unknown): EnergyExportSeries {
  const data = record(value);
  const metric = member(
    data.metric,
    ENERGY_METRICS.map((item) => item.id),
  );
  const unit = string(data.unit);
  if (ENERGY_METRICS.find((item) => item.id === metric)?.expectedUnit !== unit) invalid();
  return {
    node_id: string(data.node_id),
    equipment_id: string(data.equipment_id),
    channel_id: string(data.channel_id),
    metric,
    unit,
  };
}
export function energyExportSeriesKey(item: EnergyExportSeries): string {
  return JSON.stringify([item.node_id, item.equipment_id, item.channel_id, item.metric, item.unit]);
}
function parseOptions(value: unknown): EnergyExportOptions {
  const data = record(value);
  const selected = array(data.series, 64).map(series);
  if (selected.length === 0 || new Set(selected.map(energyExportSeriesKey)).size !== selected.length)
    invalid();
  const from = instant(data.from);
  const to = instant(data.to);
  if (Date.parse(from) >= Date.parse(to)) invalid();
  const statistics = array(data.statistics, 3).map((value) => member(value, ["avg", "min", "max"] as const));
  if (statistics.length === 0) invalid();
  return {
    series: selected,
    from,
    to,
    step_seconds: member(data.step_seconds, ENERGY_EXPORT_STEPS),
    statistics,
    format: member(data.format, ["xlsx", "csv"] as const),
  };
}
export function parseEnergyExportJob(value: unknown): EnergyExportJob {
  const data = record(value);
  const job_id = string(data.job_id);
  if (!/^[a-f0-9]{32}$/.test(job_id)) invalid();
  const progress = record(data.progress);
  const preview = data.preview === null ? null : record(data.preview);
  const artifact = data.artifact === null ? null : record(data.artifact);
  const error = data.error === null ? null : record(data.error);
  const parsed: EnergyExportJob = {
    job_id,
    status: member(data.status, [
      "queued",
      "running",
      "preview_ready",
      "ready",
      "failed",
      "canceled",
      "expired",
    ] as const),
    phase: member(data.phase, ["preview", "render"] as const),
    created_at: instant(data.created_at),
    expires_at: instant(data.expires_at),
    options: parseOptions(data.options),
    progress: {
      processed: count(progress.processed),
      total: progress.total === null ? null : count(progress.total),
      unit: member(progress.unit, ["source_events", "output_rows"] as const),
    },
    preview: preview
      ? {
          source_events: count(preview.source_events),
          output_rows: preview.output_rows === null ? null : count(preview.output_rows),
          estimated_bytes: preview.estimated_bytes === null ? null : count(preview.estimated_bytes),
          available_steps: array(preview.available_steps, 9).map((step) => member(step, ENERGY_EXPORT_STEPS)),
          actual_first_utc: preview.actual_first_utc === null ? null : instant(preview.actual_first_utc),
          actual_last_utc: preview.actual_last_utc === null ? null : instant(preview.actual_last_utc),
          snapshot_at: instant(preview.snapshot_at),
          retention_days: count(preview.retention_days),
          warnings: array(preview.warnings, 20).map(string),
        }
      : null,
    artifact: artifact
      ? {
          output_rows: count(artifact.output_rows),
          bytes: count(artifact.bytes),
          sha256: string(artifact.sha256),
          data_sheets: artifact.data_sheets === null ? null : count(artifact.data_sheets),
        }
      : null,
    error: error ? { code: string(error.code), message: string(error.message) } : null,
  };
  if (
    parsed.status === "preview_ready" &&
    (!parsed.preview ||
      parsed.preview.output_rows === null ||
      parsed.preview.estimated_bytes === null ||
      !parsed.preview.available_steps.includes(parsed.options.step_seconds))
  )
    invalid();
  if (
    parsed.status === "ready" &&
    (!parsed.artifact ||
      !/^[a-f0-9]{64}$/.test(parsed.artifact.sha256) ||
      parsed.artifact.output_rows !== parsed.preview?.output_rows)
  )
    invalid();
  return parsed;
}

export class EnergyExportClient {
  private readonly root: string;
  constructor(
    private readonly fetchImpl: typeof fetch,
    apiBaseUrl: string,
  ) {
    this.root = apiBaseUrl.replace(/\/$/, "") + "/api/v1/energy/exports";
  }
  private async request(
    path: string,
    method: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, 15000);
    try {
      const response = await this.fetchImpl(this.root + path, {
        method,
        cache: "no-store",
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const value: unknown = await response.json();
      if (!response.ok) {
        const detail = record(value).detail;
        const message =
          typeof detail === "object" &&
          detail !== null &&
          "message" in detail &&
          typeof detail.message === "string"
            ? detail.message
            : response.status === 401
              ? "Сеанс завершився. Увійдіть знову."
              : response.status === 403
                ? "Доступ до експорту відсутній."
                : "Перевірте параметри експорту або повторіть запит.";
        throw new Error(message);
      }
      return value;
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    }
  }
  async catalog(signal?: AbortSignal): Promise<EnergyExportCatalog> {
    const value = record(await this.request("/catalog", "GET", undefined, signal));
    if (value.timezone !== "Europe/Kyiv") invalid();
    return {
      retention_days: count(value.retention_days),
      items: array(value.items, 1024).map((value) => {
        const item = record(value);
        return {
          ...series(item),
          equipment_name: string(item.equipment_name),
          meter_label: string(item.meter_label),
          parameter_name: string(item.parameter_name),
        };
      }),
    };
  }
  async preview(options: EnergyExportOptions, signal?: AbortSignal): Promise<EnergyExportJob> {
    return parseEnergyExportJob(await this.request("/preview", "POST", options, signal));
  }
  async job(id: string, signal?: AbortSignal): Promise<EnergyExportJob> {
    if (!/^[a-f0-9]{32}$/.test(id)) invalid();
    return parseEnergyExportJob(await this.request(`/${id}`, "GET", undefined, signal));
  }
  async action(id: string, action: "start" | "cancel", signal?: AbortSignal): Promise<EnergyExportJob> {
    if (!/^[a-f0-9]{32}$/.test(id)) invalid();
    return parseEnergyExportJob(await this.request(`/${id}/${action}`, "POST", undefined, signal));
  }
  async downloadUrl(id: string, signal?: AbortSignal): Promise<string> {
    if (!/^[a-f0-9]{32}$/.test(id)) invalid();
    const data = record(await this.request(`/${id}/download-ticket`, "POST", undefined, signal));
    const path = string(data.download_path);
    if (!new RegExp(`^/api/v1/energy/exports/${id}/download\\?ticket=[A-Za-z0-9_-]{40,64}$`).test(path))
      invalid();
    const url = new URL(this.root);
    url.pathname += `/${id}/download`;
    url.search = path.split("?")[1];
    url.hash = "";
    return url.toString();
  }
}
