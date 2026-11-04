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
import { instrumentLiveLink } from "@/features/equipment/instrument-live-link";

const lifecycleLabel: Record<CommissioningSession["lifecycle"], string> = {
  draft: "Чернетка",
  ready_for_preflight: "Готова до перевірки",
  verified: "Перевірено",
  pending_activation: "Активація…",
  active: "Зчитування ввімкнено",
  activation_failed: "Активація не завершена",
  rolled_back: "Відкочено",
  blocked: "Заблокована",
  unsupported: "Профіль не підтримується",
  cancelled: "Скасована",
};

const lifecycleTone: Record<CommissioningSession["lifecycle"], string> = {
  draft: "border-cyan-400/20 bg-cyan-400/10 text-cyan-200",
  ready_for_preflight: "border-blue-400/20 bg-blue-400/10 text-blue-200",
  verified: "border-cyan-400/20 bg-cyan-400/10 text-cyan-100",
  pending_activation: "border-amber-400/20 bg-amber-400/10 text-amber-100",
  active: "border-emerald-400/20 bg-emerald-400/10 text-emerald-100",
  activation_failed: "border-rose-400/20 bg-rose-400/10 text-rose-200",
  rolled_back: "border-slate-400/20 bg-slate-400/10 text-slate-300",
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
  const [loadedRepository, setLoadedRepository] = useState<CommissioningRepository | null>(null);
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
        setLoadedRepository(repository);
        setState("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setLoadedRepository(repository);
        setError(cause instanceof Error ? cause.message : "Список приладів недоступний.");
        setState("error");
      });
    return () => controller.abort();
  }, [epoch, repository]);

  const visibleSessions = loadedRepository === repository ? sessions : [];
  const assetNames = new Map(
    assets
      .filter((asset) => asset.category === "refrigeration-equipment")
      .map((asset) => [asset.id, asset.displayName]),
  );
  const activeSessions = visibleSessions.filter((session) => session.lifecycle !== "cancelled");
  const blockedCount = activeSessions.filter(
    (session) => session.lifecycle === "blocked" || session.lifecycle === "unsupported",
  ).length;
  const viewState = repository ? (loadedRepository === repository ? state : "loading") : "error";
  const viewError = repository ? error : "Локальний сервіс підключень не налаштований.";

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-cyan-300/10 bg-[#08182e]/90 p-4 shadow-xl shadow-black/10 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
              <Cable className="h-4 w-4" /> Прилади
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Підключені прилади</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Додайте прилад і відкрийте його показники. Назву та підключення можна переглянути в
              налаштуваннях.
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
          <Metric
            label="У моніторингу"
            value={activeSessions.filter((item) => item.lifecycle === "active").length}
          />
          <Metric
            label="Готові до підключення"
            value={
              activeSessions.filter((item) => ["ready_for_preflight", "verified"].includes(item.lifecycle))
                .length
            }
          />
          <Metric label="Потребують уваги" value={blockedCount} warning={blockedCount > 0} />
        </div>
      </section>

      <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Мої прилади</h2>
            <p className="mt-1 text-xs text-slate-500">
              Актуальність показників і стан зв’язку відображаються на сторінці даних.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            aria-label="Оновити список приладів"
            className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.05] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>

        {viewState === "loading" ? (
          <div role="status" className="mt-5 flex items-center gap-2 text-sm text-slate-400">
            <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> Завантаження приладів…
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
        {viewState === "ready" && visibleSessions.length === 0 ? (
          <div className="mt-5 rounded-2xl border border-dashed border-white/10 p-7 text-center">
            <CircleDashed className="mx-auto h-7 w-7 text-slate-600" />
            <p className="mt-3 text-sm font-medium text-white">Приладів ще немає</p>
            <p className="mt-1 text-xs text-slate-500">Натисніть «Підключити пристрій», щоб додати перший.</p>
          </div>
        ) : null}
        {viewState === "ready" && visibleSessions.length > 0 ? (
          <div className="mt-4 grid gap-2 xl:grid-cols-2">
            {visibleSessions.map((session) => (
              <article
                key={session.id}
                className="rounded-2xl border border-white/[0.07] bg-[#06142a]/65 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {session.displayName || `${session.manufacturer} ${session.model}`}
                    </p>
                    {session.displayName ? (
                      <p className="mt-1 truncate text-xs text-slate-500">
                        {session.manufacturer} {session.model}
                      </p>
                    ) : null}
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-1 text-[9px] ${lifecycleTone[session.lifecycle]}`}
                  >
                    {lifecycleLabel[session.lifecycle]}
                  </span>
                </div>
                <p className="mt-3 text-xs text-slate-400">
                  Адреса {session.unitId ?? "—"} ·{" "}
                  {session.targetEquipmentKey
                    ? `Прив’язка: ${assetNames.get(session.targetEquipmentKey) ?? session.targetEquipmentKey}`
                    : "Самостійний прилад"}
                </p>
                {session.unsupportedReason || session.blockedReason ? (
                  <p className="mt-2 flex items-center gap-1.5 text-[10px] text-amber-200">
                    <Ban className="h-3 w-3" /> {session.unsupportedReason ?? session.blockedReason}
                  </p>
                ) : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  {instrumentLiveLink(session) ? (
                    <Link
                      href={instrumentLiveLink(session)!}
                      aria-label={`Показники: ${session.displayName || `${session.manufacturer} ${session.model}`}`}
                      className="inline-flex min-h-11 items-center justify-center rounded-xl bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-200 focus:ring-2 focus:ring-cyan-300 focus:outline-none"
                    >
                      Показники
                    </Link>
                  ) : null}
                  <Link
                    href={`/equipment/onboarding/${encodeURIComponent(session.id)}`}
                    aria-label={`Налаштування: ${session.displayName || `${session.manufacturer} ${session.model}`}`}
                    className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/[0.05] focus:ring-2 focus:ring-cyan-300 focus:outline-none"
                  >
                    {session.lifecycle === "active" ? "Налаштування" : "Переглянути підключення"}
                  </Link>
                </div>
              </article>
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
