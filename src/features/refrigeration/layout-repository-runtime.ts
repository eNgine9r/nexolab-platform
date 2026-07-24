import type { RefrigerationEquipment } from "@/data/refrigeration";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

import { HttpRefrigerationLayoutRepository } from "./http-layout-repository";
import {
  createLayoutDraft,
  InMemoryRefrigerationLayoutRepository,
  type RefrigerationLayoutRepository,
} from "./layout-repository";

export type RefrigerationLayoutRuntime = {
  mode: "demo" | "live";
  repository: RefrigerationLayoutRepository | null;
  actorId: string;
  error: string | null;
};

export type RefrigerationLayoutRuntimeInput = {
  equipment: RefrigerationEquipment;
  fetchImpl?: typeof fetch;
  actorId?: string;
  mode?: string;
  apiBaseUrl?: string;
};

export function createRefrigerationLayoutRuntime(
  input: RefrigerationLayoutRuntimeInput,
): RefrigerationLayoutRuntime {
  const actorId = normalizeActorId(input.actorId ?? process.env.NEXT_PUBLIC_NEXOLAB_OPERATOR_ID);

  try {
    const config = getTelemetryRuntimeConfigFromInput(input);
    if (config.mode === "live") {
      return {
        mode: "live",
        repository: new HttpRefrigerationLayoutRepository({
          apiBaseUrl: config.apiBaseUrl,
          fetchImpl: input.fetchImpl,
        }),
        actorId,
        error: null,
      };
    }

    const createdAt = new Date().toISOString();
    return {
      mode: "demo",
      repository: new InMemoryRefrigerationLayoutRepository({
        drafts: [
          createLayoutDraft({
            id: `draft-${input.equipment.id}`,
            equipmentId: input.equipment.id,
            image: input.equipment.image,
            placements: input.equipment.sensors.map(({ id, x, y }) => ({
              sensorId: id,
              x,
              y,
            })),
            createdAt,
          }),
        ],
      }),
      actorId,
      error: null,
    };
  } catch (error) {
    return {
      mode: input.mode === "live" ? "live" : "demo",
      repository: null,
      actorId,
      error: error instanceof Error ? error.message : "Не вдалося налаштувати сховище схем обладнання.",
    };
  }
}

function getTelemetryRuntimeConfigFromInput(input: RefrigerationLayoutRuntimeInput) {
  if (input.mode !== undefined || input.apiBaseUrl !== undefined) {
    const mode = input.mode?.trim() || "demo";
    if (mode === "demo") {
      return { mode: "demo" as const, apiBaseUrl: null };
    }
    if (mode !== "live") {
      throw new Error(`Unsupported refrigeration layout mode: ${mode}`);
    }
    const apiBaseUrl = input.apiBaseUrl?.trim();
    if (!apiBaseUrl) {
      throw new Error("NEXOLAB API URL is required for live refrigeration layouts.");
    }
    return { mode: "live" as const, apiBaseUrl };
  }

  const config = getTelemetryRuntimeConfig();
  return config.mode === "live"
    ? { mode: "live" as const, apiBaseUrl: config.apiBaseUrl }
    : { mode: "demo" as const, apiBaseUrl: null };
}

function normalizeActorId(value: string | undefined): string {
  const normalized = value?.trim() || "dashboard-operator";
  return normalized.slice(0, 128);
}
