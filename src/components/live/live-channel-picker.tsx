"use client";

import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { useId, useMemo, useState } from "react";

import {
  deselectChannels,
  filterPickerGroups,
  groupLiveChannelsByDevice,
  groupSelectionState,
  selectChannels,
  type ChannelNames,
} from "@/features/live/channel-picker";
import { displayUnit } from "@/features/charts/units";
import { LIVE_SELECTION_LIMIT } from "@/features/live/live-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

/**
 * Device-grouped channel selection (#1671): searchable, collapsible groups, per-device and global
 * select/deselect, operator-defined names, a visible «n із 24» counter and an explicit message when
 * the limit stops a bulk selection. It edits the same selection as the flat table below it.
 */
export function LiveChannelPicker({
  samples,
  selectedKeys,
  names,
  limit = LIVE_SELECTION_LIMIT,
  onChange,
}: {
  samples: readonly TelemetrySample[];
  selectedKeys: readonly string[];
  names: ChannelNames;
  limit?: number;
  onChange: (keys: string[]) => void;
}) {
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const allGroups = useMemo(() => groupLiveChannelsByDevice(samples, names), [names, samples]);
  const groups = useMemo(() => filterPickerGroups(allGroups, query), [allGroups, query]);
  const visibleKeys = useMemo(() => groups.flatMap((group) => group.channels.map((c) => c.key)), [groups]);
  const searching = query.trim().length > 0;

  const apply = (next: { selected: string[]; truncated: boolean }) => {
    setMessage(
      next.truncated ? `Досягнуто ліміт ${limit} каналів: частину вибраних каналів не додано.` : null,
    );
    onChange(next.selected);
  };

  const toggleCollapsed = (key: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <section
      data-testid="live-channel-picker"
      aria-labelledby="live-channel-picker-title"
      className="min-w-0 rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="live-channel-picker-title" className="text-base font-semibold text-white">
            Вибір каналів за приладами
          </h2>
          <p
            className="mt-1 text-xs text-slate-400"
            data-testid="live-channel-picker-count"
            aria-live="polite"
          >
            Вибрано {selectedKeys.length} із {limit}
            {searching ? ` · знайдено ${visibleKeys.length} каналів` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => apply(selectChannels(selectedKeys, visibleKeys, limit))}
            disabled={visibleKeys.length === 0}
            className="min-h-9 rounded-xl border border-cyan-300/25 bg-cyan-400/[0.06] px-3 text-xs font-medium text-cyan-100 hover:bg-cyan-400/10 disabled:opacity-50"
          >
            {searching ? "Вибрати знайдені" : "Вибрати всі"}
          </button>
          <button
            type="button"
            onClick={() => apply({ selected: deselectChannels(selectedKeys, visibleKeys), truncated: false })}
            disabled={!visibleKeys.some((key) => selectedKeys.includes(key))}
            className="min-h-9 rounded-xl border border-white/10 px-3 text-xs text-slate-300 hover:border-cyan-300/25 disabled:opacity-50"
          >
            {searching ? "Зняти знайдені" : "Зняти всі"}
          </button>
        </div>
      </div>

      <label htmlFor={searchId} className="mt-3 flex items-center gap-2 text-xs text-slate-400">
        <Search className="h-4 w-4" aria-hidden="true" />
        <span className="sr-only">Фільтр списку приладів і каналів</span>
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Знайти прилад, датчик або показник…"
          className="min-h-10 w-full rounded-xl border border-white/10 bg-[#081a32] px-3 text-sm text-slate-100 outline-none focus:border-cyan-300/35"
        />
      </label>
      {message ? (
        <p
          className="mt-2 text-xs font-medium text-amber-200"
          role="status"
          data-testid="live-channel-picker-message"
        >
          {message}
        </p>
      ) : null}

      {groups.length === 0 ? (
        <p className="mt-4 text-sm text-slate-400" data-testid="live-channel-picker-empty">
          Каналів не знайдено.
        </p>
      ) : (
        <ul className="mt-4 grid gap-2" aria-label="Прилади та їхні канали">
          {groups.map((group) => {
            const state = groupSelectionState(group, selectedKeys);
            const open = searching || !collapsed.has(group.key);
            const chosen = group.channels.filter((channel) => selectedKeys.includes(channel.key)).length;
            const panelId = `picker-${group.key}`;
            const keys = group.channels.map((channel) => channel.key);
            return (
              <li
                key={group.key}
                data-testid="live-channel-picker-group"
                className="rounded-2xl border border-white/[0.07] bg-[#06142a]/70"
              >
                <div className="flex items-center gap-2 px-3 py-2">
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={panelId}
                    onClick={() => toggleCollapsed(group.key)}
                    disabled={searching}
                    className="inline-flex min-h-9 flex-1 items-center gap-2 text-left text-sm font-medium text-slate-100 disabled:cursor-default"
                  >
                    {open ? (
                      <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
                    )}
                    <span className="truncate">{group.label}</span>
                    <span className="text-xs font-normal text-slate-500">
                      {group.nodeId} · вибрано {chosen} із {group.channels.length}
                    </span>
                  </button>
                  <label className="inline-flex min-h-9 items-center gap-2 text-xs text-slate-300">
                    <input
                      type="checkbox"
                      checked={state === "all"}
                      ref={(element) => {
                        if (element) element.indeterminate = state === "some";
                      }}
                      onChange={() =>
                        state === "all"
                          ? apply({ selected: deselectChannels(selectedKeys, keys), truncated: false })
                          : apply(selectChannels(selectedKeys, keys, limit))
                      }
                      aria-label={`Вибрати всі канали приладу ${group.label}`}
                      className="h-4 w-4 accent-cyan-400"
                    />
                    Усі
                  </label>
                </div>
                {open ? (
                  <ul
                    id={panelId}
                    className="grid gap-1 border-t border-white/[0.06] px-3 py-2 sm:grid-cols-2"
                  >
                    {group.channels.map((channel) => {
                      const checked = selectedKeys.includes(channel.key);
                      return (
                        <li key={channel.key}>
                          <label className="flex min-h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm text-slate-200 hover:bg-white/[0.04]">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() =>
                                checked
                                  ? apply({
                                      selected: deselectChannels(selectedKeys, [channel.key]),
                                      truncated: false,
                                    })
                                  : apply(selectChannels(selectedKeys, [channel.key], limit))
                              }
                              aria-label={`Вибрати канал ${group.label} ${channel.label} ${channel.metric}`}
                              className="h-4 w-4 accent-cyan-400"
                            />
                            <span className="truncate">{channel.label}</span>
                            <span className="ml-auto shrink-0 text-xs text-slate-500">
                              {channel.metric} · {displayUnit(channel.unit)}
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
