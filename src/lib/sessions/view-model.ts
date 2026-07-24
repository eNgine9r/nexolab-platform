import type { AttributedTelemetrySample, LaboratorySession, SessionAction, SessionState } from "./types";

export const SESSION_STATE_LABELS: Record<SessionState, string> = {
  draft: "Чернетка",
  ready: "Готова",
  running: "Виконується",
  paused: "Призупинена",
  completed: "Завершена",
  cancelled: "Скасована",
  archived: "Архів",
};

export const SESSION_ACTION_LABELS: Record<SessionAction, string> = {
  prepare: "Підготувати",
  start: "Запустити",
  pause: "Призупинити",
  resume: "Відновити",
  complete: "Завершити",
  cancel: "Скасувати",
  archive: "Архівувати",
};

export const ACTIONS_BY_STATE: Record<SessionState, SessionAction[]> = {
  draft: ["prepare", "cancel"],
  ready: ["start", "cancel"],
  running: ["pause", "complete", "cancel"],
  paused: ["resume", "complete", "cancel"],
  completed: ["archive"],
  cancelled: ["archive"],
  archived: [],
};

export function isReadOnlySession(session: LaboratorySession): boolean {
  return session.state === "completed" || session.state === "cancelled" || session.state === "archived";
}

export function sessionElapsedMs(session: LaboratorySession, now = Date.now()): number | null {
  if (!session.started_at) return null;
  const end =
    session.completed_at ?? session.cancelled_at ?? (session.state === "paused" ? session.paused_at : null);
  return Math.max(0, new Date(end ?? now).getTime() - new Date(session.started_at).getTime());
}

export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return "—";
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function latestCapturedAt(samples: readonly AttributedTelemetrySample[]): string | null {
  let latest: string | null = null;
  for (const sample of samples) {
    if (!latest || sample.captured_at > latest) latest = sample.captured_at;
  }
  return latest;
}

export type WorkspaceConnectionState = "connecting" | "live" | "stale" | "offline" | "error";

export function deriveWorkspaceConnectionState(options: {
  loading: boolean;
  error: Error | null;
  hasSnapshot: boolean;
  samples: readonly AttributedTelemetrySample[];
  now?: number;
  staleAfterMs?: number;
}): WorkspaceConnectionState {
  const { loading, error, hasSnapshot, samples } = options;
  if (loading && !hasSnapshot) return "connecting";
  if (error && hasSnapshot) return "offline";
  if (error) return "error";
  const capturedAt = latestCapturedAt(samples);
  if (!capturedAt) return hasSnapshot ? "stale" : "connecting";
  const age = (options.now ?? Date.now()) - new Date(capturedAt).getTime();
  return age > (options.staleAfterMs ?? 30_000) ? "stale" : "live";
}

export interface EnergyUnitView {
  equipmentId: string;
  voltage: number | null;
  current: number | null;
  activePower: number | null;
  frequency: number | null;
  powerFactor: number | null;
  quality: string;
}

export function selectTemperatureSamples(samples: readonly AttributedTelemetrySample[]) {
  return ["106-03", "106-04"].map((channelId) => {
    const sample = samples.find(
      (item) => item.channel_id === channelId && item.metric === "temperature.probe",
    );
    return { channelId, sample: sample ?? null };
  });
}

export function selectEnergyUnits(samples: readonly AttributedTelemetrySample[]): EnergyUnitView[] {
  return [200, 201, 202, 203].map((unitId) => {
    const equipmentId = `LE01MP-${unitId}`;
    const unitSamples = samples.filter((sample) => sample.equipment_id === equipmentId);
    const value = (metric: string) => unitSamples.find((sample) => sample.metric === metric)?.value ?? null;
    const quality = unitSamples.find((sample) => sample.quality !== "valid")?.quality ?? "valid";
    return {
      equipmentId,
      voltage: value("electrical.voltage"),
      current: value("electrical.current"),
      activePower: value("electrical.power.active"),
      frequency: value("electrical.frequency"),
      powerFactor: value("electrical.power_factor"),
      quality,
    };
  });
}
