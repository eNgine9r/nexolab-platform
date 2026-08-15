"use client";

import { ChevronRight, Search } from "lucide-react";
import { useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import {
  canonicalizeTelemetryPointSelection,
  flattenTelemetryPointHierarchy,
  searchTelemetryPointHierarchy,
  telemetryPointNodeSelectionState,
  toggleTelemetryPointNodeSelection,
  type TelemetryPointHierarchy,
  type TelemetryPointNode,
  type TelemetryPointSelectionState,
  type TelemetryPointTreeRow,
} from "@/features/telemetry-selection/hierarchy";

export type TelemetryPointSelectorProps = {
  hierarchy: TelemetryPointHierarchy;
  value: readonly string[];
  onConfirm: (selected: string[]) => void;
  onCancel?: () => void;
  maxSelection?: number;
  maxVisibleNodes?: number;
  initialExpandedNodeIds?: readonly string[];
  title?: string;
};

type VersionedDraft = {
  committedSignature: string;
  selected: string[];
};

type VersionedStatus = {
  committedSignature: string;
  message: string | null;
};

function ariaChecked(state: TelemetryPointSelectionState): boolean | "mixed" {
  if (state === "checked") return true;
  if (state === "mixed") return "mixed";
  return false;
}

function limitLabel(limit: number): string {
  return Number.isFinite(limit) ? ` / ${Math.max(0, Math.floor(limit))}` : "";
}

function normalizedLimit(limit: number | undefined): number {
  if (limit === undefined || !Number.isFinite(limit)) return Number.POSITIVE_INFINITY;
  return Math.max(0, Math.floor(limit));
}

function selectionMarker(state: TelemetryPointSelectionState): string {
  if (state === "checked") return "✓";
  if (state === "mixed") return "−";
  return "";
}

export function TelemetryPointSelector({
  hierarchy,
  value,
  onConfirm,
  onCancel,
  maxSelection,
  maxVisibleNodes,
  initialExpandedNodeIds = [],
  title = "Точки телеметрії",
}: TelemetryPointSelectorProps) {
  const treeLabelId = useId();
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const maximum = normalizedLimit(maxSelection);
  const committed = useMemo(() => canonicalizeTelemetryPointSelection(hierarchy, value), [hierarchy, value]);
  const committedSignature = committed.join("\u0000");
  const [draftState, setDraftState] = useState<VersionedDraft>(() => ({
    committedSignature,
    selected: committed,
  }));
  const [query, setQuery] = useState("");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set(initialExpandedNodeIds));
  const [activeId, setActiveId] = useState<string | null>(null);
  const [statusState, setStatusState] = useState<VersionedStatus>(() => ({
    committedSignature,
    message: null,
  }));

  const draft = draftState.committedSignature === committedSignature ? draftState.selected : committed;
  const statusMessage = statusState.committedSignature === committedSignature ? statusState.message : null;
  const setDraft = (selected: string[]) => {
    setDraftState({ committedSignature, selected });
  };
  const setStatusMessage = (message: string | null) => {
    setStatusState({ committedSignature, message });
  };

  const searchResult = useMemo(() => searchTelemetryPointHierarchy(hierarchy, query), [hierarchy, query]);
  const visible = useMemo(
    () =>
      flattenTelemetryPointHierarchy(searchResult.roots, expandedIds, {
        forceExpanded: Boolean(query.trim()),
        maxVisibleNodes,
      }),
    [expandedIds, maxVisibleNodes, query, searchResult.roots],
  );
  const visibleIds = useMemo(() => new Set(visible.rows.map((row) => row.node.id)), [visible.rows]);
  const effectiveActiveId =
    activeId && visibleIds.has(activeId) ? activeId : (visible.rows[0]?.node.id ?? null);
  const selectedSet = useMemo(() => new Set(draft), [draft]);
  const dirty = draft.join("\u0000") !== committedSignature;

  const focusNode = (id: string | null) => {
    if (!id) return;
    setActiveId(id);
    rowRefs.current.get(id)?.focus();
  };

  const toggleExpansion = (node: TelemetryPointNode) => {
    if (node.kind === "point") return;
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(node.id)) next.delete(node.id);
      else next.add(node.id);
      return next;
    });
  };

  const toggleSelection = (node: TelemetryPointNode) => {
    const result = toggleTelemetryPointNodeSelection(hierarchy, node, draft, maximum);
    if (result.reason === "limit") {
      setStatusMessage(`Ліміт вибору — ${maximum}. Зменште поточний вибір перед додаванням цієї групи.`);
      return;
    }
    setStatusMessage(null);
    if (result.changed) setDraft(result.selected);
  };

  const moveFocus = (rowIndex: number) => {
    const boundedIndex = Math.min(Math.max(rowIndex, 0), visible.rows.length - 1);
    focusNode(visible.rows[boundedIndex]?.node.id ?? null);
  };

  const onTreeItemKeyDown = (
    event: ReactKeyboardEvent<HTMLDivElement>,
    row: TelemetryPointTreeRow,
    index: number,
  ) => {
    const node = row.node;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveFocus(index + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveFocus(index - 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      moveFocus(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      moveFocus(visible.rows.length - 1);
      return;
    }
    if (event.key === "ArrowRight" && node.kind !== "point") {
      event.preventDefault();
      if (!expandedIds.has(node.id) && !query.trim()) {
        toggleExpansion(node);
      } else {
        const nextRow = visible.rows[index + 1];
        if (nextRow && nextRow.level > row.level) focusNode(nextRow.node.id);
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (node.kind !== "point" && expandedIds.has(node.id) && !query.trim()) {
        toggleExpansion(node);
      } else {
        focusNode(node.parentId);
      }
      return;
    }
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      toggleSelection(node);
    }
  };

  return (
    <section className="min-w-0 rounded-3xl border border-white/[0.08] bg-[#091a31]/95 p-4 text-slate-100 sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Telemetry selection</p>
          <h2 id={treeLabelId} className="mt-1 text-lg font-semibold text-white">
            {title}
          </h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
            Лабораторія / зона → тип обладнання → обладнання → канал і метрика. Зміни застосовуються лише
            після підтвердження.
          </p>
        </div>
        <div
          data-testid="telemetry-selection-count"
          className="shrink-0 rounded-xl border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-xs text-slate-300"
        >
          Обрано <span className="font-semibold text-white">{draft.length}</span>
          {limitLabel(maximum)}
        </div>
      </div>

      <label className="mt-4 grid gap-1.5 text-xs font-medium text-slate-400">
        Пошук
        <span className="relative block">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-500"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setStatusMessage(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" && visible.rows.length > 0) {
                event.preventDefault();
                focusNode(visible.rows[0].node.id);
              }
            }}
            placeholder="Лабораторія, зона, обладнання, канал, метрика..."
            className="h-11 w-full rounded-xl border border-white/10 bg-[#06142a] pr-3 pl-10 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-400/10"
          />
        </span>
      </label>

      <div className="mt-4 min-w-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-[#06142a]/55">
        {visible.rows.length === 0 ? (
          <div className="grid min-h-36 place-items-center p-6 text-center">
            <div>
              <p className="text-sm font-medium text-slate-200">Точок телеметрії не знайдено</p>
              <p className="mt-1 text-xs text-slate-500">Змініть пошуковий запит або перевірте каталог.</p>
            </div>
          </div>
        ) : (
          <div
            role="tree"
            aria-labelledby={treeLabelId}
            aria-multiselectable="true"
            className="max-h-[560px] min-w-0 overflow-auto p-2"
          >
            {visible.rows.map((row, index) => {
              const node = row.node;
              const branch = node.kind !== "point";
              const expanded = branch && (Boolean(query.trim()) || expandedIds.has(node.id));
              const state = telemetryPointNodeSelectionState(node, selectedSet);
              return (
                <div
                  key={node.id}
                  ref={(element) => {
                    if (element) rowRefs.current.set(node.id, element);
                    else rowRefs.current.delete(node.id);
                  }}
                  role="treeitem"
                  aria-level={row.level}
                  aria-expanded={branch ? expanded : undefined}
                  aria-checked={ariaChecked(state)}
                  aria-selected={state === "checked"}
                  tabIndex={effectiveActiveId === node.id ? 0 : -1}
                  data-telemetry-node-id={node.id}
                  onFocus={() => setActiveId(node.id)}
                  onKeyDown={(event) => onTreeItemKeyDown(event, row, index)}
                  onClick={() => toggleSelection(node)}
                  className="group flex min-h-10 min-w-0 cursor-pointer items-center gap-2 rounded-xl px-2 py-1.5 text-sm outline-none hover:bg-white/[0.04] focus-visible:bg-cyan-400/[0.08] focus-visible:ring-2 focus-visible:ring-cyan-300/70"
                  style={{ paddingInlineStart: `${8 + (row.level - 1) * 20}px` }}
                >
                  {branch ? (
                    <button
                      type="button"
                      tabIndex={-1}
                      aria-label={`${expanded ? "Згорнути" : "Розгорнути"} ${node.label}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (!query.trim()) toggleExpansion(node);
                      }}
                      className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-slate-500 hover:bg-white/[0.06] hover:text-white"
                    >
                      <ChevronRight
                        className={`h-4 w-4 transition-transform ${expanded ? "rotate-90" : ""}`}
                        aria-hidden="true"
                      />
                    </button>
                  ) : (
                    <span className="h-7 w-7 shrink-0" aria-hidden="true" />
                  )}
                  <span
                    className={`grid h-5 w-5 shrink-0 place-items-center rounded-md border text-xs font-bold ${
                      state === "checked"
                        ? "border-cyan-300/50 bg-cyan-400/20 text-cyan-100"
                        : state === "mixed"
                          ? "border-amber-300/40 bg-amber-400/10 text-amber-100"
                          : "border-white/15 bg-white/[0.02] text-transparent"
                    }`}
                    aria-hidden="true"
                  >
                    {selectionMarker(state)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-slate-200">{node.label}</span>
                  {node.kind === "point" ? (
                    <span className="hidden shrink-0 text-xs text-slate-500 sm:inline">
                      {node.point.metric} · {node.point.unit}
                    </span>
                  ) : (
                    <span className="shrink-0 text-xs text-slate-600">{node.leafKeys.length}</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {visible.truncated ? (
        <p className="mt-2 text-xs text-amber-200" role="status">
          Показано перші {visible.rows.length} вузлів. Уточніть пошук, щоб звузити великий каталог.
        </p>
      ) : null}
      {statusMessage ? (
        <p className="mt-2 text-xs text-amber-200" role="status">
          {statusMessage}
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] pt-4">
        <p className="text-xs text-slate-500">
          {dirty ? "Є непідтверджені зміни." : "Вибір відповідає збереженому стану."}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setDraft(committed);
              setQuery("");
              setStatusMessage(null);
              onCancel?.();
            }}
            className="min-h-10 rounded-xl border border-white/10 px-4 text-xs font-medium text-slate-300 hover:border-white/20 hover:text-white focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            Скасувати
          </button>
          <button
            type="button"
            onClick={() => {
              const canonical = canonicalizeTelemetryPointSelection(hierarchy, draft);
              setDraft(canonical);
              setStatusMessage("Вибір підготовлено до застосування.");
              onConfirm(canonical);
            }}
            className="min-h-10 rounded-xl border border-cyan-300/30 bg-cyan-400/10 px-4 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/15 focus-visible:ring-2 focus-visible:ring-cyan-300"
          >
            Підтвердити вибір
          </button>
        </div>
      </div>
    </section>
  );
}
