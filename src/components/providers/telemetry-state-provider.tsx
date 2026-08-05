"use client";

import { useEffect, type ReactNode } from "react";

import { retainTelemetryApplicationShell } from "@/lib/telemetry/route-persistent-client";

export function TelemetryStateProvider({ children }: { children: ReactNode }) {
  useEffect(() => retainTelemetryApplicationShell(), []);
  return children;
}
