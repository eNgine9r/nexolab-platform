"use client";

import { useMemo, useState } from "react";
import { Settings2 } from "lucide-react";
import { chartSeries } from "@/data/dashboard";

const ranges = ["1г", "6г", "24г", "7д", "30д"];

function createPath(points: readonly number[]) {
  return points
    .map((point, index) => {
      const x = 32 + (index / (points.length - 1)) * 568;
      const y = 162 - (point / 100) * 135;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export function TemperatureChart() {
  const [range, setRange] = useState("24г");
  const paths = useMemo(
    () => chartSeries.map((series) => ({ ...series, path: createPath(series.points) })),
    [],
  );

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-slate-600 uppercase">Live telemetry</p>
          <p className="mt-1 text-[11px] text-slate-400">Синхронізація кожні 10 секунд</p>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-black/10 p-1">
          {ranges.map((item) => (
            <button
              key={item}
              onClick={() => setRange(item)}
              className={`rounded-lg px-2.5 py-1.5 text-[9px] font-medium transition ${range === item ? "bg-blue-600 text-white shadow-[0_5px_15px_rgba(0,119,255,.2)]" : "text-slate-500 hover:text-slate-200"}`}
            >
              {item}
            </button>
          ))}
          <button
            className="ml-1 grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200"
            aria-label="Налаштування графіка"
          >
            <Settings2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-white/[0.045] bg-[#071a35]/60 p-2">
        <svg
          viewBox="0 0 630 190"
          className="h-[200px] w-full"
          role="img"
          aria-label="Графік температур за 24 години"
        >
          <defs>
            <linearGradient id="chartFade" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#0077ff" stopOpacity="0.13" />
              <stop offset="1" stopColor="#0077ff" stopOpacity="0" />
            </linearGradient>
            <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.8" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {[28, 55, 82, 109, 136, 163].map((y) => (
            <line key={y} x1="32" y1={y} x2="600" y2={y} stroke="rgba(148,163,184,.11)" strokeWidth="1" />
          ))}
          {[32, 145, 258, 371, 484, 600].map((x) => (
            <line key={x} x1={x} y1="20" x2={x} y2="163" stroke="rgba(148,163,184,.055)" strokeWidth="1" />
          ))}
          <path d={`${paths[2].path} L600 163 L32 163 Z`} fill="url(#chartFade)" />
          {paths.map((series) => (
            <g key={series.id} filter="url(#softGlow)">
              <path
                d={series.path}
                fill="none"
                stroke={series.color}
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {[0, 5, 10, 15, 20, 23].map((index) => {
                const x = 32 + (index / 23) * 568;
                const y = 162 - (series.points[index] / 100) * 135;
                return (
                  <circle
                    key={index}
                    cx={x}
                    cy={y}
                    r="2.1"
                    fill="#071a35"
                    stroke={series.color}
                    strokeWidth="1.4"
                  />
                );
              })}
            </g>
          ))}
          {["00:00", "04:00", "08:00", "12:00", "16:00", "24:00"].map((label, index) => (
            <text
              key={label}
              x={32 + index * 113.6}
              y="181"
              textAnchor={index === 0 ? "start" : index === 5 ? "end" : "middle"}
              fill="#64748b"
              fontSize="9"
            >
              {label}
            </text>
          ))}
          {["20", "10", "0", "−10", "−20", "−30"].map((label, index) => (
            <text key={label} x="24" y={31 + index * 27} textAnchor="end" fill="#64748b" fontSize="9">
              {label}
            </text>
          ))}
        </svg>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {chartSeries.map((series) => (
          <button
            key={series.id}
            className="rounded-xl border border-white/[0.055] bg-white/[0.018] p-2.5 text-left transition hover:border-white/[0.1] hover:bg-white/[0.03]"
          >
            <div className="flex items-center gap-1.5 text-[9px] text-slate-500">
              <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: series.color }} />
              {series.id}
            </div>
            <p className="mt-1.5 text-lg font-medium tracking-tight text-slate-100">{series.value}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
