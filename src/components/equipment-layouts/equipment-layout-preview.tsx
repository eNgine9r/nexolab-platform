"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { AlertTriangle, ImageOff, X } from "lucide-react";

import type { LayoutCatalogReadyItem } from "@/features/equipment-layouts/layout-catalog";

export function EquipmentLayoutPreview({
  item,
  onClose,
}: {
  item: LayoutCatalogReadyItem;
  onClose: () => void;
}) {
  const published = item.published;
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);

  if (!published) return null;

  const sourceUrl = published.image.sourceUrl;
  const aspectRatio =
    published.image.widthPx > 0 && published.image.heightPx > 0
      ? `${published.image.widthPx} / ${published.image.heightPx}`
      : "16 / 10";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 p-3 backdrop-blur-sm sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="layout-preview-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="max-h-[94vh] w-full max-w-6xl overflow-auto rounded-3xl border border-cyan-300/15 bg-[#07172d] shadow-2xl shadow-black/50">
        <header className="sticky top-0 z-20 flex items-start justify-between gap-4 border-b border-white/[0.07] bg-[#07172d]/95 px-4 py-4 backdrop-blur-xl sm:px-6">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
              Опублікована схема · r{published.revision}
            </p>
            <h2 id="layout-preview-title" className="mt-1 text-lg font-semibold text-white">
              {item.equipment.code} · {item.equipment.name}
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              {published.placements.length} позицій · {formatDateTime(published.publishedAt)} ·{" "}
              {published.publishedBy}
            </p>
          </div>
          <button
            type="button"
            aria-label="Закрити попередній перегляд"
            title="Закрити"
            onClick={onClose}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] hover:text-white focus:ring-2 focus:ring-cyan-300 focus:outline-none"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="p-4 sm:p-6">
          <div
            className="relative isolate mx-auto w-full overflow-hidden rounded-2xl border border-cyan-300/15 bg-slate-950"
            style={{ aspectRatio }}
          >
            {sourceUrl && !imageFailed ? (
              <Image
                src={sourceUrl}
                alt={published.image.alt}
                fill
                unoptimized
                sizes="(min-width: 1280px) 1120px, 96vw"
                className="object-contain"
                onError={() => setImageFailed(true)}
              />
            ) : (
              <div className="absolute inset-0 grid place-items-center p-6 text-center">
                <div>
                  <ImageOff className="mx-auto h-9 w-9 text-slate-500" />
                  <p className="mt-3 text-sm font-medium text-slate-300">
                    {sourceUrl ? "Підписане посилання на фото недоступне" : "Фото ревізії відсутнє"}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Закрийте preview, оновіть каталог і повторіть відкриття.
                  </p>
                </div>
              </div>
            )}

            <div className="pointer-events-none absolute inset-0 z-10 bg-gradient-to-b from-transparent to-slate-950/15" />
            <div className="pointer-events-none absolute inset-0 z-20">
              {published.placements.map((placement, index) => (
                <span
                  key={placement.sensorId}
                  className="absolute grid h-7 min-w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-md border border-cyan-100/90 bg-cyan-950/90 px-1 text-[8px] font-bold text-cyan-50 shadow-lg shadow-black/60"
                  style={{ left: `${placement.x * 100}%`, top: `${placement.y * 100}%` }}
                  title={placement.sensorId}
                >
                  {index + 1}
                </span>
              ))}
            </div>
          </div>

          {imageFailed ? (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-300/20 bg-amber-400/10 p-3 text-xs text-amber-100">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              Preview залишається read-only. Жодна чернетка, ревізія або image metadata не змінена.
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}
