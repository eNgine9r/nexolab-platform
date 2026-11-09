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

type SessionViewFilter = "all" | "attention" | "in_progress" | "active";

const attentionLifecycles = new Set<CommissioningSession["lifecycle"]>([
  "blocked",
  "unsupported",
  "activation_failed",
  "rolled_back",
]);
const inProgressLifecycles = new Set<CommissioningSession["lifecycle"]>([
  "draft",
  "ready_for_preflight",
  "verified",
  "pending_activation",
]);

const lifecycleLabel: Record<CommissioningSession["lifecycle"], string> = {
  draft: "Чернетка",
  ready_for_preflight: "Готова до перевірки",
  verified: "Перевірено",
  pending_activation: "Активація…",
  active: "Read-only моніторинг активний",
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
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<SessionViewFilter>("all");
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
        setError(cause instanceof Error ? cause.message : "Чернетки комісіонування недоступні.");
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
  const attentionCount = activeSessions.filter((session) => attentionLifecycles.has(session.lifecycle)).length;
  const pendingCount = activeSessions.filter((session) => inProgressLifecycles.has(session.lifecycle)).length;
  const viewState = repository ? (loadedRepository === repository ? state : "loading") : "error";
  const viewError = repository ? error : "Локальний сервіс чернеток комісіонування не налаштований.";
  const normalizedQuery = query.trim().toLocaleLowerCase("uk-UA");
  const filteredSessions =
    viewState !== "ready"
      ? []
      : visibleSessions.filter((session) => {
          if (statusFilter === "attention" && !attentionLifecycles.has(session.lifecycle)) return false;
          if (statusFilter === "in_progress" && !inProgressLifecycles.has(session.lifecycle)) return false;
          if (statusFilter === "active" && session.lifecycle !== "active") return false;
          if (!normalizedQuery) return true;
          const targetName = session.targetEquipmentKey
            ? (assetNames.get(session.targetEquipmentKey) ?? session.targetEquipmentKey)
            : "";
          const haystack = [
            session.manufacturer,
            session.model,
            session.profileId,
            session.nodeId,
            session.busId,
            session.unitId === null ? "" : `Unit ID ${session.unitId}`,
            targetName,
          ]
            .filter(Boolean)
            .join(" ")
            .toLocaleLowerCase("uk-UA");
          return haystack.includes(normalizedQuery);
        });
  const filterOptions: { id: SessionViewFilter; label: string; count: number }[] = [
    { id: "all", label: "Усі", count: visibleSessions.length },
    { id: "attention", label: "Потрібна увага", count: attentionCount },
    { id: "in_progress", label: "У процесі", count: pendingCount },
    { id: "active", label: "Активні", count: activeSessions.filter((item) => item.lifecycle === "active").length },
  ];

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-cyan-300/10 bg-[#08182e]/90 p-4 shadow-xl shadow-black/10 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
              <Cable className="h-4 w-4" aria-hidden="true" /> RS-485 · локальні підключення
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Підключення пристроїв</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Знайдіть прилад, перевірте збережену шину та статус підключення. Активний моніторинг
              відображається лише після підтвердженої активації. Зміни в цьому списку не
              надсилають команди обладнанню.
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
            label="Моніторинг активний"
            value={viewState === "ready" ? activeSessions.filter((item) => item.lifecycle === "active").length : "—"}
          />
          <Metric label="У процесі підключення" value={viewState === "ready" ? pendingCount : "—"} />
          <Metric label="Потрібна увага" value={viewState === "ready" ? attentionCount : "—"} warning={viewState === "ready" && attentionCount > 0} />
        </div>
      </section>

      <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Прилади та чернетки підключення</h2>
            <p className="mt-1 text-xs text-slate-500">
              Збережені підключення організації. Статуси — з локальної бази, не з автоматичного сканування.
            </p>
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

        {viewState === "ready" && visibleSessions.length > 0 ? (
          <div className="mt-4 space-y-3 border-t border-white/[0.06] pt-4">
            <label className="block text-xs font-medium text-slate-200">
              Пошук підключень
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Модель, шина, Unit ID або обладнання"
                className="mt-1.5 h-11 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/15"
              />
            </label>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Фільтр за станом підключення">
              {filterOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={statusFilter === option.id}
                  onClick={() => setStatusFilter(option.id)}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-xl border px-3 text-xs font-medium transition focus-visible:ring-2 focus-visible:ring-cyan-300 ${statusFilter === option.id ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-100" : "border-white/10 text-slate-300 hover:border-cyan-300/20 hover:text-white"}`}
                >
                  {option.label}
                  <span className="tabular-nums text-[11px] opacity-75">{option.count}</span>
                </button>
              ))}
            </div>
            <p role="status" className="text-xs text-slate-400">
              Показано {filteredSessions.length} із {visibleSessions.length} збережених сесій
            </p>
          </div>
        ) : null}

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
        {viewState === "ready" && visibleSessions.length === 0 ? (
          <div className="mt-5 rounded-2xl border border-dashed border-white/10 p-7 text-center">
            <CircleDashed className="mx-auto h-7 w-7 text-slate-600" />
            <p className="mt-3 text-sm font-medium text-white">Чернеток ще немає</p>
            <p className="mt-1 text-xs text-slate-500">Створіть намір для вже підтримуваного профілю.</p>
          </div>
        ) : null}
        {viewState === "ready" && visibleSessions.length > 0 && filteredSessions.length === 0 ? (
          <div className="mt-4 rounded-xl border border-dashed border-white/10 p-5 text-center">
            <p className="text-sm font-medium text-slate-200">За заданими умовами підключень немає</p>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setStatusFilter("all");
              }}
              className="mt-2 min-h-10 rounded-lg border border-white/10 px-3 text-xs font-medium text-cyan-200 hover:border-cyan-300/30"
            >
              Скинути фільтри
            </button>
          </div>
        ) : null}
        {viewState === "ready" && filteredSessions.length > 0 ? (
          <div className="mt-4 grid gap-2 xl:grid-cols-2">
            {filteredSessions.map((session) => (
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
                    <p className="mt-1 break-words text-[11px] leading-4 text-slate-400">
                      {session.profileId ?? "Профіль не визначено"} · версія {session.version}
                    </p>
                  </div>
                  <span
                    className={`max-w-[12rem] shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-4 text-center ${lifecycleTone[session.lifecycle]}`}
                  >
                    {lifecycleLabel[session.lifecycle]}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300">
                  {session.busId ? <span className="break-all">Шина: {session.busId}</span> : null}
                  {session.unitId !== null ? <span>Unit ID: {session.unitId}</span> : null}
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  Прив’язка:{" "}
                  {session.targetEquipmentKey
                    ? (assetNames.get(session.targetEquipmentKey) ?? session.targetEquipmentKey)
                    : "не вибрана"}
                </p>
                {session.unsupportedReason || session.blockedReason ? (
                  <p className="mt-2 flex items-center gap-1.5 text-[11px] leading-4 text-amber-200">
                    <Ban className="h-3 w-3" /> {session.unsupportedReason ?? session.blockedReason}
                  </p>
                ) : null}
              </Link>
            ))}
          </div>
        ) : null}
      </section>

      <div className="space-y-2">
        <p className="px-1 text-xs leading-5 text-slate-400">
          LAN-пошук мережевих пристроїв — окрема функція. Він не визначає Modbus ID та не
          сканує активні шини RS-485.
        </p>
        <EquipmentDiscoveryInbox repository={discoveryRepository} canManage={canManage} assets={assets} />
      </div>
    </div>
  );
}

function Metric({ label, value, warning = false }: { label: string; value: number | string; warning?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-[#06142a]/55 p-3">
      <p className="text-xs font-medium text-slate-300">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${warning ? "text-amber-200" : "text-white"}`}>
        {value}
      </p>
    </div>
  );
}
