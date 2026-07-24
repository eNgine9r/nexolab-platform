"use client";

import { AlertTriangle, Archive, CheckCircle2, Pause, Play, RefreshCw, Square } from "lucide-react";

import type { SessionAction } from "@/lib/sessions/types";
import { ACTIONS_BY_STATE, SESSION_ACTION_LABELS } from "@/lib/sessions/view-model";

import { useSessionWorkspace } from "./use-session-workspace";
import {
  ConfigurationEvidence,
  EnergyGrid,
  NotesAndAudit,
  SessionHero,
  StageTimeline,
  TemperatureAndChart,
  WorkspaceError,
  WorkspaceLoading,
} from "./workspace-panels";

export function SessionWorkspace({ sessionId }: { sessionId: string }) {
  const workspace = useSessionWorkspace(sessionId);

  if (!workspace.data && workspace.loading) return <WorkspaceLoading />;
  if (!workspace.data && workspace.error) {
    return <WorkspaceError message={workspace.error.message} onRetry={workspace.refresh} />;
  }
  if (!workspace.data) return <WorkspaceError message="Session snapshot is unavailable." onRetry={workspace.refresh} />;

  const { data } = workspace;
  const actions = ACTIONS_BY_STATE[data.session.state];

  return (
    <div className="space-y-4">
      <SessionHero
        session={data.session}
        connectionState={workspace.connectionState}
        clock={workspace.clock}
        readOnly={workspace.readOnly}
      />

      <section className="panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div>
          <p className="text-[9px] font-semibold tracking-[0.16em] text-cyan-300 uppercase">Operator controls</p>
          <p className="mt-1 text-[10px] text-slate-500">
            Кожна команда має стабільний idempotency key до підтвердженого commit.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="secondary-button gap-2"
            onClick={workspace.refresh}
            disabled={workspace.loading || workspace.mutating}
          >
            <RefreshCw className={`h-4 w-4 ${workspace.loading ? "animate-spin" : ""}`} />
            Оновити
          </button>
          {actions.map((action) => (
            <LifecycleButton
              key={action}
              action={action}
              disabled={workspace.mutating}
              onClick={() => void workspace.transition(action)}
            />
          ))}
          {workspace.readOnly && (
            <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-300/10 bg-slate-400/[0.04] px-4 text-[10px] font-semibold text-slate-400">
              <Archive className="h-4 w-4" />
              Immutable view
            </span>
          )}
        </div>
      </section>

      {workspace.error && (
        <div className="rounded-2xl border border-amber-300/15 bg-amber-400/[0.045] p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-300" />
            <div>
              <p className="text-[11px] font-semibold text-white">Останнє оновлення не завершено</p>
              <p className="mt-1 text-[10px] leading-5 text-slate-400">{workspace.error.message}</p>
              <p className="mt-1 text-[9px] text-slate-600">
                Попередній підтверджений snapshot залишається видимим і позначений як offline.
              </p>
            </div>
          </div>
        </div>
      )}

      <TemperatureAndChart data={data} />
      <EnergyGrid samples={data.latest} />
      <StageTimeline
        stages={data.stages}
        currentStageId={data.session.current_stage_id}
        readOnly={workspace.readOnly}
        mutating={workspace.mutating}
        onAdvance={workspace.advanceStage}
      />
      <NotesAndAudit
        notes={data.notes}
        audit={data.audit}
        readOnly={workspace.readOnly}
        mutating={workspace.mutating}
        onAddNote={workspace.addNote}
      />
      <ConfigurationEvidence data={data} />
    </div>
  );
}

function LifecycleButton({
  action,
  disabled,
  onClick,
}: {
  action: SessionAction;
  disabled: boolean;
  onClick: () => void;
}) {
  const Icon = actionIcon(action);
  const danger = action === "cancel";
  const complete = action === "complete" || action === "archive";
  return (
    <button
      className={`inline-flex h-10 items-center gap-2 rounded-xl border px-4 text-[10px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
        danger
          ? "border-red-400/25 bg-red-500/[0.08] text-red-200 hover:bg-red-500/[0.14]"
          : complete
            ? "border-emerald-400/25 bg-emerald-500/[0.07] text-emerald-200 hover:bg-emerald-500/[0.12]"
            : "border-blue-400/30 bg-blue-500/[0.08] text-cyan-100 hover:bg-blue-500/[0.14]"
      }`}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon className="h-4 w-4" />
      {SESSION_ACTION_LABELS[action]}
    </button>
  );
}

function actionIcon(action: SessionAction) {
  if (action === "start" || action === "resume") return Play;
  if (action === "pause") return Pause;
  if (action === "complete" || action === "archive") return CheckCircle2;
  return Square;
}
