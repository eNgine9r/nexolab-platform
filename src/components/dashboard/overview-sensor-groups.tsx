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
  const visibleGroups = groups.filter(
    (group) =>
      matches(group.label) ||
      group.children?.some(
        (device) =>
          matches(device.label) ||
          device.sensors.some((sensor) => matches(`${sensor.label} ${sensor.channelId}`)),
      ),
  );
  return (
    <div className="space-y-3">
      <label className="block text-xs text-slate-300">
        Пошук камери, приладу або датчика
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="mt-2 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2 text-sm text-white"
        />
      </label>
      <p role="status" className="text-[10px] text-slate-400">
        {catalog.loading
          ? "Завантаження назв… Канали доступні за точними ID."
          : catalog.error
            ? `Каталог камер недоступний: ${catalog.error} Канали доступні за точними ID.`
            : "Груповий вибір охоплює всі датчики групи, зокрема приховані пошуком."}
      </p>
      {!visibleGroups.length ? (
        <p className="text-sm text-slate-400">За цим пошуком датчиків не знайдено.</p>
      ) : null}
      {visibleGroups.map((camera) => (
        <details key={camera.id} open className="min-w-0 rounded-2xl border border-white/10 p-3">
          <summary className="cursor-pointer text-sm font-semibold break-words text-white">
            {camera.label}
          </summary>
          <GroupSelection group={camera} kind="камери" selected={selected} onToggle={onToggleGroup} />
          <div className="mt-3 space-y-2">
            {camera.children?.map((device) => {
              const sensors = device.sensors.filter(
                (sensor) =>
                  matches(camera.label) ||
                  matches(device.label) ||
                  matches(`${sensor.label} ${sensor.channelId}`),
              );
              if (!sensors.length) return null;
              return (
                <details key={device.id} open className="min-w-0 rounded-xl border border-white/[0.06] p-2">
                  <summary className="cursor-pointer text-xs font-semibold break-words text-cyan-200">
                    {device.label}
                  </summary>
                  <GroupSelection
                    group={device}
                    kind="приладу"
                    selected={selected}
                    onToggle={onToggleGroup}
                  />
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {sensors.map((sensor) => renderSensor(sensor.channelId, sensor.label))}
                  </div>
                </details>
              );
            })}
          </div>
        </details>
      ))}
    </div>
  );
}

function GroupSelection({
  group,
  kind,
  selected,
  onToggle,
}: {
  group: OverviewGroup;
  kind: string;
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
    <label className="mt-2 flex cursor-pointer items-center gap-2 text-[10px] text-slate-300">
      <input
        ref={input}
        type="checkbox"
        checked={count === group.sensors.length}
        aria-checked={mixed ? "mixed" : count === group.sensors.length}
        onChange={() => onToggle(group.sensors.map((sensor) => sensor.channelId))}
        className="h-4 w-4 shrink-0 accent-cyan-400"
      />
      <span className="min-w-0 break-words">
        Показувати всі датчики {kind}: {group.label}
      </span>
    </label>
  );
}
