"use client";

import { useEffect, useMemo, useState } from "react";

import type { TelemetryAdapter, TelemetrySample } from "@/lib/telemetry/types";

import type {
  RefrigerationControllerBinding,
  RefrigerationControllerBindingRepository,
} from "./controller-binding-repository";
import {
  buildEmbracoSnapshot,
  loadEmbracoHistory,
  loadEmbracoLatest,
  resolveRefrigerationHistoryRange,
  type EmbracoControllerSnapshot,
  type RefrigerationHistoryPreset,
  type RefrigerationHistoryRange,
} from "./controller-monitoring";

const EMPTY_SAMPLES: readonly TelemetrySample[] = [];
const EMPTY_HISTORY: ReadonlyMap<string, TelemetrySample[]> = new Map();

type BindingState = {
  key: string | null;
  value: RefrigerationControllerBinding | null;
  error: string | null;
};

type LatestState = {
  key: string | null;
  samples: readonly TelemetrySample[];
  error: string | null;
};

type HistoryState = {
  key: string | null;
  value: ReadonlyMap<string, TelemetrySample[]>;
  error: string | null;
};

export type RefrigerationControllerModel = {
  binding: RefrigerationControllerBinding | null;
  bindingLoading: boolean;
  latest: EmbracoControllerSnapshot | null;
  latestError: string | null;
  history: ReadonlyMap<string, TelemetrySample[]>;
  historyLoading: boolean;
  historyError: string | null;
  preset: RefrigerationHistoryPreset;
  range: RefrigerationHistoryRange;
  customRange: RefrigerationHistoryRange;
  setPreset: (preset: RefrigerationHistoryPreset) => void;
  setCustomRange: (range: RefrigerationHistoryRange) => void;
};

export function useRefrigerationController({
  equipmentId,
  repository,
  telemetry,
  historyEnabled,
}: {
  equipmentId: string;
  repository: RefrigerationControllerBindingRepository | null;
  telemetry: TelemetryAdapter | null;
  historyEnabled: boolean;
}): RefrigerationControllerModel {
  const [bindingState, setBindingState] = useState<BindingState>({ key: null, value: null, error: null });
  const [latestState, setLatestState] = useState<LatestState>({
    key: null,
    samples: EMPTY_SAMPLES,
    error: null,
  });
  const [historyState, setHistoryState] = useState<HistoryState>({
    key: null,
    value: EMPTY_HISTORY,
    error: null,
  });
  const [preset, setPreset] = useState<RefrigerationHistoryPreset>("1h");
  const [customRange, setCustomRange] = useState<RefrigerationHistoryRange>(() => {
    const to = new Date();
    return { from: new Date(to.getTime() - 24 * 60 * 60 * 1000), to };
  });
  const range = useMemo(
    () => resolveRefrigerationHistoryRange(preset, new Date(), customRange),
    [customRange, preset],
  );

  const bindingKey = repository ? equipmentId : null;
  const binding = bindingState.key === bindingKey ? bindingState.value : null;
  const latestKey =
    binding && telemetry ? `${binding.id}:${binding.nodeId}:${binding.controllerEquipmentId}` : null;
  const latestSamples = latestState.key === latestKey ? latestState.samples : EMPTY_SAMPLES;
  const latest = useMemo(
    () => (binding ? buildEmbracoSnapshot(latestSamples) : null),
    [binding, latestSamples],
  );
  const historyKey =
    historyEnabled && binding && telemetry
      ? `${binding.id}:${range.from.toISOString()}:${range.to.toISOString()}`
      : null;
  const history = historyState.key === historyKey ? historyState.value : EMPTY_HISTORY;

  useEffect(() => {
    if (!repository || bindingKey === null) return;
    const controller = new AbortController();
    void repository
      .get(equipmentId, controller.signal)
      .then((item) => {
        if (!controller.signal.aborted) setBindingState({ key: bindingKey, value: item, error: null });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setBindingState({
            key: bindingKey,
            value: null,
            error: error instanceof Error ? error.message : "Не вдалося отримати контролер.",
          });
        }
      });
    return () => controller.abort();
  }, [bindingKey, equipmentId, repository]);

  useEffect(() => {
    if (!binding || !telemetry || latestKey === null) return;
    const controller = new AbortController();
    void loadEmbracoLatest(telemetry, binding, controller.signal)
      .then((snapshot) => {
        if (!controller.signal.aborted) {
          setLatestState({ key: latestKey, samples: [...snapshot.latestByMetric.values()], error: null });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLatestState({
            key: latestKey,
            samples: EMPTY_SAMPLES,
            error: error instanceof Error ? error.message : "Не вдалося отримати live дані контролера.",
          });
        }
      });
    const subscription = telemetry.subscribe(
      { node_id: binding.nodeId, equipment_id: binding.controllerEquipmentId },
      {
        onSample: (sample) => {
          setLatestState((current) => {
            const source = current.key === latestKey ? current.samples : EMPTY_SAMPLES;
            const next = new Map(source.map((item) => [item.metric, item] as const));
            const previous = next.get(sample.metric);
            if (!previous || Date.parse(sample.captured_at) >= Date.parse(previous.captured_at)) {
              next.set(sample.metric, sample);
            }
            return { key: latestKey, samples: [...next.values()], error: null };
          });
        },
        onError: (error) => {
          setLatestState((current) => ({
            key: latestKey,
            samples: current.key === latestKey ? current.samples : EMPTY_SAMPLES,
            error: error.message,
          }));
        },
      },
    );
    return () => {
      controller.abort();
      subscription.close();
    };
  }, [binding, latestKey, telemetry]);

  useEffect(() => {
    if (!historyEnabled || !binding || !telemetry || historyKey === null) return;
    const controller = new AbortController();
    void loadEmbracoHistory(telemetry, binding, range, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setHistoryState({ key: historyKey, value: result, error: null });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHistoryState({
            key: historyKey,
            value: EMPTY_HISTORY,
            error: error instanceof Error ? error.message : "Не вдалося завантажити історію контролера.",
          });
        }
      });
    return () => controller.abort();
  }, [binding, historyEnabled, historyKey, range, telemetry]);

  const bindingError = bindingState.key === bindingKey ? bindingState.error : null;
  const latestError = latestState.key === latestKey ? latestState.error : null;
  return {
    binding,
    bindingLoading: bindingKey !== null && bindingState.key !== bindingKey,
    latest,
    latestError: bindingError ?? latestError,
    history,
    historyLoading: historyKey !== null && historyState.key !== historyKey,
    historyError: historyState.key === historyKey ? historyState.error : null,
    preset,
    range,
    customRange,
    setPreset,
    setCustomRange,
  };
}
