"use client";

import { useEffect, useRef, useState } from "react";
import type {
  AddressSearchInput,
  CommissioningConnectionSerial,
  CommissioningRepository,
} from "@/features/equipment/commissioning-repository";

type SearchProfile = { id: string; version: string; displayName: string };
type Props = {
  repository: CommissioningRepository;
  connection: Omit<AddressSearchInput, "unitId">;
  disabled: boolean;
  onSelect: (unitId: number, profileId?: string) => void;
  onRunningChange: (running: boolean) => void;
  profiles?: SearchProfile[];
  serial?: CommissioningConnectionSerial | null;
};
const defaultProfiles: SearchProfile[] = [
  { id: "dixell-xjp60d", version: "dixell-xjp60d-fc03-v1", displayName: "Dixell XJP60D" },
];
const serialByProfile: Record<string, [number, string, number]> = {
  "dixell-xjp60d": [9600, "N", 1],
  "f-and-f-le01mp": [9600, "N", 1],
  "embraco-sync": [9600, "N", 2],
  "danfoss-ak-cc25-pro": [9600, "E", 1],
};

export function Rs485AddressSearch(props: Props) {
  const identity = JSON.stringify([props.connection, props.profiles, props.serial]);
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
  profiles = defaultProfiles,
  serial,
}: Props) {
  const [running, setRunning] = useState(false);
  const [checked, setChecked] = useState(0);
  const [responders, setResponders] = useState<Record<number, string[]>>({});
  const [failedAddresses, setFailedAddresses] = useState<number[]>([]);
  const [status, setStatus] = useState("Натисніть пошук, щоб перевірити підключені прилади.");
  const request = useRef<AbortController | null>(null);
  const compatible = profiles.filter((profile) => {
    const settings = serialByProfile[profile.id];
    return (
      settings &&
      (!serial ||
        (settings[0] === serial.baudrate && settings[1] === serial.parity && settings[2] === serial.stopbits))
    );
  });
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
    if (disabled || request.current || !repository.searchAddress || !compatible.length) return;
    const controller = new AbortController();
    request.current = controller;
    setRunning(true);
    setChecked(0);
    setResponders({});
    setFailedAddresses([]);
    const failures = new Set<number>();
    setStatus("Шукаємо всі прилади на лінії…");
    try {
      for (let unitId = 1; unitId <= 247; unitId++) {
        for (const profile of compatible) {
          if (controller.signal.aborted) return;
          const read = () =>
            repository.searchAddress!(
              { ...connection, unitId, profileId: profile.id, profileVersion: profile.version },
              controller.signal,
            );
          const recoverable = (code: string | null) =>
            code === "malformed_response" || code === "read_failed";
          let result = await read();
          if (controller.signal.aborted) return;
          if (result.state === "failed" && recoverable(result.errorCode)) result = await read();
          if (controller.signal.aborted) return;
          if (result.state === "failed" && recoverable(result.errorCode)) {
            failures.add(unitId);
            setFailedAddresses([...failures]);
            continue;
          }
          if (result.state !== "completed") throw new Error(result.errorCode ?? "search_failed");
          if (result.candidates.length || result.exceptionAddresses.length) {
            setResponders((current) => {
              const matches = current[unitId] ?? [];
              return {
                ...current,
                [unitId]:
                  result.candidates.length && !matches.includes(profile.id)
                    ? [...matches, profile.id]
                    : matches,
              };
            });
          }
        }
        setChecked(unitId);
      }
      setStatus(
        failures.size
          ? "Пошук завершено з помилками зв’язку. Список може бути неповним."
          : "Пошук завершено. Оберіть прилад зі списку.",
      );
    } catch (cause) {
      if (!controller.signal.aborted)
        setStatus(
          cause instanceof Error && cause.message === "serial_profile_mismatch"
            ? "Налаштування лінії не відповідають обраній моделі. Показані результати часткового пошуку."
            : "Пошук перервано через помилку. Показані результати часткового пошуку; перевірте підключення та повторіть.",
        );
    } finally {
      if (request.current === controller) {
        request.current = null;
        setRunning(false);
        if (controller.signal.aborted) setStatus("Пошук зупинено. Показані результати часткового пошуку.");
      }
    }
  };

  if (!repository.searchAddress) return null;
  return (
    <section aria-label="Пошук приладів RS-485" className="rounded-2xl border border-cyan-300/15 p-4 text-xs">
      <h3 className="text-sm font-semibold text-white">Знайти всі прилади</h3>
      <p className="mt-2 leading-5 text-slate-300">
        Перевіримо адреси 1–247. Пошук може тривати кілька хвилин; результати з’являються одразу. Налаштування
        приладів не змінюються.
      </p>
      {!compatible.length ? (
        <p role="alert" className="mt-2 text-amber-200">
          Обрана модель має інші налаштування зв’язку. Оберіть автовизначення або відповідну модель.
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || running || !compatible.length}
          onClick={() => void start()}
          className="rounded-xl bg-cyan-300 px-4 py-2 font-semibold text-slate-950 disabled:opacity-50"
        >
          Знайти прилади
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
        {status} Перевірено адрес: {checked}/247. Знайдено адрес із приладами:{" "}
        {Object.keys(responders).length}.
      </p>
      <div className="mt-3 space-y-2">
        {failedAddresses.length ? (
          <p role="alert" className="text-amber-200">
            Адреси з помилками зв’язку після повторної перевірки: {failedAddresses.join(", ")}. Перевірте
            підключення та повторіть пошук.
          </p>
        ) : null}
        {Object.entries(responders).map(([address, matches]) => (
          <div key={address} className="rounded-xl border border-emerald-300/20 p-3">
            <p className="font-semibold text-white">Адреса {address}</p>
            {matches.length ? (
              <>
                <p className="mt-1 text-slate-300">
                  Відповідає профілю:{" "}
                  {matches.map((id) => profiles.find((p) => p.id === id)?.displayName ?? id).join(", ")}.
                  Точну модель ще не підтверджено.
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {matches.map((id) => (
                    <button
                      key={id}
                      type="button"
                      disabled={disabled}
                      onClick={() => onSelect(Number(address), id)}
                      className="rounded-lg border border-emerald-300/30 px-3 py-2 disabled:opacity-50"
                      aria-label={`Вибрати адресу ${address}${matches.length > 1 ? ` · ${profiles.find((p) => p.id === id)?.displayName ?? id}` : ""}`}
                    >
                      Обрати
                      {matches.length > 1
                        ? ` · ${profiles.find((p) => p.id === id)?.displayName ?? id}`
                        : " цей прилад"}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <p className="mt-1 text-amber-200">
                Прилад відповідає Modbus, але модель не визначена. Обраний профіль не підтримується.
              </p>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-slate-400">
        Кількість визначається за різними адресами. Прилади з однаковою адресою окремо не розрізняються.
      </p>
    </section>
  );
}
