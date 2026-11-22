/**
 * Canonical alert → chart annotation mapping (#1647, WP-C).
 *
 * Evidence-integrity contract §6: a chart event/alarm annotation requires a canonical
 * source-domain entity. `AlertInstance` is that entity; `TelemetrySample.alarm` is only
 * measurement context and never produces markers. This module is pure and read-only.
 */

import type { AlertInstance, AlertSeverity } from "@/lib/alerts/types";

import type {
  ChartAlarmRegion,
  ChartEventMarker,
  ChartSeriesIdentity,
  ChartThreshold,
  ChartXDomain,
} from "./domain";
import { chartSeriesKey } from "./domain";

export interface AlertChartAnnotations {
  events: ChartEventMarker[];
  alarmRegions: ChartAlarmRegion[];
  thresholds: ChartThreshold[];
}

const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  information: "Інформація",
  warning: "Попередження",
  alarm: "Аварія",
  critical: "Критична аварія",
  system: "Системна подія",
};

function markerSeverity(severity: AlertSeverity): NonNullable<ChartEventMarker["severity"]> {
  if (severity === "alarm" || severity === "critical") return "alarm";
  if (severity === "warning" || severity === "system") return "warning";
  return "info";
}

function regionSeverity(severity: AlertSeverity): ChartAlarmRegion["severity"] {
  return severity === "alarm" || severity === "critical" ? "alarm" : "warning";
}

function parse(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function alertMatchesSeries(alert: AlertInstance, identity: ChartSeriesIdentity): boolean {
  return (
    alert.node_id === identity.nodeId &&
    alert.equipment_id === identity.equipmentId &&
    alert.channel_id === identity.channelId &&
    alert.metric === identity.metric
  );
}

/** Operator-facing label for an alert event type (no colour dependence). */
export function alertEventTypeLabel(type: string): string {
  switch (type) {
    case "alert_triggered":
      return "Спрацювання";
    case "alert_acknowledged":
      return "Підтверджено";
    case "alert_resolved":
      return "Відновлено";
    case "alert_closed":
      return "Закрито";
    default:
      return type;
  }
}

/**
 * Builds annotations for the given plotted series and viewed window. Alerts that do not match
 * any plotted series, or that do not touch the window, produce nothing. Open alerts extend to
 * `nowMs` (clipped to the window end) because no resolution has been recorded.
 */
export function buildAlertChartAnnotations(
  alerts: readonly AlertInstance[],
  series: readonly ChartSeriesIdentity[],
  window: ChartXDomain,
  nowMs: number,
): AlertChartAnnotations {
  const events: ChartEventMarker[] = [];
  const alarmRegions: ChartAlarmRegion[] = [];
  const thresholds = new Map<string, ChartThreshold>();
  const seenAlerts = new Set<string>();

  for (const alert of alerts) {
    if (seenAlerts.has(alert.id)) continue;
    const identity = series.find((candidate) => alertMatchesSeries(alert, candidate));
    if (!identity) continue;

    const triggeredAt = parse(alert.triggered_at);
    if (triggeredAt === null) continue;
    const endedAt = parse(alert.resolved_at) ?? parse(alert.closed_at);
    const regionEnd = Math.min(endedAt ?? nowMs, window.toMs);
    const regionStart = Math.max(triggeredAt, window.fromMs);
    const touchesWindow = triggeredAt <= window.toMs && (endedAt ?? nowMs) >= window.fromMs;
    if (!touchesWindow) continue;
    seenAlerts.add(alert.id);

    const label = `${SEVERITY_LABEL[alert.severity]} · ${alert.metric}`;
    const source = {
      entityId: alert.id,
      entityType: "alert_instance",
      equipmentId: alert.equipment_id,
      channelId: alert.channel_id,
    };
    const push = (type: string, at: number | null, stateLabel: string) => {
      if (at === null || at < window.fromMs || at > window.toMs) return;
      events.push({
        id: `${alert.id}:${type}`,
        timestampMs: at,
        type,
        label: `${stateLabel}: ${label}`,
        source,
        severity: markerSeverity(alert.severity),
        status: alert.state,
      });
    };
    push("alert_triggered", triggeredAt, "Спрацювання");
    push("alert_acknowledged", parse(alert.acknowledged_at), "Підтверджено");
    push("alert_resolved", parse(alert.resolved_at), "Відновлено");
    push("alert_closed", parse(alert.closed_at), "Закрито");

    if (regionEnd > regionStart) {
      alarmRegions.push({
        id: `${alert.id}:region`,
        fromMs: regionStart,
        toMs: regionEnd,
        label,
        severity: regionSeverity(alert.severity),
      });
    }

    if (alert.trigger_threshold !== null && Number.isFinite(alert.trigger_threshold)) {
      const kind: ChartThreshold["kind"] =
        alert.trigger_value !== null && alert.trigger_value < alert.trigger_threshold ? "lower" : "upper";
      const seriesKey = chartSeriesKey(identity);
      const id = `${seriesKey}:${kind}:${alert.trigger_threshold}`;
      if (!thresholds.has(id)) {
        thresholds.set(id, {
          id,
          seriesKey,
          kind,
          value: alert.trigger_threshold,
          label: `${kind === "lower" ? "Нижня" : "Верхня"} межа ${alert.trigger_threshold}`,
        });
      }
    }
  }

  events.sort((left, right) => left.timestampMs - right.timestampMs || left.id.localeCompare(right.id));
  alarmRegions.sort((left, right) => left.fromMs - right.fromMs || left.id.localeCompare(right.id));
  return { events, alarmRegions, thresholds: [...thresholds.values()] };
}
