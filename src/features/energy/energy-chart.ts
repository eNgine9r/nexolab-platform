import {
  chartSeriesKey,
  type ChartContinuityBreak,
  type ChartFreshnessState,
  type ChartPoint,
  type ChartSegment,
  type ChartSeries,
  type ChartSeriesIdentity,
  type ChartXDomain,
} from "@/features/charts/domain";
import {
  energyHistorySourceEventId,
  isEnergyHistorySegmentStart,
} from "@/features/energy/energy-history-segment";
import {
  ENERGY_METERS,
  ENERGY_METRICS,
  energyMeterOrder,
  isEnergySample,
  resolveEnergyMeter,
  type EnergyMetricId,
} from "@/features/energy/energy-telemetry";
import { energySeriesSelectionKey, type EnergySeriesSelection } from "./energy-series-selection";
import type { EnergyTelemetryModel } from "@/hooks/use-energy-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

const METER_COLORS: Record<number, string> = {
  1: "#14b8a6",
  200: "#38bdf8",
  201: "#22c55e",
  202: "#a78bfa",
  203: "#f59e0b",
};

export interface EnergyChartScene {
  series: ChartSeries[];
  xDomain: ChartXDomain;
}

function freshness(status: EnergyTelemetryModel["status"]): ChartFreshnessState {
  if (status === "live") return "live";
  if (status === "stale") return "stale";
  if (status === "connecting") return "connecting";
  if (status === "reconnecting") return "reconnecting";
  return "offline";
}

function fallbackDomain(samples: readonly TelemetrySample[]): ChartXDomain {
  const timestamps = samples.map((sample) => Date.parse(sample.captured_at)).filter(Number.isFinite);
  const now = Date.now();
  if (timestamps.length === 0) return { fromMs: now - 60 * 60_000, toMs: now };
  const fromMs = Math.min(...timestamps);
  const toMs = Math.max(...timestamps);
  return { fromMs, toMs: toMs > fromMs ? toMs : fromMs + 1 };
}

function resolvedDomain(
  samples: readonly TelemetrySample[],
  window: EnergyTelemetryModel["historyWindow"],
): ChartXDomain {
  const fromMs = window ? Date.parse(window.from) : Number.NaN;
  const toMs = window ? Date.parse(window.to) : Number.NaN;
  if (Number.isFinite(fromMs) && Number.isFinite(toMs) && toMs > fromMs) {
    return { fromMs, toMs };
  }
  return fallbackDomain(samples);
}

function buildSegments(identity: ChartSeriesIdentity, samples: readonly TelemetrySample[]): ChartSegment[] {
  const seriesKey = chartSeriesKey(identity);
  const ordered = [...samples].sort(
    (left, right) =>
      Date.parse(left.captured_at) - Date.parse(right.captured_at) ||
      energyHistorySourceEventId(left.event_id).localeCompare(energyHistorySourceEventId(right.event_id)),
  );
  const segments: ChartSegment[] = [];
  let points: ChartPoint[] = [];
  let activeBreak: ChartContinuityBreak | undefined;
  let pendingBreak: ChartContinuityBreak | undefined;

  const flush = () => {
    if (points.length === 0) return;
    const first = points[0];
    segments.push({
      id: `${seriesKey}:segment:${segments.length}:${first.timestampMs}`,
      seriesKey,
      points,
      ...(activeBreak ? { precedingBreak: activeBreak } : {}),
    });
    points = [];
    activeBreak = undefined;
  };

  for (const sample of ordered) {
    const timestampMs = Date.parse(sample.captured_at);
    if (!Number.isFinite(timestampMs)) continue;
    const sourceEventId = energyHistorySourceEventId(sample.event_id);

    if (isEnergyHistorySegmentStart(sample.event_id)) {
      flush();
      pendingBreak = { reason: "explicit_gap", atMs: timestampMs, sourceEventId };
    }

    if (sample.quality !== "valid" || sample.value === null || !Number.isFinite(sample.value)) {
      flush();
      pendingBreak = { reason: "invalid_quality", atMs: timestampMs, sourceEventId };
      continue;
    }

    if (points.length === 0 && pendingBreak) {
      activeBreak = pendingBreak;
      pendingBreak = undefined;
    }
    points.push({
      id: sourceEventId,
      timestampMs,
      value: sample.value,
      quality: sample.quality,
      sourceEventId,
      ...(activeBreak && points.length === 0 ? { pinReasons: ["segment_boundary"] as const } : {}),
    });
  }
  flush();
  return segments;
}

export function buildEnergyChartScene({
  samples,
  selectedMetric,
  selectedMetrics,
  selectedPairs,
  selectedUnitIds,
  status,
  historyWindow,
}: {
  samples: readonly TelemetrySample[];
  selectedMetric?: EnergyMetricId;
  selectedMetrics?: readonly EnergyMetricId[];
  selectedPairs?: readonly EnergySeriesSelection[];
  selectedUnitIds: readonly number[];
  status: EnergyTelemetryModel["status"];
  historyWindow: EnergyTelemetryModel["historyWindow"];
}): EnergyChartScene {
  const metrics = new Set(selectedMetrics ?? [selectedMetric ?? ENERGY_METRICS[0].id]);
  const pairs = selectedPairs ? new Set(selectedPairs.map(energySeriesSelectionKey)) : null;
  const selected = new Set(selectedUnitIds);
  const groups = new Map<
    string,
    {
      meter: (typeof ENERGY_METERS)[number];
      metric: (typeof ENERGY_METRICS)[number];
      nodeId: string;
      channelId: string;
      samples: TelemetrySample[];
    }
  >();
  for (const sample of samples) {
    if (!metrics.has(sample.metric as EnergyMetricId) || !isEnergySample(sample)) continue;
    const meter = resolveEnergyMeter(sample);
    const metric = ENERGY_METRICS.find((item) => item.id === sample.metric);
    if (!meter || !metric || !selected.has(meter.unitId)) continue;
    if (pairs && !pairs.has(energySeriesSelectionKey({ unitId: meter.unitId, metric: metric.id }))) continue;
    const key = JSON.stringify([
      sample.node_id,
      meter.equipmentId,
      sample.channel_id,
      metric.id,
      metric.expectedUnit,
    ]);
    const group = groups.get(key) ?? {
      meter,
      metric,
      nodeId: sample.node_id,
      channelId: sample.channel_id,
      samples: [],
    };
    group.samples.push(sample);
    groups.set(key, group);
  }

  const chartFreshness = freshness(status);
  const series = [...groups.values()]
    .sort(
      (left, right) =>
        energyMeterOrder(left.meter.unitId) - energyMeterOrder(right.meter.unitId) ||
        ENERGY_METRICS.indexOf(left.metric) - ENERGY_METRICS.indexOf(right.metric) ||
        left.nodeId.localeCompare(right.nodeId) ||
        left.channelId.localeCompare(right.channelId),
    )
    .map((group) => {
      const identity: ChartSeriesIdentity = {
        nodeId: group.nodeId,
        equipmentId: group.meter.equipmentId,
        channelId: group.channelId,
        metric: group.metric.id,
        nativeUnit: group.metric.expectedUnit,
      };
      return {
        identity,
        name: `${group.meter.label} · ${group.metric.label} · ${group.meter.equipmentId} · ${group.channelId}`,
        colorToken:
          group.metric.id === "electrical.power.active"
            ? (METER_COLORS[group.meter.unitId] ?? "#00C6E0")
            : `hsl(${((ENERGY_METRICS.indexOf(group.metric) * ENERGY_METERS.length + energyMeterOrder(group.meter.unitId)) * 137.508) % 360} 75% 65%)`,
        dashStyle: (["solid", "dashed", "dotted"] as const)[ENERGY_METRICS.indexOf(group.metric) % 3],
        markerShape: "circle" as const,
        freshness: chartFreshness,
        segments: buildSegments(identity, group.samples),
        visible: true,
        semanticMode:
          group.metric.id === "electrical.energy.active"
            ? ("cumulative_counter" as const)
            : ("instantaneous" as const),
        displayPrecision: group.metric.digits,
      } satisfies ChartSeries;
    })
    .filter((item) => item.segments.some((segment) => segment.points.length > 0));

  return { series, xDomain: resolvedDomain(samples, historyWindow) };
}
