import { TelemetryClientError } from "./errors";

/**
 * #1809: bounds how many requests of one kind are in flight from this browser tab.
 *
 * History pages used to be fired by several chart surfaces at once. The browser queued them behind
 * its own per-origin connection limit while their 8 s timeout was already running, and the server
 * received more concurrent pages than its history pool serves (#1807). A queued task starts only
 * when a slot is free, so the caller's timeout covers the actual request, not the wait.
 */
export class RequestLimiter {
  private active = 0;
  private readonly queue: Array<{ start: () => void; cancel: () => void }> = [];

  constructor(readonly maxConcurrent: number) {
    if (!Number.isInteger(maxConcurrent) || maxConcurrent < 1) {
      throw new Error("RequestLimiter maxConcurrent must be a positive integer");
    }
  }

  get inFlight(): number {
    return this.active;
  }

  get queued(): number {
    return this.queue.length;
  }

  run<T>(signal: AbortSignal | undefined, task: () => Promise<T>): Promise<T> {
    if (signal?.aborted) return Promise.reject(aborted());
    return new Promise<T>((resolve, reject) => {
      const entry = {
        start: () => {
          signal?.removeEventListener("abort", onAbort);
          this.active += 1;
          let settled: Promise<T>;
          try {
            settled = task();
          } catch (error) {
            settled = Promise.reject(error);
          }
          settled.then(resolve, reject).finally(() => {
            this.active -= 1;
            this.next();
          });
        },
        cancel: () => reject(aborted()),
      };
      const onAbort = () => {
        const index = this.queue.indexOf(entry);
        if (index >= 0) {
          this.queue.splice(index, 1);
          entry.cancel();
        }
      };
      signal?.addEventListener("abort", onAbort, { once: true });
      this.queue.push(entry);
      this.next();
    });
  }

  private next(): void {
    while (this.active < this.maxConcurrent && this.queue.length > 0) {
      this.queue.shift()!.start();
    }
  }
}

function aborted(): TelemetryClientError {
  return new TelemetryClientError("aborted", "Telemetry request was aborted");
}

/**
 * Shared by every history surface in this tab. The telemetry service serves history from a
 * dedicated pool of four connections (#1807); three per tab leaves room for another tab or kiosk.
 */
export const HISTORY_MAX_CONCURRENT_REQUESTS = 3;
export const historyRequestLimiter = new RequestLimiter(HISTORY_MAX_CONCURRENT_REQUESTS);
