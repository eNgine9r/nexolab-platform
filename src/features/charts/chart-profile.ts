/**
 * #1867: opt-in stage timing of the chart pipeline for browser evidence (performance E2E). Off unless
 * a test sets `window.__nexolabChartProfileEnabled = true`; then each stage accumulates count, total
 * and max milliseconds in `window.__nexolabChartProfile`. Production never records or grows a buffer.
 */
export interface ChartProfileStage {
  count: number;
  totalMs: number;
  maxMs: number;
}

type ProfileGlobal = typeof globalThis & {
  __nexolabChartProfileEnabled?: boolean;
  __nexolabChartProfile?: Record<string, ChartProfileStage>;
};

export function chartProfile<T>(stage: string, run: () => T): T {
  const scope = globalThis as ProfileGlobal;
  if (scope.__nexolabChartProfileEnabled !== true) return run();
  const started = performance.now();
  try {
    return run();
  } finally {
    const elapsed = performance.now() - started;
    const table = (scope.__nexolabChartProfile ??= {});
    const entry = (table[stage] ??= { count: 0, totalMs: 0, maxMs: 0 });
    entry.count += 1;
    entry.totalMs += elapsed;
    if (elapsed > entry.maxMs) entry.maxMs = elapsed;
  }
}
