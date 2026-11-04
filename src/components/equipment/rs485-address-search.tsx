"use client";

import { useEffect, useRef, useState } from "react";
import type {
  AddressSearchInput,
  CommissioningRepository,
} from "@/features/equipment/commissioning-repository";

type Props = {
  repository: CommissioningRepository;
  connection: Omit<AddressSearchInput, "unitId">;
  disabled: boolean;
  onSelect: (unitId: number) => void;
  onRunningChange: (running: boolean) => void;
  selectFirstMatch?: boolean;
};

export function Rs485AddressSearch(props: Props) {
  const identity = `${props.connection.nodeId}:${props.connection.busId}:${props.connection.stableTransportIdentifier}`;
  const [context, setContext] = useState({ repository: props.repository, identity, generation: 0 });
  if (context.repository !== props.repository || context.identity !== identity) {
    setContext({ repository: props.repository, identity, generation: context.generation + 1 });
    return null;
  }
  return <SearchPanel key={context.generation} {...props} />;
}

function SearchPanel({
  repository,
  connection,
  disabled,
  onSelect,
  onRunningChange,
  selectFirstMatch,
}: Props) {
  const [confirmed, setConfirmed] = useState(false);
  const [running, setRunning] = useState(false);
  const [checked, setChecked] = useState(0);
  const [candidates, setCandidates] = useState<number[]>([]);
  const [status, setStatus] = useState("Ще не запускався.");
  const request = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      request.current?.abort();
    },
    [],
  );
  useEffect(() => {
    onRunningChange(running);
    return () => onRunningChange(false);
  }, [running, onRunningChange]);
  useEffect(() => {
    if (disabled) request.current?.abort();
  }, [disabled]);

  const start = async () => {
    if (disabled || !confirmed || request.current || !repository.searchAddress) return;
    const controller = new AbortController();
    request.current = controller;
    setRunning(true);
    setChecked(0);
    setCandidates([]);
    setStatus("Шукаємо прилад…");
    try {
      for (let unitId = 1; unitId <= 247; unitId++) {
        if (controller.signal.aborted) return;
        const result = await repository.searchAddress({ ...connection, unitId }, controller.signal);
        if (controller.signal.aborted) return;
        if (result.state !== "completed") throw new Error("search_failed");
        if (result.candidates.length) setCandidates((current) => [...current, unitId]);
        setChecked(unitId);
        if (result.candidates.length && selectFirstMatch) {
          onSelect(unitId);
          setStatus("Прилад знайдено. Адресу підставлено автоматично.");
          return;
        }
      }
      setStatus(
        "Пошук завершено. Виберіть адресу зі списку відповідей або перевірте підключення, якщо список порожній.",
      );
    } catch {
      if (!controller.signal.aborted)
        setStatus(
          "Пошук перервано через помилку. Перевірте стан адаптера та доступність пошуку у встановленій версії системи.",
        );
    } finally {
      if (request.current === controller) {
        request.current = null;
        setRunning(false);
        if (controller.signal.aborted)
          setStatus("Пошук зупинено. Показані лише відповіді, отримані до зупинки.");
      }
    }
  };

  if (!repository.searchAddress) return null;
  return (
    <section
      aria-label="Пошук адреси Dixell XJP60D"
      className="rounded-2xl border border-cyan-300/15 p-4 text-xs"
    >
      <h3 className="text-sm font-semibold text-white">Не знаєте адресу Dixell XJP60D?</h3>
      <p className="mt-2 leading-5 text-slate-300">
        Перевіримо адреси 1–247 для профілю 9600 8N1. Це може зайняти кілька хвилин. Відповідь ще не
        підтверджує модель приладу.
      </p>
      <label className="mt-3 flex items-start gap-2 text-slate-200">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={disabled || running}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        Підключено один окремий XJP60D; ця лінія не з’єднана з робочою RS-485.
      </label>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || running || !confirmed}
          onClick={() => void start()}
          className="rounded-xl bg-cyan-300 px-4 py-2 font-semibold text-slate-950 disabled:opacity-50"
        >
          Знайти адресу
        </button>
        {running ? (
          <button
            type="button"
            onClick={() => request.current?.abort()}
            className="rounded-xl border border-white/20 px-4 py-2"
          >
            Зупинити пошук
          </button>
        ) : null}
      </div>
      <p role="status" aria-live="polite" className="mt-3 text-slate-300">
        {status} Перевірено адрес: {checked}/247.
      </p>
      {candidates.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {candidates.map((unitId) => (
            <button
              key={unitId}
              type="button"
              disabled={disabled || running}
              onClick={() => onSelect(unitId)}
              className="rounded-xl border border-emerald-300/30 px-3 py-2 disabled:opacity-50"
            >
              Вибрати адресу {unitId}
            </button>
          ))}
        </div>
      ) : null}
      <p className="mt-3 text-slate-400">
        Після вибору виконайте перевірку підключення. Реєстрація та моніторинг вмикаються окремо.
      </p>
    </section>
  );
}
