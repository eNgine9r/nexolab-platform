"use client";

import { useEffect, useState } from "react";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import {
  monitoredTemperatureChannels,
  TEMPERATURE_REGISTRY_URL,
} from "@/features/acquisition/temperature-monitoring";

type Options = { enabled: boolean; organizationId: string | null };
type State = Options & { channelIds: string[]; isLoading: boolean; error: string | null };

export function useMonitoredTemperatureChannels(options: Options) {
  const { enabled, organizationId } = options;
  const [state, setState] = useState<State>({ ...options, channelIds: [], isLoading: enabled, error: null });
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    const authenticatedFetch = createAuthenticatedFetch(
      fetch.bind(globalThis),
      createRuntimeCredentialProvider(organizationId),
    );
    void authenticatedFetch(TEMPERATURE_REGISTRY_URL, {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(`Не вдалося отримати реєстр моніторингу (HTTP ${response.status}).`);
        return monitoredTemperatureChannels(await response.json());
      })
      .then((channelIds) => {
        if (active) setState({ enabled, organizationId, channelIds, isLoading: false, error: null });
      })
      .catch((cause) => {
        if (active)
          setState({
            enabled,
            organizationId,
            channelIds: [],
            isLoading: false,
            error: controller.signal.aborted
              ? "Час очікування реєстру моніторингу вичерпано."
              : cause instanceof Error
                ? cause.message
                : "Реєстр моніторингу недоступний.",
          });
      })
      .finally(() => clearTimeout(timer));
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, organizationId]);
  if (!enabled || state.enabled !== enabled || state.organizationId !== organizationId) {
    return { channelIds: [], isLoading: enabled, error: null };
  }
  return state;
}
