"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { LiveTelemetryExplorer } from "@/components/live/live-telemetry-explorer";
import { useLiveTelemetry, type LiveHistoryRange } from "@/hooks/use-live-telemetry";

function initialHistoryRange(value: string | null): LiveHistoryRange {
  if (value === "6h") return "6h";
  if (value === "24h") return "24h";
  if (value === "7d" || value === "custom") return "7d";
  return "1h";
}

export function LiveDataWorkspace({ organizationId }: { organizationId: string }) {
  const searchParams = useSearchParams();
  const initialSelectedKeys = useMemo(
    () => [...new Set(searchParams.getAll("compare"))].slice(0, 8),
    [searchParams],
  );
  const initialRange = initialHistoryRange(searchParams.get("range"));
  const telemetry = useLiveTelemetry({
    enabled: true,
    organizationId,
    initialSelectedKeys,
    initialRange,
  });

  return <LiveTelemetryExplorer telemetry={telemetry} />;
}
