"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  CadenceClientError,
  type CadenceFamily,
  type AcquisitionCadenceConfiguration,
  type AcquisitionCapacitySummary,
  createCadenceClient,
} from "@/features/acquisition/cadence-client";

export type CadenceOperatorError = {
  code: CadenceClientError["code"];
  message: string;
  capacity: AcquisitionCapacitySummary | null;
};

export type AcquisitionCadenceController = {
  configuration: AcquisitionCadenceConfiguration | null;
  isLoading: boolean;
  isSaving: boolean;
  error: CadenceOperatorError | null;
  refresh: () => Promise<void>;
  setFamilyDefault: (busId: string, deviceFamily: CadenceFamily, intervalSeconds: number) => Promise<boolean>;
  setDeviceOverride: (deviceId: string, intervalSeconds: number | null) => Promise<boolean>;
};

type Options = {
  enabled: boolean;
  organizationId: string | null;
};

function operatorError(error: unknown): CadenceOperatorError {
  if (error instanceof CadenceClientError) {
    return { code: error.code, message: error.message, capacity: error.capacity };
  }
  return {
    code: "request_failed",
    message: error instanceof Error ? error.message : "Невідома помилка cadence control plane.",
    capacity: null,
  };
}

export function useAcquisitionCadence(options: Options): AcquisitionCadenceController {
  const [configuration, setConfiguration] = useState<AcquisitionCadenceConfiguration | null>(null);
  const [isLoading, setIsLoading] = useState(options.enabled);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<CadenceOperatorError | null>(null);
  const client = useMemo(() => createCadenceClient(options.organizationId), [options.organizationId]);

  const refresh = useCallback(async () => {
    if (!options.enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      setConfiguration(await client.read());
    } catch (nextError) {
      setError(operatorError(nextError));
    } finally {
      setIsLoading(false);
    }
  }, [client, options.enabled]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      if (!options.enabled) {
        setConfiguration(null);
        setIsLoading(false);
        setError(null);
        return;
      }
      void refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [options.enabled, refresh]);

  const mutate = useCallback(
    async (payload: Parameters<typeof client.mutate>[0]) => {
      if (!options.enabled) return false;
      setIsSaving(true);
      setError(null);
      try {
        const next = await client.mutate(payload);
        setConfiguration(next);
        return true;
      } catch (nextError) {
        const normalized = operatorError(nextError);
        setError(normalized);
        if (normalized.code === "revision_conflict") {
          // A conflict invalidates browser state. Re-read immediately so the
          // operator sees the current canonical revision before retrying.
          try {
            setConfiguration(await client.read());
          } catch (refreshError) {
            setError(operatorError(refreshError));
          }
        }
        return false;
      } finally {
        setIsSaving(false);
      }
    },
    [client, options.enabled],
  );

  const setFamilyDefault = useCallback(
    async (busId: string, deviceFamily: CadenceFamily, intervalSeconds: number) => {
      if (!configuration) return false;
      return mutate({
        expected_revision: configuration.registryRevision,
        reason: `Operator updated ${deviceFamily} physical polling cadence in NEXOLAB Settings`,
        family_defaults: [
          {
            bus_id: busId,
            device_family: deviceFamily,
            interval_seconds: intervalSeconds,
          },
        ],
      });
    },
    [configuration, mutate],
  );

  const setDeviceOverride = useCallback(
    async (deviceId: string, intervalSeconds: number | null) => {
      if (!configuration) return false;
      return mutate({
        expected_revision: configuration.registryRevision,
        reason:
          intervalSeconds === null
            ? `Operator returned ${deviceId} physical polling cadence to inherited default`
            : `Operator updated ${deviceId} physical polling cadence in NEXOLAB Settings`,
        device_overrides: [{ device_id: deviceId, interval_seconds: intervalSeconds }],
      });
    },
    [configuration, mutate],
  );

  return {
    configuration,
    isLoading,
    isSaving,
    error,
    refresh,
    setFamilyDefault,
    setDeviceOverride,
  };
}
