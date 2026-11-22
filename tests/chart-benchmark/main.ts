import "./style.css";

import { chartSeriesKey } from "@/features/charts/domain";
import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";
import {
  BENCHMARK_INTERVAL_MS,
  BENCHMARK_START_MS,
  createBenchmarkScene,
  createBenchmarkSeries,
  createSynchronizedBenchmarkScenes,
} from "@/features/charts/fixtures";
import { reduceChartSegments } from "@/features/charts/reduction";
import type { ChartRendererScene } from "@/features/charts/renderer-adapter";

interface MeasurementSummary {
  samplesMs: number[];
  medianMs: number;
  p95Ms: number;
  maximumMs: number;
}

interface ScenarioResult {
  name: string;
  measurement: MeasurementSummary;
  details: Record<string, string | number | boolean>;
}

interface MountedPlot {
  adapter: EChartsRendererAdapter;
  container: HTMLDivElement;
  scene: ChartRendererScene;
}

declare global {
  interface Window {
    nexolabChartBenchmark: {
      runInitial: (seriesCount: 1 | 8, iterations?: number) => Promise<ScenarioResult>;
      runSynchronizedGroups: () => Promise<ScenarioResult>;
      runGapAndEvidence: () => Promise<ScenarioResult>;
      runIncremental: (updates?: number) => Promise<ScenarioResult>;
      runResize: () => Promise<ScenarioResult>;
      runRemount: () => Promise<ScenarioResult>;
      runLongLived: (updates?: number) => Promise<ScenarioResult>;
      dispose: () => void;
    };
  }
}

function requiredBenchmarkRoot(): HTMLElement {
  const element = document.querySelector<HTMLElement>("#benchmark-root");
  if (!element) throw new Error("Benchmark root is missing");
  return element;
}

const root = requiredBenchmarkRoot();

let mounted: MountedPlot[] = [];

function percentile(values: readonly number[], ratio: number): number {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))] ?? 0;
}

function summarize(samplesMs: number[]): MeasurementSummary {
  return {
    samplesMs,
    medianMs: percentile(samplesMs, 0.5),
    p95Ms: percentile(samplesMs, 0.95),
    maximumMs: Math.max(...samplesMs, 0),
  };
}

function nextPaint(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
}

function dispose(): void {
  for (const plot of mounted) plot.adapter.dispose();
  mounted = [];
  root.replaceChildren();
}

function createHeader(seriesCount: number): HTMLElement {
  const header = document.createElement("header");
  header.className = "benchmark-header";
  header.innerHTML = `
    <div>
      <p class="eyebrow">LOCAL_LAN · deterministic fixture</p>
      <h1>NEXOLAB Chart System benchmark</h1>
      <p class="status">Live · 15 min · ${seriesCount} series · exact timestamp inspection</p>
    </div>
    <div class="actions" aria-label="Chart controls">
      <button type="button">Pause View</button>
      <button type="button">Return to Live</button>
      <button type="button">Reset zoom</button>
    </div>`;
  return header;
}

function createLegend(scene: ChartRendererScene): HTMLElement {
  const legend = document.createElement("section");
  legend.className = "benchmark-legend";
  legend.setAttribute("aria-label", "Chart legend");
  for (const series of scene.series) {
    const latest = series.segments.at(-1)?.points.at(-1);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "legend-item";
    button.innerHTML = `<span class="legend-token" style="--series-color:${series.colorToken}"></span><span>${series.name} · ${latest?.value.toFixed(2) ?? "—"} ${series.identity.nativeUnit} · ${latest?.quality ?? "unknown"} · ${series.freshness}</span>`;
    legend.append(button);
  }
  return legend;
}

function createInspector(scene: ChartRendererScene): HTMLElement {
  const latest = scene.series[0]?.segments.at(-1)?.points.at(-1);
  const inspector = document.createElement("aside");
  inspector.className = "benchmark-inspector";
  inspector.setAttribute("aria-label", "Exact chart inspector");
  inspector.textContent = latest
    ? `${new Date(latest.timestampMs).toISOString()} · ${scene.series[0].name} · ${latest.value} ${scene.series[0].identity.nativeUnit} · ${latest.quality} · ${scene.series[0].freshness}`
    : "No inspectable measurement";
  return inspector;
}

function mountScenes(scenes: readonly ChartRendererScene[]): MountedPlot[] {
  dispose();
  root.append(createHeader(scenes.reduce((sum, scene) => sum + scene.series.length, 0)));
  const summary = document.createElement("p");
  summary.className = "sr-only";
  summary.textContent = `Telemetry benchmark. ${scenes.length} synchronized plot groups. State Live. Gaps remain separate segments.`;
  root.append(summary);
  const grid = document.createElement("div");
  grid.className = "plot-grid";
  root.append(grid);

  mounted = scenes.map((scene, index) => {
    const section = document.createElement("section");
    section.className = "plot-shell";
    section.setAttribute("aria-label", `Synchronized plot group ${index + 1}`);
    const container = document.createElement("div");
    container.className = "plot";
    section.append(container, createLegend(scene), createInspector(scene));
    grid.append(section);
    const adapter = new EChartsRendererAdapter();
    adapter.initialize({
      container,
      renderer: "canvas",
      reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
      maximumLivePoints: 240,
      onCursor: () => undefined,
      onXDomainChange: () => undefined,
    });
    adapter.setScene(scene);
    return { adapter, container, scene };
  });
  return mounted;
}

async function runInitial(seriesCount: 1 | 8, iterations = 10): Promise<ScenarioResult> {
  const samplesMs: number[] = [];
  for (let index = 0; index < iterations; index += 1) {
    const start = performance.now();
    mountScenes([createBenchmarkScene(seriesCount)]);
    await nextPaint();
    samplesMs.push(performance.now() - start);
  }
  const points = mounted[0].scene.series.flatMap((series) =>
    series.segments.flatMap((segment) => segment.points),
  );
  return {
    name: `${seriesCount}x240 initial Canvas render`,
    measurement: summarize(samplesMs),
    details: { seriesCount, renderedPoints: points.length, rendererInstances: mounted.length },
  };
}

async function runSynchronizedGroups(): Promise<ScenarioResult> {
  const start = performance.now();
  const plots = mountScenes(createSynchronizedBenchmarkScenes());
  await nextPaint();
  return {
    name: "multiple synchronized unit groups",
    measurement: summarize([performance.now() - start]),
    details: { plotGroups: plots.length, sharedTimeDomain: true, dualAxisMixing: false },
  };
}

async function runGapAndEvidence(): Promise<ScenarioResult> {
  const raw = createBenchmarkSeries(0, 1_200, { withGap: true, withEvidence: true });
  const sourceMaximum = Math.max(
    ...raw.segments.flatMap((segment) => segment.points.map((point) => point.value)),
  );
  const reducedSegments = reduceChartSegments(raw.segments, { maximumPoints: 240 });
  const reducedMaximum = Math.max(
    ...reducedSegments.flatMap((segment) => segment.points.map((point) => point.value)),
  );
  const scene = {
    ...createBenchmarkScene(1, { withGap: true, withEvidence: true }),
    series: [{ ...raw, segments: reducedSegments }],
  };
  const start = performance.now();
  mountScenes([scene]);
  await nextPaint();
  return {
    name: "gaps, extrema and threshold evidence",
    measurement: summarize([performance.now() - start]),
    details: {
      sourcePoints: 1_200,
      reducedPoints: reducedSegments.flatMap((segment) => segment.points).length,
      segmentCount: reducedSegments.length,
      sourceMaximum,
      reducedMaximum,
      extremaPreserved: sourceMaximum === reducedMaximum,
    },
  };
}

async function runIncremental(updates = 100): Promise<ScenarioResult> {
  const [plot] = mountScenes([createBenchmarkScene(1)]);
  await nextPaint();
  const series = plot.scene.series[0];
  const seriesKey = chartSeriesKey(series.identity);
  const segmentId = series.segments.at(-1)!.id;
  const samplesMs: number[] = [];
  for (let index = 0; index < updates; index += 1) {
    const start = performance.now();
    plot.adapter.appendLiveTail(seriesKey, [
      {
        segmentId,
        point: {
          id: `incremental-${index}`,
          timestampMs: BENCHMARK_START_MS + (240 + index) * BENCHMARK_INTERVAL_MS,
          value: -10 + Math.sin(index / 9),
          quality: "valid",
        },
      },
    ]);
    samplesMs.push(performance.now() - start);
  }
  await nextPaint();
  return {
    name: "incremental live-tail update",
    measurement: summarize(samplesMs),
    details: { updates, rendererInstancesCreated: 1, maximumLivePoints: 240 },
  };
}

async function runResize(): Promise<ScenarioResult> {
  const [plot] = mountScenes([createBenchmarkScene(8)]);
  await nextPaint();
  const samplesMs: number[] = [];
  for (const width of [360, 960, 1_440, 1_920, 720]) {
    plot.container.style.width = `${width}px`;
    const start = performance.now();
    plot.adapter.resize();
    await nextPaint();
    samplesMs.push(performance.now() - start);
  }
  plot.container.style.width = "100%";
  return {
    name: "responsive resize",
    measurement: summarize(samplesMs),
    details: { resizeCount: samplesMs.length, fullReloads: 0 },
  };
}

async function runRemount(): Promise<ScenarioResult> {
  const samplesMs: number[] = [];
  for (let index = 0; index < 10; index += 1) {
    const start = performance.now();
    mountScenes([createBenchmarkScene(8)]);
    await nextPaint();
    samplesMs.push(performance.now() - start);
  }
  return {
    name: "dispose and reinitialize",
    measurement: summarize(samplesMs),
    details: { cycles: 10, activeRendererInstances: mounted.length, expectedActiveInstances: 1 },
  };
}

async function runLongLived(updates = 1_000): Promise<ScenarioResult> {
  const [plot] = mountScenes([createBenchmarkScene(1)]);
  await nextPaint();
  const series = plot.scene.series[0];
  const seriesKey = chartSeriesKey(series.identity);
  const segmentId = series.segments[0].id;
  const samplesMs: number[] = [];
  for (let index = 0; index < updates; index += 1) {
    const start = performance.now();
    plot.adapter.appendLiveTail(seriesKey, [
      {
        segmentId,
        point: {
          id: `long-${index}`,
          timestampMs: BENCHMARK_START_MS + (240 + index) * BENCHMARK_INTERVAL_MS,
          value: -8 + Math.cos(index / 13),
          quality: "valid",
        },
      },
    ]);
    samplesMs.push(performance.now() - start);
    if (index > 0 && index % 100 === 0) await nextPaint();
  }
  await nextPaint();
  return {
    name: "long-lived bounded update loop",
    measurement: summarize(samplesMs),
    details: { updates, rendererInstancesCreated: 1, maximumLivePoints: 240 },
  };
}

window.nexolabChartBenchmark = {
  runInitial,
  runSynchronizedGroups,
  runGapAndEvidence,
  runIncremental,
  runResize,
  runRemount,
  runLongLived,
  dispose,
};

void runInitial(1, 1);
