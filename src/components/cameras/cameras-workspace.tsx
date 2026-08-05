"use client";

import { Camera, Search, ShieldAlert, VideoOff } from "lucide-react";
import { useMemo, useState } from "react";

import type { CameraRecord, CameraState } from "@/features/cameras/domain";

const STATE_LABELS: Record<CameraState, string> = {
  configured: "Налаштовано, не перевірено",
  online: "Онлайн",
  offline: "Офлайн",
  unavailable: "Недоступно у браузері",
  invalid: "Некоректна конфігурація",
};

interface CamerasWorkspaceProps {
  items: CameraRecord[];
  rejected: number;
}

export function CamerasWorkspace({
  items,
  rejected,
}: CamerasWorkspaceProps) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<"all" | CameraState>("all");

  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("uk");

    return items.filter((camera) => {
      const matchesState = state === "all" || camera.state === state;
      const matchesQuery =
        !normalized ||
        [camera.id, camera.name, camera.zone ?? "", camera.endpoint ?? ""]
          .join(" ")
          .toLocaleLowerCase("uk")
          .includes(normalized);

      return matchesState && matchesQuery;
    });
  }, [items, query, state]);

  const onlineCount = items.filter(
    (item) => item.state === "online",
  ).length;
  const attentionCount = items.filter((item) =>
    ["offline", "unavailable", "invalid"].includes(item.state),
  ).length;

  return (
    <section className="space-y-4" aria-labelledby="cameras-title">
      <header className="rounded-3xl border border-white/10 bg-[#091a31]/95 p-5 shadow-2xl shadow-black/20">
        <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">
          Local camera readiness
        </p>
        <h1
          id="cameras-title"
          className="mt-2 text-2xl font-semibold text-white"
        >
          Камери
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          Лише перевірений локальний inventory і чесні стани доступності.
          Статична конфігурація або декоративне зображення не вважаються
          доказом LIVE.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Налаштовано" value={items.length} />
        <Metric label="Підтверджено онлайн" value={onlineCount} />
        <Metric label="Потребує уваги" value={attentionCount + rejected} />
      </div>

      <div className="grid gap-3 rounded-2xl border border-white/10 bg-[#091a31]/80 p-4 md:grid-cols-[1fr_240px]">
        <label className="relative block">
          <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <span className="sr-only">Пошук камер</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Камера, зона або endpoint"
            className="w-full rounded-xl border border-white/10 bg-[#06142a] py-2.5 pr-3 pl-10 text-sm text-white outline-none focus:border-cyan-300/40"
          />
        </label>
        <label>
          <span className="sr-only">Фільтр стану</span>
          <select
            value={state}
            onChange={(event) =>
              setState(event.target.value as "all" | CameraState)
            }
            className="w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-300/40"
          >
            <option value="all">Усі стани</option>
            {Object.entries(STATE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {items.length === 0 ? (
        <div className="rounded-3xl border border-dashed border-cyan-300/20 bg-[#091a31]/70 p-8 text-center">
          <VideoOff className="mx-auto h-10 w-10 text-cyan-300" />
          <h2 className="mt-4 text-lg font-semibold text-white">
            Камери не налаштовані
          </h2>
          <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">
            У репозиторії немає перевіреного camera inventory або безпечного
            media gateway. NEXOLAB не показує вигадані LIVE-потоки й не
            відкриває raw RTSP у браузері.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-[#091a31]/70 p-6 text-center text-sm text-slate-400">
          За поточними фільтрами камер не знайдено.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((camera) => (
            <article
              key={camera.id}
              className="rounded-2xl border border-white/10 bg-[#091a31]/90 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-cyan-400/10">
                    <Camera className="h-5 w-5 text-cyan-300" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="truncate font-medium text-white">
                      {camera.name}
                    </h2>
                    <p className="text-xs text-slate-500">{camera.id}</p>
                  </div>
                </div>
                <span className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-slate-300">
                  {STATE_LABELS[camera.state]}
                </span>
              </div>
              <dl className="mt-4 space-y-2 text-sm">
                <Row label="Зона" value={camera.zone ?? "Не вказано"} />
                <Row label="Джерело" value={camera.sourceKind} />
                <Row
                  label="Endpoint"
                  value={camera.endpoint ?? "Приховано або відсутній"}
                />
              </dl>
              {camera.reason ? (
                <p className="mt-4 flex gap-2 rounded-xl bg-amber-400/10 p-3 text-xs leading-5 text-amber-100">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                  {camera.reason}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[#091a31]/80 p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[90px_1fr] gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-all text-slate-300">{value}</dd>
    </div>
  );
}
