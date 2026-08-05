import { TelemetryClientError } from "./errors";

interface RequestConsumer<T> {
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
  signal?: AbortSignal;
  onAbort?: () => void;
}

interface InFlightRequest<T> {
  controller: AbortController;
  promise: Promise<T>;
  consumers: Map<symbol, RequestConsumer<T>>;
}

function abortedError(reason?: unknown): TelemetryClientError {
  return new TelemetryClientError("aborted", "Telemetry request was aborted", { cause: reason });
}

export class TelemetryRequestCoordinator {
  private readonly entries = new Map<string, InFlightRequest<unknown>>();
  private consumerCount = 0;

  constructor(private readonly onActivityChange?: () => void) {}

  get hasConsumers(): boolean {
    return this.consumerCount > 0;
  }

  get inFlightCount(): number {
    return this.entries.size;
  }

  request<T>(
    key: string,
    signal: AbortSignal | undefined,
    factory: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    if (signal?.aborted) return Promise.reject(abortedError(signal.reason));

    let entry = this.entries.get(key) as InFlightRequest<T> | undefined;
    if (!entry) {
      const controller = new AbortController();
      entry = {
        controller,
        consumers: new Map(),
        promise: Promise.resolve().then(() => factory(controller.signal)),
      };
      this.entries.set(key, entry as InFlightRequest<unknown>);
      entry.promise.then(
        () => this.removeSettledEntry(key, entry as InFlightRequest<unknown>),
        () => this.removeSettledEntry(key, entry as InFlightRequest<unknown>),
      );
    }

    const token = Symbol(key);
    return new Promise<T>((resolve, reject) => {
      const consumer: RequestConsumer<T> = { resolve, reject, signal };
      consumer.onAbort = () => this.abortConsumer(entry, token, signal?.reason);
      entry.consumers.set(token, consumer);
      this.consumerCount += 1;
      this.onActivityChange?.();
      signal?.addEventListener("abort", consumer.onAbort, { once: true });

      entry.promise.then(
        (value) => this.settleConsumer(entry, token, () => resolve(value)),
        (error) => this.settleConsumer(entry, token, () => reject(error)),
      );
    });
  }

  abortAll(reason: unknown = new DOMException("Telemetry scope disposed", "AbortError")): void {
    for (const entry of this.entries.values()) {
      for (const token of [...entry.consumers.keys()]) {
        this.abortConsumer(entry, token, reason);
      }
      if (!entry.controller.signal.aborted) entry.controller.abort(reason);
    }
    this.entries.clear();
  }

  private settleConsumer<T>(entry: InFlightRequest<T>, token: symbol, settle: () => void): void {
    const consumer = entry.consumers.get(token);
    if (!consumer) return;
    this.releaseConsumer(entry, token, consumer);
    settle();
  }

  private abortConsumer<T>(entry: InFlightRequest<T>, token: symbol, reason?: unknown): void {
    const consumer = entry.consumers.get(token);
    if (!consumer) return;
    this.releaseConsumer(entry, token, consumer);
    consumer.reject(abortedError(reason));
    if (entry.consumers.size === 0 && !entry.controller.signal.aborted) {
      entry.controller.abort(reason);
    }
  }

  private releaseConsumer<T>(entry: InFlightRequest<T>, token: symbol, consumer: RequestConsumer<T>): void {
    consumer.signal?.removeEventListener("abort", consumer.onAbort as EventListener);
    entry.consumers.delete(token);
    this.consumerCount = Math.max(0, this.consumerCount - 1);
    this.onActivityChange?.();
  }

  private removeSettledEntry(key: string, entry: InFlightRequest<unknown>): void {
    if (this.entries.get(key) === entry) this.entries.delete(key);
  }
}
