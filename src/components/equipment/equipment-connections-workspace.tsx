"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Ban, Cable, CircleDashed, LoaderCircle, Plus, RotateCcw } from "lucide-react";

import { EquipmentDiscoveryInbox } from "@/components/equipment/equipment-discovery-inbox";
import type {
  CommissioningRepository,
  CommissioningSession,
} from "@/features/equipment/commissioning-repository";
import type { EquipmentRegistryAsset } from "@/features/equipment/asset-registry";
import type { EquipmentDiscoveryRepository } from "@/features/equipment/discovery-repository";

const lifecycleLabel: Record<CommissioningSession["lifecycle"], string> = {
  draft: "Чернетка",
  ready_for_preflight: "Готова до перевірки",
  blocked: "Заблокована",
  unsupported: "Профіль не підтримується",
  cancelled: "Скасована",
};

const lifecycleTone: Record<CommissioningSession["lifecycle"], string> = {
  draft: "border-cyan-400/20 bg-cyan-400/10 text-cyan-200",
  ready_for_preflight: "border-blue-400/20 bg-blue-400/10 text-blue-200",
  blocked: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  unsupported: "border-rose-400/20 bg-rose-400/10 text-rose-200",
  cancelled: "border-slate-400/20 bg-slate-400/10 text-slate-400",
};

export function EquipmentConnectionsWorkspace({
  repository,
  discoveryRepository,
  canManage,
  assets,
}: {
  repository: CommissioningRepository | null;
  discoveryRepository: EquipmentDiscoveryRepository | null;
  canManage: boolean;
  assets: EquipmentRegistryAsset[];
}) {
  const [sessions, setSessions] = useState<CommissioningSession[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const load = useCallback(() => setEpoch((current) => current + 1), []);

  useEffect(() => {
    if (!repository) return;
    const controller = new AbortController();
    void repository
      .listSessions(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setSessions(items);
        setState("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "Чернетки комісіонування недоступні.");
        setState("error");
      });
    return () => controller.abort();
  }, [epoch, repository]);

  const assetNames = new Map(assets.map((asset) => [asset.key, asset.displayName]));
  const activeSessions = sessions.filter((session) => session.lifecycle !== "cancelled");
  const blockedCount = activeSessions.filter(
    (session) => session.lifecycle === "blocked" || session.lifecycle === "unsupported",
  ).length;
  const viewState = repository ? state : "error";
  const viewError = repository ? error : "Локальний сервіс чернеток комісіонування не налаштований.";

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-cyan-300/10 bg-[#08182e]/90 p-4 shadow-xl shadow-black/10 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
              <Cable className="h-4 w-4" /> Device connections
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Підключення пристроїв</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Постійні чернетки наміру підключення. Вони не змінюють Device Agent, не запускають опитування та
              не є активними acquisition targets.
            </p>
          </div>
          {canManage ? (
            <Link
              href="/equipment/onboarding/new"
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-400 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
            >
              <Plus className="h-4 w-4" /> Підключити пристрій
            </Link>
          ) : (
            <span className="rounded-xl border border-white/[0.08] px-3 py-2 text-xs text-slate-500">
              Потрібен дозвіл equipment.manage
            </span>
          )}
        </div>
        <div className="mt-5 grid gap-2 sm:grid-cols-3">
          <Metric label="Активні чернетки" value={activeSessions.length} />
          <Metric
            label="Готові до майбутньої перевірки"
            value={activeSessions.filter((item) => item.lifecycle === "ready_for_preflight").length}
          />
          <Metric label="Blocked / unsupported" value={blockedCount} warning={blockedCount > 0} />
        </div>
      </section>

      <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Чернетки комісіонування</h2>
            <p className="mt-1 text-xs text-slate-500">Збережені у локальній базі даних організації.</p>
          </div>
          <button
            type="button"
            onClick={load}
            aria-label="Оновити чернетки комісіонування"
            className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.05] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>

        {viewState === "loading" ? (
          <div role="status" className="mt-5 flex items-center gap-2 text-sm text-slate-400">
            <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> Завантаження чернеток…
          </div>
        ) : null}
        {viewState === "error" ? (
          <div
            role="alert"
            className="mt-5 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-400/[0.06] p-3 text-sm text-rose-200"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {viewError}
          </div>
        ) : null}
        {viewState === "ready" && sessions.length === 0 ? (
          <div className="mt-5 rounded-2xl border border-dashed border-white/10 p-7 text-center">
            <CircleDashed className="mx-auto h-7 w-7 text-slate-600" />
            <p className="mt-3 text-sm font-medium text-white">Чернеток ще немає</p>
            <p className="mt-1 text-xs text-slate-500">Створіть намір для вже підтримуваного профілю.</p>
          </div>
        ) : null}
        {viewState === "ready" && sessions.length > 0 ? (
          <div className="mt-4 grid gap-2 xl:grid-cols-2">
            {sessions.map((session) => (
              <Link
                key={session.id}
                href={`/equipment/onboarding/${encodeURIComponent(session.id)}`}
                className="group rounded-2xl border border-white/[0.07] bg-[#06142a]/65 p-4 transition hover:border-cyan-300/20 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {session.manufacturer} {session.model}
                    </p>
                    <p className="mt-1 truncate text-[10px] text-slate-500">
                      {session.profileId ?? "Профіль не визначено"} · v{session.version}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-1 text-[9px] ${lifecycleTone[session.lifecycle]}`}
                  >
                    {lifecycleLabel[session.lifecycle]}
                  </span>
                </div>
                <p className="mt-3 text-xs text-slate-400">
                  Прив’язка:{" "}
                  {session.targetEquipmentKey
                    ? (assetNames.get(session.targetEquipmentKey) ?? session.targetEquipmentKey)
                    : "не вибрана"}
                </p>
                {session.unsupportedReason || session.blockedReason ? (
                  <p className="mt-2 flex items-center gap-1.5 text-[10px] text-amber-200">
                    <Ban className="h-3 w-3" /> {session.unsupportedReason ?? session.blockedReason}
                  </p>
                ) : null}
              </Link>
            ))}
          </div>
        ) : null}
      </section>

      <EquipmentDiscoveryInbox repository={discoveryRepository} canManage={canManage} assets={assets} />
    </div>
  );
}

function Metric({ label, value, warning = false }: { label: string; value: number; warning?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-[#06142a]/55 p-3">
      <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${warning ? "text-amber-200" : "text-white"}`}>
        {value}
      </p>
    </div>
  );
}
