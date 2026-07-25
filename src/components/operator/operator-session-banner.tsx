"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, LoaderCircle, ShieldCheck, UserRound } from "lucide-react";

type OperatorSession = {
  actorId: string;
  displayName: string | null;
  provider: "client" | "tailscale";
  authenticated: boolean;
};

type SessionState =
  | { status: "idle" | "loading" }
  | { status: "ready"; session: OperatorSession }
  | { status: "error"; message: string };

export function OperatorSessionBanner() {
  const mode = process.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE?.trim() || "demo";
  const apiBaseUrl = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim().replace(/\/$/, "") || null;
  const [state, setState] = useState<SessionState>({ status: mode === "live" ? "loading" : "idle" });

  useEffect(() => {
    if (mode !== "live" || !apiBaseUrl) return;

    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/v1/operator/session`, {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
        });
        const payload: unknown = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(readError(payload) ?? `Operator session failed with HTTP ${response.status}.`);
        }
        const session = parseSession(payload);
        if (!session) {
          throw new Error("Operator session response does not match the API contract.");
        }
        setState({ status: "ready", session });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Operator session is unavailable.",
        });
      }
    })();

    return () => controller.abort();
  }, [apiBaseUrl, mode]);

  if (mode !== "live") return null;

  if (!apiBaseUrl) {
    return <SessionError message="Live mode requires NEXT_PUBLIC_NEXOLAB_API_BASE_URL." />;
  }

  if (state.status === "loading") {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-cyan-400/15 bg-cyan-500/[0.06] px-3 py-2 text-xs text-cyan-200">
        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
        Перевірка операторської сесії…
      </div>
    );
  }

  if (state.status === "error") {
    return <SessionError message={state.message} />;
  }

  if (state.status !== "ready") return null;

  const { session } = state;
  return (
    <div
      className={
        session.authenticated
          ? "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-emerald-400/20 bg-emerald-500/[0.08] px-3 py-2 text-xs text-emerald-100"
          : "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-amber-400/20 bg-amber-500/[0.08] px-3 py-2 text-xs text-amber-100"
      }
      role="status"
      data-testid="operator-session"
    >
      {session.authenticated ? <ShieldCheck className="h-4 w-4" /> : <UserRound className="h-4 w-4" />}
      <span className="font-semibold">{session.displayName ?? session.actorId}</span>
      <span className="text-[10px] opacity-70">{session.actorId}</span>
      <span className="ml-auto text-[10px] tracking-[0.18em] uppercase opacity-70">
        {session.provider === "tailscale" ? "Tailscale identity" : "Client identity"}
      </span>
    </div>
  );
}

function SessionError({ message }: { message: string }) {
  return (
    <div
      className="flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/[0.08] px-3 py-2 text-xs text-rose-100"
      role="alert"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function parseSession(payload: unknown): OperatorSession | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  const actorId = typeof record.actor_id === "string" ? record.actor_id.trim() : "";
  const displayName = typeof record.display_name === "string" ? record.display_name.trim() : null;
  const provider = record.provider;
  const authenticated = record.authenticated;
  if (!actorId || (provider !== "client" && provider !== "tailscale") || typeof authenticated !== "boolean") {
    return null;
  }
  return {
    actorId,
    displayName: displayName || null,
    provider,
    authenticated,
  };
}

function readError(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const detail = (payload as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const message = (detail as Record<string, unknown>).message;
  return typeof message === "string" && message.trim() ? message.trim() : null;
}
