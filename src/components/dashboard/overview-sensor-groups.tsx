"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { buildOverviewSensorHierarchy, type OverviewGroup } from "./overview-sensor-hierarchy";
import { useOverviewSensorCatalog } from "./use-overview-sensor-catalog";

export function OverviewSensorGroups({
  organizationId,
  nodeId,
  channelIds,
  selected,
  onToggleGroup,
  renderSensor,
}: {
  organizationId: string | null;
  nodeId: string | null;
  channelIds: readonly string[];
  selected: readonly string[];
  onToggleGroup: (ids: readonly string[]) => void;
  renderSensor: (channelId: string, label: string) => ReactNode;
}) {
  const catalog = useOverviewSensorCatalog(organizationId, nodeId);
  const groups = useMemo(
    () => buildOverviewSensorHierarchy(channelIds, nodeId, catalog.equipment),
    [channelIds, nodeId, catalog.equipment],
  );
  const [query, setQuery] = useState("");
  const search = query.trim().toLocaleLowerCase("uk-UA");
  const matches = (value: string) => value.toLocaleLowerCase("uk-UA").includes(search);
  const visibleGroups = groups
    .map((group) => {
      const matchesGroup = matches(group.label) || (group.context ? matches(group.context) : false);
      return {
        group,
        sensors: matchesGroup
          ? group.sensors
          : group.sensors.filter((sensor) => matches(`${sensor.label} ${sensor.channelId}`)),
      };
    })
    .filter((item) => item.sensors.length > 0);

  return (
    <div className="space-y-2.5">
      <label className="block text-xs font-medium text-slate-200">
        Пошук приладу або датчика
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Назва приладу, камера або ID каналу"
          className="mt-1.5 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-white placeholder:text-slate-500"
        />
      </label>
      <p role="status" className="text-[11px] leading-4 text-slate-400">
        {catalog.loading
          ? "Завантаження назв… Канали доступні за точними ID."
          : catalog.error
            ? `Каталог камер недоступний: ${catalog.error} Канали доступні за точними ID.`
            : "Вибір усієї групи змінює всі її канали, навіть якщо пошук приховав частину."}
      </p>
      {!visibleGroups.length ? (
        <p className="py-3 text-sm text-slate-400">За цим пошуком датчиків не знайдено.</p>
      ) : null}
      {visibleGroups.map(({ group, sensors }) => {
        const selectedCount = group.sensors.filter((sensor) => selected.includes(sensor.channelId)).length;
        return (
          <details
            key={group.id}
            open={Boolean(search) || groups.length <= 2}
            className="min-w-0 rounded-xl border border-white/10 bg-white/[0.018] p-3"
          >
            <summary className="cursor-pointer text-xs font-semibold break-words text-white">
              {group.label}
              <span className="ml-2 text-[11px] font-normal text-slate-400">
                {selectedCount}/{group.sensors.length} показано
              </span>
            </summary>
            {group.context ? (
              <p className="mt-1 text-[11px] leading-4 text-slate-400">Розташування: {group.context}</p>
            ) : group.id === "unconfirmed" ? (
              <p className="mt-1 text-[11px] leading-4 text-amber-200">
                Канали доступні за ID без обов’язкової прив’язки до камери.
              </p>
            ) : null}
            <GroupSelection group={group} selected={selected} onToggle={onToggleGroup} />
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {sensors.map((sensor) => renderSensor(sensor.channelId, sensor.label))}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function GroupSelection({
  group,
  selected,
  onToggle,
}: {
  group: OverviewGroup;
  selected: readonly string[];
  onToggle: (ids: readonly string[]) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const count = group.sensors.filter((sensor) => selected.includes(sensor.channelId)).length;
  const mixed = count > 0 && count < group.sensors.length;
  useEffect(() => {
    if (input.current) input.current.indeterminate = mixed;
  }, [mixed]);
  return (
    <label className="mt-2 flex cursor-pointer items-center gap-2 text-[11px] leading-4 text-slate-300">
      <input
        ref={input}
        type="checkbox"
        checked={count === group.sensors.length}
        aria-checked={mixed ? "mixed" : count === group.sensors.length}
        onChange={() => onToggle(group.sensors.map((sensor) => sensor.channelId))}
        className="h-4 w-4 shrink-0 accent-cyan-400"
      />
      <span className="min-w-0 break-words">
        Показувати всі датчики {group.id === "unconfirmed" ? "групи" : "приладу"}: {group.label}
      </span>
    </label>
  );
}
