"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Eye,
  Gauge,
  Plus,
  Search,
  Snowflake,
  Thermometer,
  Trash2,
  Wifi,
} from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import {
  CreateEquipmentDialog,
  DeleteEquipmentDialog,
} from "@/components/refrigeration/refrigeration-equipment-dialogs";
import {
  refrigerationEquipment,
  type EquipmentStatus,
  type RefrigerationEquipment,
} from "@/data/refrigeration";
import type { RefrigerationEquipmentCreateInput } from "@/features/refrigeration/equipment-repository";
import {
  createRefrigerationEquipmentRuntime,
  type RefrigerationEquipmentRuntime,
} from "@/features/refrigeration/equipment-repository-runtime";

const statusStyles: Record<EquipmentStatus, string> = {
  normal: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
  warning: "border-amber-400/20 bg-amber-400/10 text-amber-300",
  alarm: "border-rose-400/20 bg-rose-400/10 text-rose-300",
  offline: "border-slate-400/20 bg-slate-400/10 text-slate-300",
};

const statusLabels: Record<EquipmentStatus, string> = {
  normal: "Норма",
  warning: "Увага",
  alarm: "Тривога",
  offline: "Offline",
};

type StatusFilter = "all" | EquipmentStatus;

type Notice = { tone: "success" | "error"; message: string } | null;

export function RefrigerationCatalogScreen({
  runtime: providedRuntime,
}: {
  runtime?: RefrigerationEquipmentRuntime;
} = {}) {
  const runtime = useMemo(
    () => providedRuntime ?? createRefrigerationEquipmentRuntime(),
    [providedRuntime],
  );
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [items, setItems] = useState<RefrigerationEquipment[]>(
    runtime.mode === "demo" ? refrigerationEquipment : [],
  );
  const [loading, setLoading] = useState(runtime.mode === "live");
  const [canManage, setCanManage] = useState(runtime.mode === "demo");
  const [notice, setNotice] = useState<Notice>(runtime.error ? { tone: "error", message: runtime.error } : null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RefrigerationEquipment | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    if (!runtime.repository) {
      setLoading(false);
      return;
    }
    try {
      const loaded = await runtime.repository.list();
      setItems(loaded);
      setNotice((current) => (current?.tone === "error" ? null : current));
    } catch (error) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "Не вдалося завантажити каталог обладнання.",
      });
    } finally {
      setLoading(false);
    }
  }, [runtime.repository]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    if (runtime.mode === "demo") {
      setCanManage(true);
      return;
    }
    if (!runtime.sessionClient) {
      setCanManage(false);
      return;
    }
    let active = true;
    void runtime.sessionClient.getSession().then((result) => {
      if (!active) return;
      setCanManage(
        result.ok &&
          result.value.memberships.some(
            (membership) =>
              (runtime.organizationId === null || membership.organizationId === runtime.organizationId) &&
              membership.permissions.includes("equipment.manage"),
          ),
      );
    });
    return () => {
      active = false;
    };
  }, [runtime.mode, runtime.organizationId, runtime.sessionClient]);

  const equipment = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("uk-UA");

    return items.filter((item) => {
      const searchText = `${item.name} ${item.code} ${item.location} ${item.model}`.toLocaleLowerCase(
        "uk-UA",
      );
      const matchesQuery = normalizedQuery.length === 0 || searchText.includes(normalizedQuery);
      const matchesStatus = status === "all" || item.status === status;

      return matchesQuery && matchesStatus;
    });
  }, [items, query, status]);

  const createEquipment = async (input: RefrigerationEquipmentCreateInput) => {
    if (!runtime.repository) return;
    setCreateBusy(true);
    setCreateError(null);
    try {
      const created = await runtime.repository.create(input);
      setItems((current) => [...current, created]);
      setCreateOpen(false);
      setNotice({ tone: "success", message: `${created.name} додано до каталогу.` });
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : "Обладнання не створено.");
    } finally {
      setCreateBusy(false);
    }
  };

  const deleteEquipment = async () => {
    if (!runtime.repository || !deleteTarget) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await runtime.repository.remove(deleteTarget.id, deleteTarget.version);
      setItems((current) => current.filter((item) => item.id !== deleteTarget.id));
      setNotice({ tone: "success", message: `${deleteTarget.name} видалено з каталогу.` });
      setDeleteTarget(null);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Обладнання не видалено.");
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Холодильне обладнання"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar title="Холодильне обладнання" onMenuOpen={() => setSidebarOpen(true)} />
        <main className="p-4 xl:p-6">
          <div className="mx-auto max-w-[1800px]">
            <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
                  Digital equipment twin
                </p>
                <h1 className="mt-2 text-2xl font-semibold text-white">Холодильне обладнання</h1>
                <p className="mt-2 max-w-2xl text-sm text-slate-400">
                  Паспорти, оперативний стан і інтерактивні схеми розміщення температурних датчиків.
                </p>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <label className="flex min-w-72 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2.5">
                  <Search className="h-4 w-4 text-slate-500" />
                  <span className="sr-only">Пошук обладнання</span>
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Пошук обладнання"
                    className="w-full bg-transparent text-sm outline-none placeholder:text-slate-600"
                  />
                </label>

                <label className="sr-only" htmlFor="equipment-status-filter">
                  Фільтр за станом
                </label>
                <select
                  id="equipment-status-filter"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as StatusFilter)}
                  className="min-h-11 rounded-xl border border-white/10 bg-[#0a1c35] px-3 py-2.5 text-sm text-slate-300 outline-none focus:border-cyan-300/35"
                >
                  <option value="all">Усі стани</option>
                  <option value="normal">Норма</option>
                  <option value="warning">Попередження</option>
                  <option value="alarm">Тривога</option>
                  <option value="offline">Offline</option>
                </select>

                {canManage ? (
                  <IconButton
                    label="Додати холодильне обладнання"
                    onClick={() => {
                      setCreateError(null);
                      setCreateOpen(true);
                    }}
                    accent
                  >
                    <Plus className="h-4 w-4" />
                  </IconButton>
                ) : null}
              </div>
            </div>

            {notice ? (
              <div
                role={notice.tone === "error" ? "alert" : "status"}
                className={`mb-4 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${
                  notice.tone === "success"
                    ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                    : "border-rose-400/20 bg-rose-400/10 text-rose-200"
                }`}
              >
                {notice.tone === "success" ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                ) : (
                  <AlertCircle className="h-4 w-4 shrink-0" />
                )}
                <span>{notice.message}</span>
              </div>
            ) : null}

            {loading ? (
              <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3" aria-label="Завантаження обладнання">
                {[0, 1, 2].map((index) => (
                  <div
                    key={index}
                    className="h-[418px] animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.025]"
                  />
                ))}
              </section>
            ) : equipment.length > 0 ? (
              <section
                className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3"
                aria-label="Перелік холодильного обладнання"
              >
                {equipment.map((item) => (
                  <article
                    key={item.id}
                    className="group overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0a1b33]/85 shadow-[0_18px_45px_rgba(0,0,0,.18)] transition hover:-translate-y-0.5 hover:border-cyan-300/20"
                  >
                    <div className="relative h-48 overflow-hidden border-b border-white/[0.07] bg-[radial-gradient(circle_at_50%_20%,rgba(34,211,238,.13),transparent_45%),linear-gradient(145deg,#0c2440,#071528)]">
                      <div className="absolute inset-x-[12%] top-[16%] bottom-0 rounded-t-2xl border border-slate-500/30 bg-[linear-gradient(90deg,#101b26_0_3%,#23384a_3%_49%,#0f1a25_49%_52%,#23384a_52%_97%,#101b26_97%)] shadow-[0_0_40px_rgba(34,211,238,.06)]">
                        {[22, 43, 64, 85].map((top) => (
                          <div
                            key={top}
                            className="absolute right-[4%] left-[4%] h-px bg-cyan-200/25"
                            style={{ top: `${top}%` }}
                          />
                        ))}
                      </div>
                      <div className="absolute top-4 left-4 flex items-center gap-2 rounded-full border border-cyan-300/15 bg-slate-950/65 px-3 py-1.5 text-[10px] text-cyan-200 backdrop-blur">
                        <Snowflake className="h-3.5 w-3.5" />
                        {item.type}
                      </div>
                    </div>

                    <div className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <h2 className="text-base font-semibold text-white">{item.name}</h2>
                          <p className="mt-1 text-xs text-slate-500">{item.location}</p>
                        </div>
                        <span
                          className={`rounded-full border px-2.5 py-1 text-[10px] ${statusStyles[item.status]}`}
                        >
                          {statusLabels[item.status]}
                        </span>
                      </div>

                      <div className="mt-4 grid grid-cols-3 gap-2">
                        <Metric icon={Thermometer} label="Середня" value={`${item.averageTemperatureC} °C`} />
                        <Metric
                          icon={Wifi}
                          label="Датчики"
                          value={`${item.onlineSensors}/${item.totalSensors}`}
                        />
                        <Metric icon={AlertTriangle} label="Тривоги" value={String(item.activeAlarms)} />
                      </div>

                      <div className="mt-4 flex items-center justify-between border-t border-white/[0.07] pt-4">
                        <div className="text-[11px] text-slate-500">
                          <span className="text-slate-300">
                            {item.manufacturer} {item.model}
                          </span>
                          <br />
                          {item.code}
                        </div>
                        <div className="flex items-center gap-2">
                          {canManage ? (
                            <IconButton
                              label={`Видалити ${item.name}`}
                              tone="danger"
                              onClick={() => {
                                setDeleteError(null);
                                setDeleteTarget(item);
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </IconButton>
                          ) : null}
                          <Link
                            href={`/refrigeration/${item.id}`}
                            aria-label={`Відкрити ${item.name}`}
                            title="Відкрити"
                            className="grid h-10 w-10 place-items-center rounded-xl border border-blue-400/20 bg-blue-500/10 text-blue-200 transition hover:bg-blue-500/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
                          >
                            <Eye className="h-4 w-4" />
                          </Link>
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </section>
            ) : (
              <section className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-6 py-16 text-center">
                <Snowflake className="mx-auto h-8 w-8 text-slate-600" />
                <h2 className="mt-4 text-sm font-semibold text-slate-200">
                  {items.length === 0 ? "Каталог холодильного обладнання порожній" : "Обладнання не знайдено"}
                </h2>
                <p className="mt-2 text-xs text-slate-500">
                  {items.length === 0
                    ? "Додайте першу вітрину або холодильну камеру."
                    : "Змініть пошуковий запит або фільтр стану."}
                </p>
                {items.length === 0 && canManage ? (
                  <button
                    type="button"
                    aria-label="Додати перше холодильне обладнання"
                    title="Додати обладнання"
                    onClick={() => setCreateOpen(true)}
                    className="mx-auto mt-5 grid h-11 w-11 place-items-center rounded-xl border border-cyan-300/25 bg-cyan-400/15 text-cyan-100 transition hover:bg-cyan-400/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
                  >
                    <Plus className="h-4 w-4" />
                  </button>
                ) : null}
              </section>
            )}
          </div>
        </main>
      </div>

      <CreateEquipmentDialog
        open={createOpen}
        busy={createBusy}
        error={createError}
        onClose={() => {
          if (!createBusy) setCreateOpen(false);
        }}
        onSubmit={createEquipment}
      />
      <DeleteEquipmentDialog
        equipment={deleteTarget}
        busy={deleteBusy}
        error={deleteError}
        onClose={() => {
          if (!deleteBusy) setDeleteTarget(null);
        }}
        onConfirm={deleteEquipment}
      />
    </div>
  );
}

function IconButton({
  label,
  children,
  onClick,
  accent = false,
  tone = "default",
}: {
  label: string;
  children: React.ReactNode;
  onClick: () => void;
  accent?: boolean;
  tone?: "default" | "danger";
}) {
  const classes = accent
    ? "border-cyan-300/25 bg-cyan-400/15 text-cyan-100 hover:bg-cyan-400/20"
    : tone === "danger"
      ? "border-rose-400/15 bg-rose-400/[0.06] text-rose-300 hover:border-rose-400/30 hover:bg-rose-400/12"
      : "border-white/10 bg-white/[0.035] text-slate-400 hover:text-white";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={`grid h-11 w-11 place-items-center rounded-xl border transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${classes}`}
    >
      {children}
    </button>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Gauge; label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-3">
      <Icon className="h-4 w-4 text-cyan-300" />
      <p className="mt-2 text-[9px] tracking-wider text-slate-600 uppercase">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-100">{value}</p>
    </div>
  );
}
