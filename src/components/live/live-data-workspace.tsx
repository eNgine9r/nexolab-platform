"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { LiveTelemetryExplorer } from "@/components/live/live-telemetry-explorer";
import { readLiveSelectionPreference, writeLiveSelectionPreference } from "@/features/live/selection-preferences";
import { useLiveTelemetry, type LiveHistoryRange } from "@/hooks/use-live-telemetry";

function initialHistoryRange(value: string | null): LiveHistoryRange {
  if (value === "6h") return "6h";
  if (value === "24h") return "24h";
  if (value === "7d" || value === "custom") return "7d";
  return "1h";
}

export function LiveDataWorkspace({ organizationId }: { organizationId: string }) {
  return <ScopedLiveDataWorkspace key={organizationId} organizationId={organizationId} />;
}

function ScopedLiveDataWorkspace({ organizationId }: { organizationId: string }) {
  const searchParams = useSearchParams();
  const [initialSelectedKeys] = useState(() =>
    searchParams.has("compare")
      ? [...new Set(searchParams.getAll("compare"))].slice(0, 8)
      : readLiveSelectionPreference(organizationId),
  );
  const initialRange = initialHistoryRange(searchParams.get("range"));
  const telemetry = useLiveTelemetry({
    enabled: true,
    organizationId,
    initialSelectedKeys,
    initialRange,
  });
  const selectionStamp = JSON.stringify(telemetry.selectedKeys);
  const selectionReady = telemetry.selectionReady === true;

  useEffect(() => {
    if (!selectionReady) return;
    writeLiveSelectionPreference(organizationId, JSON.parse(selectionStamp) as string[]);
  }, [organizationId, selectionReady, selectionStamp]);

  return <LiveTelemetryExplorer telemetry={telemetry} />;
}
