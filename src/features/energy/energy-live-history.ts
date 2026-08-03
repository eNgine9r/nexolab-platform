import { markEnergyHistorySegmentStart } from "@/features/energy/energy-history-segment";
import { resolveEnergyMeter } from "@/features/energy/energy-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

export interface EnergyLiveHistoryReconciliation {
  samples: TelemetrySample[];
  pendingUnitIds: Set<number>;
}

function isRenderable(sample: TelemetrySample): boolean {
  return sample.quality === "valid" && sample.value !== null && Number.isFinite(sample.value);
}

export function reconcileEnergyLiveHistory(
  samples: readonly TelemetrySample[],
  pendingUnitIds: ReadonlySet<number> = new Set(),
): EnergyLiveHistoryReconciliation {
  const pending = new Set(pendingUnitIds);
  const reconciled: TelemetrySample[] = [];
  const sorted = [...samples].sort(
    (left, right) => Date.parse(left.captured_at) - Date.parse(right.captured_at),
  );

  for (const sample of sorted) {
    const meter = resolveEnergyMeter(sample);
    if (!meter) continue;

    if (!isRenderable(sample)) {
      pending.add(meter.unitId);
      reconciled.push(sample);
      continue;
    }

    if (pending.delete(meter.unitId)) {
      reconciled.push(markEnergyHistorySegmentStart(sample));
      continue;
    }

    reconciled.push(sample);
  }

  return { samples: reconciled, pendingUnitIds: pending };
}
