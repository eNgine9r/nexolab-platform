import { CircleCheck, CircleDashed, CircleX, LoaderCircle } from "lucide-react";

import type { VersionOperation, VersionOperationPhase } from "@/features/settings/version-management";

const PHASES: { id: VersionOperationPhase; label: string; description: string }[] = [
  {
    id: "verifying_package",
    label: "Перевірка пакета",
    description: "Ідентичність, platform, schema compatibility та validated manifest.",
  },
  {
    id: "checking_capacity",
    label: "Перевірка вільного місця",
    description: "Консервативний capacity preflight перед backup або runtime mutation.",
  },
  {
    id: "creating_backup",
    label: "Створення резервної копії",
    description: "PostgreSQL backup створюється та перевіряється до застосування пакета.",
  },
  {
    id: "applying_update",
    label: "Застосування",
    description: "Validated offline package застосовується через існуючий version manager.",
  },
  {
    id: "verifying_runtime",
    label: "Перевірка локального runtime",
    description: "Очікуємо повернення NEXOLAB та перевіряємо readiness після restart.",
  },
  {
    id: "done",
    label: "Готово",
    description: "Операція завершена лише після post-update verification.",
  },
];

export function VersionOperationProgress({ operation }: { operation: VersionOperation }) {
  const reconnecting =
    operation.status === "running" &&
    (operation.phase === "applying_update" || operation.phase === "verifying_runtime");

  return (
    <section
      aria-labelledby={`version-operation-${operation.id}`}
      className="rounded-2xl border border-amber-300/20 bg-amber-400/5 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs tracking-[.18em] text-amber-200 uppercase">Version operation</p>
          <h2 id={`version-operation-${operation.id}`} className="mt-1 text-base font-semibold">
            {operation.action === "update" ? "Оновлення" : "Rollback"}: {operation.sourceRelease} →{" "}
            {operation.targetRelease}
          </h2>
          <p className="mt-1 font-mono text-[11px] text-slate-500">operation {operation.id}</p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">
          {operationStatusLabel(operation.status)}
        </span>
      </div>

      {reconnecting ? (
        <div
          role="status"
          className="mt-4 rounded-xl border border-cyan-300/20 bg-cyan-300/5 px-4 py-3 text-sm text-cyan-100"
        >
          NEXOLAB перезапускається — очікуємо локальний runtime. Ця сторінка продовжує читати той самий
          durable operation ID і не запускає повторне оновлення.
        </div>
      ) : null}

      <ol className="mt-4 grid gap-2" aria-label="Етапи операції">
        {PHASES.map((phase) => {
          const state = phaseState(operation, phase.id);
          return (
            <li
              key={phase.id}
              className="grid grid-cols-[24px_1fr] gap-3 rounded-xl border border-white/8 bg-[#07182e]/65 px-3 py-3"
            >
              <PhaseIcon state={state} />
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-100">{phase.label}</span>
                  <span className="text-[11px] text-slate-500">{phaseStateLabel(state)}</span>
                </div>
                <p className="mt-1 text-xs leading-5 text-slate-400">{phase.description}</p>
              </div>
            </li>
          );
        })}
      </ol>

      {operation.safeMessage ? (
        <div className="mt-4 rounded-xl border border-rose-300/20 bg-rose-400/5 px-4 py-3 text-sm text-rose-100">
          {operation.safeMessage}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        {operation.capacityEvidenceId ? <span>Capacity: {operation.capacityEvidenceId}</span> : null}
        {operation.backupEvidenceId ? <span>Backup: {operation.backupEvidenceId}</span> : null}
        {operation.resultCode ? <span>Result: {operation.resultCode}</span> : null}
      </div>
    </section>
  );
}

type PhaseViewState = "pending" | "active" | "complete" | "failed";

function phaseState(operation: VersionOperation, phase: VersionOperationPhase): PhaseViewState {
  if (operation.completedPhases.includes(phase)) return "complete";
  if (operation.phase === phase) {
    if (operation.phaseStatus === "failed" || operation.status === "failed") return "failed";
    if (operation.phaseStatus === "succeeded" || operation.status === "succeeded") return "complete";
    return "active";
  }
  if (phase === "done" && operation.status === "succeeded") return "complete";
  return "pending";
}

function PhaseIcon({ state }: { state: PhaseViewState }) {
  if (state === "complete") {
    return <CircleCheck aria-label="Завершено" className="mt-0.5 h-5 w-5 text-emerald-300" />;
  }
  if (state === "failed") {
    return <CircleX aria-label="Помилка" className="mt-0.5 h-5 w-5 text-rose-300" />;
  }
  if (state === "active") {
    return (
      <LoaderCircle
        aria-label="Виконується"
        className="mt-0.5 h-5 w-5 animate-spin text-cyan-300 motion-reduce:animate-none"
      />
    );
  }
  return <CircleDashed aria-label="Очікує" className="mt-0.5 h-5 w-5 text-slate-600" />;
}

function phaseStateLabel(state: PhaseViewState): string {
  switch (state) {
    case "complete":
      return "завершено";
    case "active":
      return "виконується";
    case "failed":
      return "помилка";
    default:
      return "очікує";
  }
}

function operationStatusLabel(status: VersionOperation["status"]): string {
  switch (status) {
    case "queued":
      return "У черзі";
    case "running":
      return "Виконується";
    case "succeeded":
      return "Завершено";
    case "failed":
      return "Помилка";
  }
}
