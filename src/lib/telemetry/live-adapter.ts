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

export class LiveTelemetryAdapter implements TelemetryAdapter {
  constructor(
    private readonly rest: TelemetryRestClient,
    private readonly live: TelemetryLiveClient,
  ) {}

  readiness(signal?: AbortSignal): Promise<TelemetryReadinessResponse> {
    return this.rest.readiness(signal);
  }

  latest(
    query: TelemetryPageQuery = {},
    signal?: AbortSignal,
  ): Promise<TelemetryCollectionResponse> {
    if (this.live instanceof RoutePersistentTelemetryClient) {
      const cached = this.live.readCachedLatest(query);
      if (cached) return Promise.resolve(cached);
    }

    return this.rest.latest(query, signal).then((response) => {
      if (!signal?.aborted && this.live instanceof RoutePersistentTelemetryClient) {
        this.live.seedLatest(query, response);
      }
      return response;
    });
  }

  history(query: TelemetryHistoryQuery, signal?: AbortSignal): Promise<TelemetryCollectionResponse> {
    return this.rest.history(query, signal);
  }

  subscribe(filters: TelemetryFilters, handlers: TelemetryLiveHandlers): TelemetrySubscription {
    return this.live.subscribe(filters, handlers);
  }
}
