import { buildTelemetryPointHierarchy, type TelemetryPointHierarchy } from "@/features/telemetry-selection/hierarchy";
import { liveDashboardInventoryToTelemetryPointDescriptor } from "@/features/live-dashboards/telemetry-selection-adapter";
import type { LiveDashboardInventoryItem } from "@/features/live-dashboards/types";

export const ALERT_TELEMETRY_SCOPE_MAX_POINTS = 64;
const ALERT_TELEMETRY_SCOPE_ORGANIZATION = "__current_organization__";

export type AlertTelemetrySelectionModel = {
  hierarchy: TelemetryPointHierarchy;
  allPointKeys: string[];
};

export type AlertTelemetryScopeResult =
  | { ok: true; telemetryPoints: string[] | undefined; selectedKeys: string[] }
  | { ok: false; message: string };

export function buildAlertTelemetrySelectionModel(
  inventory: readonly LiveDashboardInventoryItem[],
): AlertTelemetrySelectionModel {
  const descriptors = inventory.map((item) =>
    liveDashboardInventoryToTelemetryPointDescriptor(item, ALERT_TELEMETRY_SCOPE_ORGANIZATION),
  );
  const hierarchy = buildTelemetryPointHierarchy(descriptors, ALERT_TELEMETRY_SCOPE_ORGANIZATION);
  return { hierarchy, allPointKeys: [...hierarchy.orderedLeafKeys] };
}

export function commitAlertTelemetryScope(
  hierarchy: TelemetryPointHierarchy,
  selectedPointKeys: readonly string[],
): AlertTelemetryScopeResult {
  const requested = new Set(selectedPointKeys);
  const selectedKeys = hierarchy.orderedLeafKeys.filter((key) => requested.has(key));
  if (selectedKeys.length === 0) {
    return { ok: false, message: "Виберіть щонайменше одну точку телеметрії." };
  }
  if (selectedKeys.length === hierarchy.orderedLeafKeys.length) {
    return { ok: true, telemetryPoints: undefined, selectedKeys };
  }
  if (selectedKeys.length > ALERT_TELEMETRY_SCOPE_MAX_POINTS) {
    return {
      ok: false,
      message: `Оберіть не більше ${ALERT_TELEMETRY_SCOPE_MAX_POINTS} точок або підтвердьте всі точки.`,
    };
  }
  return { ok: true, telemetryPoints: selectedKeys, selectedKeys };
}
