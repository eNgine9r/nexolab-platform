"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createIdempotencyKey,
  createOperatorCommand,
  createSessionApiClient,
} from "@/lib/sessions/api-client";
import type {
  AttributedTelemetrySample,
  AuditLogEntry,
  LaboratorySession,
  SessionAction,
  SessionConfiguration,
  SessionEvent,
  SessionNote,
  SessionStage,
  SessionStageType,
} from "@/lib/sessions/types";
import {
  deriveWorkspaceConnectionState,
  isReadOnlySession,
  type WorkspaceConnectionState,
} from "@/lib/sessions/view-model";

const POLL_INTERVAL_MS = 5_000;

export interface SessionWorkspaceData {
  session: LaboratorySession;
  configuration: SessionConfiguration;
  events: SessionEvent[];
  stages: SessionStage[];
  notes: SessionNote[];
  audit: AuditLogEntry[];
  latest: AttributedTelemetrySample[];
  history: AttributedTelemetrySample[];
}

export interface SessionWorkspaceModel {
  data: SessionWorkspaceData | null;
  connectionState: WorkspaceConnectionState;
  error: Error | null;
  loading: boolean;
  mutating: boolean;
  readOnly: boolean;
  clock: number;
  refresh: () => void;
  transition: (action: SessionAction) => Promise<void>;
  advanceStage: (input: {
    stageType: SessionStageType;
    name: string;
    plannedDurationMinutes: number;
  }) => Promise<void>;
  addNote: (body: string) => Promise<void>;
}

export function useSessionWorkspace(sessionId: string): SessionWorkspaceModel {
  const [data, setData] = useState<SessionWorkspaceData | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  const mutationKeys = useRef(new Map<string, string>());

  const refresh = useCallback(() => setGeneration((value) => value + 1), []);

  const load = useCallback(
    async (signal: AbortSignal) => {
      try {
        const client = createSessionApiClient();
        const session = await client.getSession(sessionId, signal);
        const historyFrom = session.started_at
          ? new Date(Math.max(new Date(session.started_at).getTime(), Date.now() - 24 * 60 * 60 * 1000))
          : null;
        const historyTo = new Date();

        const [configuration, events, stages, notes, audit, latest, history] = await Promise.all([
          client.getConfiguration(sessionId, signal),
          client.listEvents(sessionId, signal),
          client.listStages(sessionId, signal),
          client.listNotes(sessionId, signal),
          client.listAudit(sessionId, signal),
          client.latestTelemetry(sessionId, { limit: 500 }, signal),
          historyFrom
            ? client.historyTelemetry(
                sessionId,
                {
                  from: historyFrom,
                  to: historyTo,
                  limit: 1000,
                },
                signal,
              )
            : Promise.resolve({ items: [], count: 0, limit: 1000, offset: 0, next_offset: null }),
        ]);

        if (signal.aborted) return;
        setData({
          session,
          configuration,
          events: events.items,
          stages,
          notes: notes.items,
          audit: audit.items,
          latest: latest.items,
          history: history.items,
        });
        setError(null);
        setClock(Date.now());
      } catch (nextError) {
        if (!signal.aborted) {
          setError(nextError instanceof Error ? nextError : new Error("Не вдалося завантажити session workspace."));
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [sessionId],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading((current) => current || data === null);
    void load(controller.signal);
    const poller = window.setInterval(() => void load(controller.signal), POLL_INTERVAL_MS);
    const ticker = window.setInterval(() => setClock(Date.now()), 1_000);
    return () => {
      controller.abort();
      window.clearInterval(poller);
      window.clearInterval(ticker);
    };
  }, [generation, load]);

  const runMutation = useCallback(
    async (scope: string, execute: (key: string) => Promise<void>) => {
      setMutating(true);
      setError(null);
      const key = mutationKeys.current.get(scope) ?? createIdempotencyKey(scope);
      mutationKeys.current.set(scope, key);
      try {
        await execute(key);
        mutationKeys.current.delete(scope);
        refresh();
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError : new Error("Session operation failed."));
        throw nextError;
      } finally {
        setMutating(false);
      }
    },
    [refresh],
  );

  const transition = useCallback(
    async (action: SessionAction) => {
      await runMutation(`lifecycle-${action}`, async (key) => {
        const client = createSessionApiClient();
        await client.transition(
          sessionId,
          action,
          createOperatorCommand(`Lifecycle action ${action} from NEXOLAB dashboard`),
          key,
        );
      });
    },
    [runMutation, sessionId],
  );

  const advanceStage = useCallback(
    async (input: {
      stageType: SessionStageType;
      name: string;
      plannedDurationMinutes: number;
    }) => {
      const nextIndex = data?.stages.length ?? 0;
      await runMutation(`stage-${nextIndex}`, async (key) => {
        const client = createSessionApiClient();
        await client.advanceStage(
          sessionId,
          {
            ...createOperatorCommand(`Entered stage ${input.name}`),
            sequence_index: nextIndex,
            stage_type: input.stageType,
            name: input.name,
            planned_duration_seconds: Math.max(0, input.plannedDurationMinutes * 60),
          },
          key,
        );
      });
    },
    [data?.stages.length, runMutation, sessionId],
  );

  const addNote = useCallback(
    async (body: string) => {
      const normalized = body.trim();
      if (!normalized) return;
      await runMutation(`note-${Date.now()}`, async (key) => {
        const client = createSessionApiClient();
        await client.addNote(
          sessionId,
          {
            ...createOperatorCommand("Operator note added from NEXOLAB dashboard"),
            stage_id: data?.session.current_stage_id ?? null,
            body: normalized,
          },
          key,
        );
      });
    },
    [data?.session.current_stage_id, runMutation, sessionId],
  );

  const connectionState = useMemo(
    () =>
      deriveWorkspaceConnectionState({
        loading,
        error,
        hasSnapshot: data !== null,
        samples: data?.latest ?? [],
        now: clock,
      }),
    [clock, data, error, loading],
  );

  return {
    data,
    connectionState,
    error,
    loading,
    mutating,
    readOnly: data ? isReadOnlySession(data.session) : true,
    clock,
    refresh,
    transition,
    advanceStage,
    addNote,
  };
}
