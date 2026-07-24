"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, Clock3, LoaderCircle } from "lucide-react";

import { createSessionApiClient } from "@/lib/sessions/api-client";
import type { LaboratorySession } from "@/lib/sessions/types";
import { SESSION_STATE_LABELS } from "@/lib/sessions/view-model";

export function SessionsPanel() {
  const [sessions, setSessions] = useState<LaboratorySession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const client = createSessionApiClient();
        const page = await client.listSessions({ nodeId: "edge-01", limit: 50 }, controller.signal);
        setSessions(
          page.items
            .filter((item) => item.state === "running" || item.state === "paused" || item.state === "ready")
            .slice(0, 5),
        );
        setError(null);
      } catch (nextError) {
        if (!controller.signal.aborted) {
          setError(nextError instanceof Error ? nextError : new Error("Sessions API failed."));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  if (loading) {
    return (
      <div className="grid min-h-48 place-items-center">
        <LoaderCircle className="h-5 w-5 animate-spin text-cyan-300" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="m-4 rounded-xl border border-amber-300/15 bg-amber-400/[0.04] p-4 text-[10px] leading-5 text-slate-400">
        <AlertTriangle className="mr-2 inline h-4 w-4 text-amber-300" />
        {error.message}
        <p className="mt-2 text-[9px] text-slate-600">Demo sessions are disabled.</p>
      </div>
    );
  }
  if (sessions.length === 0) {
    return (
      <div className="grid min-h-48 place-items-center px-5 text-center">
        <div>
          <p className="text-[11px] font-semibold text-white">Активних сесій немає</p>
          <Link href="/sessions/new" className="mt-3 inline-flex text-[10px] text-cyan-300 hover:text-cyan-200">
            Створити реальний draft →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="divide-y divide-white/[0.045] px-4 py-1 sm:px-5">
      {sessions.map((session) => (
        <Link key={session.id} href={`/sessions/${session.id}`} className="group block w-full py-3 text-left">
          <div className="flex items-center justify-between gap-3">
            <h3 className="truncate text-[10px] font-medium text-slate-100 transition group-hover:text-cyan-200">
              {session.title}
            </h3>
            <span className="rounded-full border border-cyan-300/10 bg-cyan-400/[0.04] px-2 py-1 text-[8px] text-cyan-300">
              {SESSION_STATE_LABELS[session.state]}
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between text-[8px] text-slate-600">
            <span>
              {session.session_number} · {session.test_object}
            </span>
            <span className="flex items-center gap-1">
              <Clock3 className="h-2.5 w-2.5" />
              {new Date(session.updated_at).toLocaleTimeString("uk-UA", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}
