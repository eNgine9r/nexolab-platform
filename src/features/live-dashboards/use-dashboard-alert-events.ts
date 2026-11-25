"use client";

import { useEffect, useState } from "react";

import { createAlertApiClient } from "@/lib/alerts/api-client";
import { AlertClientError } from "@/lib/alerts/runtime-config";
import type { AlertInstance } from "@/lib/alerts/types";

export type DashboardAlertEventsStatus = "idle" | "loading" | "ready" | "unavailable" | "error";

export interface DashboardAlertEvents {
  status: DashboardAlertEventsStatus;
  alerts: readonly AlertInstance[];
  message: string | null;
}

const PAGE_LIMIT = 200;
const MAX_PAGES = 5;
const REFRESH_MS = 60_000;
const EMPTY: DashboardAlertEvents = { status: "idle", alerts: [], message: null };

/**
 * Read-only canonical alert history for chart annotations (#1647). One bounded paginated
 * read per viewed range (re-polled every minute). Access or configuration failures degrade
 * to an explicit text state; they never affect the chart itself. No alert is ever mutated.
 */
export function useDashboardAlertEvents({
  enabled,
  rangeKey,
}: {
  enabled: boolean;
  rangeKey: string;
}): DashboardAlertEvents {
  const [result, setResult] = useState<{ key: string; value: DashboardAlertEvents }>({
    key: "",
    value: EMPTY,
  });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let disposed = false;
    const publish = (value: DashboardAlertEvents) => {
      if (!disposed) setResult({ key: rangeKey, value });
    };

    const load = async (initial: boolean) => {
      if (initial) publish({ status: "loading", alerts: [], message: null });
      try {
        const client = createAlertApiClient();
        const alerts: AlertInstance[] = [];
        let offset: number | null = 0;
        for (let page = 0; page < MAX_PAGES && offset !== null; page += 1) {
          const response = await client.listAlerts({ limit: PAGE_LIMIT, offset }, controller.signal);
          alerts.push(...response.items);
          offset = response.next_offset;
        }
        publish({ status: "ready", alerts, message: null });
      } catch (error) {
        if (controller.signal.aborted || disposed) return;
        if (error instanceof AlertClientError && (error.status === 401 || error.status === 403)) {
          publish({
            status: "unavailable",
            alerts: [],
            message: "Журнал тривог недоступний для вашої ролі; події на графіку не показуються.",
          });
          return;
        }
        if (error instanceof AlertClientError && error.code === "configuration") {
          publish({
            status: "unavailable",
            alerts: [],
            message: "Журнал тривог недоступний у цьому режимі; події на графіку не показуються.",
          });
          return;
        }
        publish({
          status: "error",
          alerts: [],
          message: "Не вдалося завантажити журнал тривог; події на графіку не показуються.",
        });
      }
    };

    void load(true);
    const timer = globalThis.setInterval(() => void load(false), REFRESH_MS);
    return () => {
      disposed = true;
      controller.abort();
      globalThis.clearInterval(timer);
    };
  }, [enabled, rangeKey]);

  if (!enabled) return EMPTY;
  return result.key === rangeKey ? result.value : { status: "loading", alerts: [], message: null };
}
