"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronRight, X } from "lucide-react";

import type { EdgeNode } from "@/data/dashboard";
import { useDashboardTelemetry } from "@/hooks/use-dashboard-telemetry";

import { AlarmsPanel } from "./alarms-panel";
import { CamerasPanel } from "./cameras-panel";
import { KpiCard } from "./kpi-card";
import { LabMap } from "./lab-map";
import { NodesPanel } from "./nodes-panel";
import { Panel } from "./panel";
import { SessionsPanel } from "./sessions-panel";
import { Sidebar } from "./sidebar";
import { TelemetryStatusBar } from "./telemetry-status-bar";
import { TemperatureChart } from "./temperature-chart";
import { Topbar } from "./topbar";

function PanelAction({ label }: { label: string }) {
  return (
    <button className="inline-flex items-center gap-1 rounded-lg border border-white/[0.065] bg-white/[0.02] px-2.5 py-1.5 text-[8px] font-medium text-slate-500 transition hover:border-blue-400/25 hover:text-slate-200">
      {label}
      <ChevronRight className="h-3 w-3" />
    </button>
  );
}

function SessionModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[80] grid place-items-center bg-[#020915]/80 p-4 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-modal-title"
    >
      <button className="absolute inset-0" onClick={onClose} aria-label="Закрити діалог" />
      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-3xl border border-cyan-300/15 bg-[linear-gradient(145deg,#0d294e,#07182f)] shadow-[0_32px_90px_rgba(0,0,0,.55)]">
        <div className="flex items-start justify-between border-b border-white/[0.065] p-5">
          <div>
            <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              New laboratory test
            </p>
            <h2 id="session-modal-title" className="mt-2 text-xl font-semibold text-white">
              Створити нову сесію
            </h2>
            <p className="mt-1 text-[11px] leading-5 text-slate-500">
              Виберіть шаблон і заповніть базові дані випробування.
            </p>
          </div>
          <button className="icon-button inline-grid" onClick={onClose} aria-label="Закрити">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form
          className="space-y-4 p-5"
          onSubmit={(event) => {
            event.preventDefault();
            onClose();
          }}
        >
          <label className="block">
            <span className="form-label">Назва випробування</span>
            <input className="form-input" defaultValue="ISO 23953 — Нова сесія" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="form-label">Методика</span>
              <select className="form-input">
                <option>ISO 23953</option>
                <option>Кліматичні випробування</option>
                <option>Smart locker test</option>
              </select>
            </label>
            <label className="block">
              <span className="form-label">Об’єкт</span>
              <select className="form-input">
                <option>Вітрина 1200</option>
                <option>Камера #02</option>
                <option>Поштомат #12</option>
              </select>
            </label>
          </div>
          <label className="block">
            <span className="form-label">Відповідальний інженер</span>
            <input className="form-input" defaultValue="Інженер лабораторії" />
          </label>
          <div className="rounded-xl border border-emerald-300/10 bg-emerald-400/[0.04] p-3 text-[10px] leading-5 text-slate-400">
            <CheckCircle2 className="mr-2 inline h-4 w-4 text-emerald-400" />
            18 датчиків та 2 камери доступні для прив’язки.
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="secondary-button" onClick={onClose}>
              Скасувати
            </button>
            <button type="submit" className="primary-button">
              Створити сесію
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function liveNode(status: ReturnType<typeof useDashboardTelemetry>["status"], records: number): EdgeNode {
  const state: EdgeNode["state"] =
    status === "live" ? "online" : status === "offline" || status === "error" ? "offline" : "warning";

  return {
    id: "edge-01",
    name: "Production Device Agent",
    channels: `${records} / 34 latest records`,
    cpu: null,
    ram: null,
    state,
    spark: [],
  };
}

export function DashboardShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activeItem, setActiveItem] = useState("Огляд");
  const [sessionModalOpen, setSessionModalOpen] = useState(false);
  const telemetry = useDashboardTelemetry();
  const nodes =
    telemetry.mode === "live"
      ? [liveNode(telemetry.status, telemetry.view?.freshSamples.length ?? 0)]
      : undefined;
  const liveSamples = telemetry.view?.samples ?? [];
  const mobileStatusTone =
    telemetry.status === "live"
      ? "border-emerald-300/10 bg-emerald-400/[0.04] text-emerald-400"
      : telemetry.status === "demo"
        ? "border-blue-300/10 bg-blue-400/[0.04] text-blue-300"
        : "border-amber-300/10 bg-amber-400/[0.04] text-amber-300";

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem={activeItem}
        onClose={() => setSidebarOpen(false)}
        onSelect={setActiveItem}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title={activeItem}
          onMenuOpen={() => setSidebarOpen(true)}
          onCreateSession={() => setSessionModalOpen(true)}
        />
        <main className="relative overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="pointer-events-none absolute bottom-0 left-1/4 h-[300px] w-[300px] rounded-full bg-cyan-400/[0.035] blur-3xl" />

          <div className="relative mx-auto max-w-[1800px]">
            <div className="mb-4 flex items-end justify-between gap-4 px-1 lg:hidden">
              <div>
                <p className="text-[9px] tracking-[0.18em] text-cyan-300 uppercase">Control center</p>
                <h1 className="mt-1 text-xl font-semibold text-white">Огляд лабораторії</h1>
              </div>
              <span className={`rounded-full border px-3 py-1.5 text-[9px] capitalize ${mobileStatusTone}`}>
                ● {telemetry.status}
              </span>
            </div>

            <TelemetryStatusBar
              mode={telemetry.mode}
              status={telemetry.status}
              lastCapturedAt={telemetry.view?.lastCapturedAt ?? null}
              ageMs={telemetry.view?.ageMs ?? null}
              rejectedFutureSamples={telemetry.view?.rejectedFutureSamples ?? 0}
              error={telemetry.error}
              onRetry={telemetry.retry}
            />

            <section
              className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6 xl:gap-3"
              aria-label="Ключові показники"
            >
              {telemetry.kpis.map((item, index) => (
                <KpiCard key={item.label} item={item} index={index} />
              ))}
            </section>

            <section className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
              <Panel
                title={telemetry.mode === "live" ? "Production node" : "Вузли системи · demo"}
                action={<PanelAction label="Всі вузли" />}
                className="xl:col-span-3"
              >
                <NodesPanel nodes={nodes} />
              </Panel>
              <Panel
                title={telemetry.mode === "live" ? "XJP60D температури" : "Температури · demo preview"}
                className="xl:col-span-6"
              >
                <TemperatureChart
                  mode={telemetry.mode}
                  status={telemetry.status}
                  samples={telemetry.temperatures}
                />
              </Panel>
              <Panel
                title={telemetry.mode === "live" ? "Telemetry alarms" : "Тривоги · demo"}
                action={<PanelAction label="Всі тривоги" />}
                className="xl:col-span-3"
              >
                <AlarmsPanel mode={telemetry.mode} samples={liveSamples} />
              </Panel>
            </section>

            <section className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
              <Panel
                title="Активні сесії · demo workflow"
                action={<PanelAction label="Всі сесії" />}
                className="xl:col-span-4"
              >
                <SessionsPanel />
              </Panel>
              <Panel
                title="Схема лабораторії · demo layout"
                action={<PanelAction label="Лабораторія 1" />}
                className="xl:col-span-5"
              >
                <LabMap />
              </Panel>
              <Panel
                title="Камери · demo preview"
                action={<PanelAction label="Всі камери" />}
                className="xl:col-span-3"
              >
                <CamerasPanel />
              </Panel>
            </section>
          </div>
        </main>
      </div>
      {sessionModalOpen && <SessionModal onClose={() => setSessionModalOpen(false)} />}
    </div>
  );
}
