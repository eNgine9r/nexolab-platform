"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { retainTelemetryApplicationShell } from "@/lib/telemetry/route-persistent-client";

function isIsolatedTelegramMiniApp(pathname: string): boolean {
  return pathname === "/telegram-miniapp" || pathname.startsWith("/telegram-miniapp/");
}

export function TelemetryStateProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  useEffect(() => {
    if (isIsolatedTelegramMiniApp(pathname)) return;
    return retainTelemetryApplicationShell();
  }, [pathname]);

  return children;
}
