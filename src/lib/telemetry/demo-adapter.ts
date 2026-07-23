import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryFilters,
  TelemetryHistoryQuery,
  TelemetryLiveHandlers,
  TelemetryPageQuery,
  TelemetryReadinessResponse,
  TelemetrySample,
  TelemetrySubscription,
} from "./types";

const DEMO_READINESS: TelemetryReadinessResponse = {
  status: "ready",
  database: "ready",
  mqtt: "ready",
  queue_size: 0,
  websocket_clients: 0,
  database_outage_since: null,
  last_persisted_at: null,
  ingestion_lag_seconds: 0,
  mqtt_error: null,
  database_error: null,
  last_error: null,
};

function matches(sample: TelemetrySample, filters: TelemetryFilters): boolean {
  return (
    (filters.node_id === undefined || sample.node_id === filters.node_id) &&
    (filters.equipment_id === undefined || sample.equipment_id === filters.equipment_id) &&
    (filters.channel_id === undefined || sample.channel_id === filters.channel_id) &&
    (filters.metric === undefined || sample.metric === filters.metric) &&
    (filters.quality === undefined || sample.quality === filters.quality) &&
    (filters.alarm === undefined || sample.alarm === filters.alarm)
  );
}

function page(samples: TelemetrySample[], query: TelemetryPageQuery): TelemetryCollectionResponse {
  const offset = query.offset ?? 0;
  const limit = query.limit ?? 200;
  const filtered = samples.filter((sample) => matches(sample, query));
  const items = filtered.slice(offset, offset + limit);
  return {
    items,
    count: items.length,
    limit,
    offset,
    next_offset: offset + limit < filtered.length ? offset + limit : null,
  };
}

export class DemoTelemetryAdapter implements TelemetryAdapter {
  constructor(
    private readonly samples: TelemetrySample[] = [],
    private readonly readinessSnapshot: TelemetryReadinessResponse = DEMO_READINESS,
  ) {}

  async readiness(): Promise<TelemetryReadinessResponse> {
    return this.readinessSnapshot;
  }

  async latest(query: TelemetryPageQuery = {}): Promise<TelemetryCollectionResponse> {
    const latestByChannel = new Map<string, TelemetrySample>();
    for (const sample of this.samples) {
      const key = `${sample.node_id}:${sample.equipment_id}:${sample.channel_id}:${sample.metric}`;
      const current = latestByChannel.get(key);
      if (!current || current.captured_at < sample.captured_at) {
        latestByChannel.set(key, sample);
      }
    }
    return page([...latestByChannel.values()], query);
  }

  async history(query: TelemetryHistoryQuery): Promise<TelemetryCollectionResponse> {
    const from = new Date(query.from).getTime();
    const to = new Date(query.to).getTime();
    return page(
      this.samples.filter((sample) => {
        const capturedAt = new Date(sample.captured_at).getTime();
        return capturedAt >= from && capturedAt <= to;
      }),
      query,
    );
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    let closed = false;
    handlers.onStateChange?.("connected");

    queueMicrotask(() => {
      if (closed) {
        return;
      }
      for (const sample of this.samples) {
        if (matches(sample, filters)) {
          handlers.onSample(sample);
        }
      }
    });

    return {
      close: () => {
        closed = true;
        handlers.onStateChange?.("disconnected");
      },
    };
  }
}
