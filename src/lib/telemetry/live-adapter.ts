import { TelemetryRestClient } from "./rest-client";
import { RoutePersistentTelemetryClient } from "./route-persistent-client";
import type {
  TelemetryAdapter,
  TelemetryCollectionResponse,
  TelemetryFilters,
  TelemetryHistoryQuery,
  TelemetryLiveHandlers,
  TelemetryPageQuery,
  TelemetryReadinessResponse,
  TelemetrySubscription,
} from "./types";
import { TelemetryWebSocketClient } from "./websocket-client";

type TelemetryLiveClient = RoutePersistentTelemetryClient | TelemetryWebSocketClient;

function pageQueryKey(query: TelemetryPageQuery): string {
  return JSON.stringify({
    node_id: query.node_id ?? null,
    equipment_id: query.equipment_id ?? null,
    channel_id: query.channel_id ?? null,
    metric: query.metric ?? null,
    quality: query.quality ?? null,
    alarm: query.alarm ?? null,
    limit: query.limit ?? null,
    offset: query.offset ?? null,
  });
}

function timestamp(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : value;
}

function historyQueryKey(query: TelemetryHistoryQuery): string {
  return JSON.stringify({
    page: pageQueryKey(query),
    from: timestamp(query.from),
    to: timestamp(query.to),
    snapshot_at: query.snapshot_at === undefined ? null : timestamp(query.snapshot_at),
  });
}

export class LiveTelemetryAdapter implements TelemetryAdapter {
  constructor(
    private readonly rest: TelemetryRestClient,
    private readonly live: TelemetryLiveClient,
    private readonly restScope = "telemetry-rest",
  ) {}

  readiness(signal?: AbortSignal): Promise<TelemetryReadinessResponse> {
    return this.rest.readiness(signal);
  }

  latest(query: TelemetryPageQuery = {}, signal?: AbortSignal): Promise<TelemetryCollectionResponse> {
    const live = this.live;
    if (live instanceof RoutePersistentTelemetryClient) {
      const cached = live.readCachedLatest(query);
      if (cached) return Promise.resolve(cached);
      return live
        .runRequest(`${this.restScope}:latest:${pageQueryKey(query)}`, signal, (physicalSignal) =>
          this.rest.latest(query, physicalSignal),
        )
        .then((response) => {
          if (!signal?.aborted) live.seedLatest(query, response);
          return response;
        });
    }

    return this.rest.latest(query, signal);
  }

  history(query: TelemetryHistoryQuery, signal?: AbortSignal): Promise<TelemetryCollectionResponse> {
    const live = this.live;
    if (live instanceof RoutePersistentTelemetryClient) {
      return live.runRequest(
        `${this.restScope}:history:${historyQueryKey(query)}`,
        signal,
        (physicalSignal) => this.rest.history(query, physicalSignal),
      );
    }
    return this.rest.history(query, signal);
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    return this.live.subscribe(filters, handlers);
  }
}
