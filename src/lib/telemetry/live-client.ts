import type { TelemetryClientConfig } from "./config";
import {
  isHeartbeat,
  parseHeartbeat,
  parseTelemetryEvent,
  TelemetryPayloadError,
} from "./runtime";
import type {
  TelemetryConnectionStatus,
  TelemetryEvent,
  TelemetryFilters,
  TelemetryHeartbeat,
} from "./types";
import { buildLiveTelemetryUrl } from "./urls";

export interface TelemetrySocket {
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onclose: ((event: { code: number; reason: string }) => void) | null;
  close(code?: number, reason?: string): void;
}

export type TelemetrySocketFactory = (url: string) => TelemetrySocket;

export interface TelemetryLiveCallbacks {
  onTelemetry(event: TelemetryEvent): void;
  onStatus(status: TelemetryConnectionStatus): void;
  onHeartbeat?(heartbeat: TelemetryHeartbeat): void;
  onError?(error: Error): void;
}

export interface TelemetryLiveClientOptions {
  config: TelemetryClientConfig;
  filters?: TelemetryFilters;
  origin?: string;
  socketFactory?: TelemetrySocketFactory;
  random?: () => number;
}

function browserOrigin(): string | undefined {
  return typeof window === "undefined" ? undefined : window.location.origin;
}

function defaultSocketFactory(url: string): TelemetrySocket {
  return new WebSocket(url) as unknown as TelemetrySocket;
}

export class TelemetryLiveClient {
  private readonly config: TelemetryClientConfig;
  private readonly filters: TelemetryFilters;
  private readonly origin?: string;
  private readonly socketFactory: TelemetrySocketFactory;
  private readonly random: () => number;
  private socket: TelemetrySocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private active = false;
  private callbacks: TelemetryLiveCallbacks | null = null;
  private resumeAfter: string | undefined;
  private status: TelemetryConnectionStatus = "idle";

  constructor(options: TelemetryLiveClientOptions) {
    this.config = options.config;
    this.filters = { ...options.filters };
    this.origin = options.origin ?? browserOrigin();
    this.socketFactory = options.socketFactory ?? defaultSocketFactory;
    this.random = options.random ?? Math.random;
  }

  connect(callbacks: TelemetryLiveCallbacks): void {
    if (this.active) return;
    this.active = true;
    this.callbacks = callbacks;
    this.setStatus("connecting");
    this.openSocket();
  }

  disconnect(): void {
    this.active = false;
    this.clearReconnectTimer();
    const socket = this.socket;
    this.socket = null;
    if (socket) socket.close(1000, "client disconnect");
    this.setStatus("stopped");
    this.callbacks = null;
  }

  getResumeAfter(): string | undefined {
    return this.resumeAfter;
  }

  private openSocket(): void {
    if (!this.active || this.socket) return;

    let socket: TelemetrySocket;
    try {
      socket = this.socketFactory(
        buildLiveTelemetryUrl(
          {
            apiBaseUrl: this.config.apiBaseUrl,
            websocketUrl: this.config.websocketUrl,
            origin: this.origin,
          },
          this.filters,
          this.resumeAfter,
        ),
      );
    } catch (error) {
      this.callbacks?.onError?.(
        error instanceof Error ? error : new Error(String(error)),
      );
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket || !this.active) return;
      this.reconnectAttempt = 0;
      this.setStatus("live");
    };
    socket.onmessage = (message) => {
      if (this.socket !== socket || !this.active) return;
      this.handleMessage(message.data);
    };
    socket.onerror = () => {
      if (this.socket !== socket || !this.active) return;
      this.callbacks?.onError?.(new Error("Telemetry WebSocket error"));
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (!this.active) return;
      if (event.code !== 1000) {
        this.callbacks?.onError?.(
          new Error(
            `Telemetry WebSocket closed with code ${event.code}${event.reason ? `: ${event.reason}` : ""}`,
          ),
        );
      }
      this.scheduleReconnect();
    };
  }

  private handleMessage(data: unknown): void {
    if (typeof data !== "string") {
      this.callbacks?.onError?.(
        new TelemetryPayloadError("Telemetry WebSocket message must be text"),
      );
      return;
    }

    try {
      const payload: unknown = JSON.parse(data);
      if (isHeartbeat(payload)) {
        this.callbacks?.onHeartbeat?.(parseHeartbeat(payload));
        return;
      }

      const event = parseTelemetryEvent(payload);
      if (
        this.resumeAfter === undefined ||
        Date.parse(event.captured_at) > Date.parse(this.resumeAfter)
      ) {
        this.resumeAfter = event.captured_at;
      }
      this.callbacks?.onTelemetry(event);
    } catch (error) {
      this.callbacks?.onError?.(
        error instanceof Error ? error : new Error(String(error)),
      );
    }
  }

  private scheduleReconnect(): void {
    if (!this.active || this.reconnectTimer) return;
    this.setStatus("reconnecting");

    const exponent = Math.min(this.reconnectAttempt, 30);
    const baseDelay = Math.min(
      this.config.reconnectMaxMs,
      this.config.reconnectMinMs * 2 ** exponent,
    );
    this.reconnectAttempt += 1;
    const jitterRange = baseDelay * this.config.reconnectJitterRatio;
    const jitter = (this.random() * 2 - 1) * jitterRange;
    const delay = Math.max(0, Math.round(baseDelay + jitter));

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setStatus(status: TelemetryConnectionStatus): void {
    if (status === this.status) return;
    this.status = status;
    this.callbacks?.onStatus(status);
  }
}
