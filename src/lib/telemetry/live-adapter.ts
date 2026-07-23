import { TelemetryRestClient } from "./rest-client";
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

export class LiveTelemetryAdapter implements TelemetryAdapter {
  constructor(
    private readonly rest: TelemetryRestClient,
    private readonly live: TelemetryWebSocketClient,
  ) {}

  readiness(signal?: AbortSignal): Promise<TelemetryReadinessResponse> {
    return this.rest.readiness(signal);
  }

  latest(
    query: TelemetryPageQuery = {},
    signal?: AbortSignal,
  ): Promise<TelemetryCollectionResponse> {
    return this.rest.latest(query, signal);
  }

  history(
    query: TelemetryHistoryQuery,
    signal?: AbortSignal,
  ): Promise<TelemetryCollectionResponse> {
    return this.rest.history(query, signal);
  }

  subscribe(
    filters: TelemetryFilters,
    handlers: TelemetryLiveHandlers,
  ): TelemetrySubscription {
    return this.live.subscribe(filters, handlers);
  }
}
