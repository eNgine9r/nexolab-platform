"use client";

import { useEffect, useRef, useState } from "react";

import type {
  CommissioningConnection,
  CommissioningConnectionInventory,
  CommissioningRepository,
} from "@/features/equipment/commissioning-repository";

type Comparison =
  | { kind: "found" | "unavailable"; connection: CommissioningConnection }
  | { kind: "none" | "ambiguous" | "changed" };

/** Compare inventories, not USB port numbers or inferred physical wiring. */
export function compareAdapterInventories(
  before: CommissioningConnectionInventory,
  after: CommissioningConnectionInventory,
): Comparison {
  const unique = (items: CommissioningConnection[]) =>
    new Set(items.map((item) => item.stableTransportIdentifier)).size === items.length &&
    new Set(items.map((item) => item.busId)).size === items.length;
  if (before.nodeId !== after.nodeId || !unique(before.connections) || !unique(after.connections)) {
    return { kind: "changed" };
  }
  const presentBefore = before.connections.filter((item) => item.present);
  const presentAfter = after.connections.filter((item) => item.present);
  const afterByPath = new Map(presentAfter.map((item) => [item.stableTransportIdentifier, item]));
  if (
    presentBefore.some((item) => {
      const current = afterByPath.get(item.stableTransportIdentifier);
      return !current || current.busId !== item.busId || current.ownership !== item.ownership;
    })
  ) {
    return { kind: "changed" };
  }
  const previousPaths = new Set(presentBefore.map((item) => item.stableTransportIdentifier));
  const added = presentAfter.filter((item) => !previousPaths.has(item.stableTransportIdentifier));
  if (added.length === 0) return { kind: "none" };
  if (added.length !== 1) return { kind: "ambiguous" };
  const connection = added[0];
  if (connection.ownership !== "available_commissioning" || !connection.availableForPreflight) {
    return { kind: "unavailable", connection };
  }
  return { kind: "found", connection };
}

type FinderProps = {
  repository: CommissioningRepository;
  disabled: boolean;
  onInventoryChanged: (inventory: CommissioningConnectionInventory) => void;
  onSelect: (busId: string) => void;
};

export function Rs485AdapterFinder(props: FinderProps) {
  const [context, setContext] = useState({ repository: props.repository, generation: 0 });
  if (context.repository !== props.repository) {
    setContext({ repository: props.repository, generation: context.generation + 1 });
    return null;
  }
  return <AdapterFinder key={context.generation} {...props} />;
}

function AdapterFinder({ repository, disabled, onInventoryChanged, onSelect }: FinderProps) {
  const [baseline, setBaseline] = useState<CommissioningConnectionInventory | null>(null);
  const [result, setResult] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const currentRepository = useRef(repository);

  useEffect(() => {
    currentRepository.current = repository;
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [repository]);

  const fetchSnapshot = async (initial: boolean) => {
    if (busy || disabled) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const operationRepository = repository;
    setBusy(true);
    setError(null);
    setResult(null);
    if (initial) setBaseline(null);
    try {
      const inventory = await operationRepository.listConnections(controller.signal);
      if (controller.signal.aborted || currentRepository.current !== operationRepository) return;
      onInventoryChanged(inventory);
      if (initial) {
        setBaseline(inventory);
      } else if (baseline) {
        setResult(compareAdapterInventories(baseline, inventory));
        setBaseline(null);
      }
    } catch {
      if (controller.signal.aborted || currentRepository.current !== operationRepository) return;
      setBaseline(null);
      setError("Не вдалося отримати список адаптерів. Перевірте зв’язок із системою та почніть знову.");
    } finally {
      if (!controller.signal.aborted && currentRepository.current === operationRepository) setBusy(false);
    }
  };

  const messages: Record<"none" | "ambiguous" | "changed", string> = {
    none: "Новий адаптер не знайдено. Перевірте USB-підключення та повторіть пошук.",
    ambiguous: "Знайдено кілька нових адаптерів. Почніть знову та підключіть лише один вільний адаптер.",
    changed: "Список адаптерів змінився неоднозначно. Перевірте підключення та почніть знову.",
  };
  return (
    <section
      aria-label="Визначення нового RS-485 адаптера"
      className="rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.04] p-4"
    >
      <h3 className="text-sm font-semibold text-white">Не знаєте, який адаптер вибрати?</h3>
      <p className="mt-2 text-xs leading-5 text-slate-300">
        Порівняємо список USB до і після підключення. Не від’єднуйте адаптери, які вже працюють у моніторингу.
      </p>
      {baseline ? (
        <p role="status" className="mt-3 text-xs text-cyan-100">
          Підключіть один вільний USB–RS-485 адаптер до Raspberry Pi, потім натисніть кнопку нижче.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-xs text-rose-200">
          {error}
        </p>
      ) : null}
      {result && (result.kind === "none" || result.kind === "ambiguous" || result.kind === "changed") ? (
        <p role="status" className="mt-3 text-xs text-amber-100">
          {messages[result.kind]}
        </p>
      ) : null}
      {result?.kind === "unavailable" ? (
        <div role="status" className="mt-3 text-xs text-amber-100">
          <p>Виявлено USB-адаптер: {result.connection.stableTransportIdentifier.split("/").at(-1)}</p>
          <p className="mt-1">
            Він недоступний для перевірки або належить робочій шині. Можлива причина — відсутній робочий
            адаптер чи немає доступу до порту. Підключення приладу не перевірено.
          </p>
        </div>
      ) : null}
      {result?.kind === "found" ? (
        <div role="status" className="mt-3 text-xs text-emerald-100">
          <p>
            Знайдено новий адаптер, доступний для перевірки:{" "}
            {result.connection.stableTransportIdentifier.split("/").at(-1)}
          </p>
          <p className="mt-1 text-slate-300">Це підтверджує USB-підключення, але не зв’язок із приладом.</p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onSelect(result.connection.busId)}
            className="mt-3 rounded-xl bg-cyan-300 px-4 py-2 font-semibold text-slate-950 disabled:opacity-50"
          >
            Вибрати цей адаптер
          </button>
        </div>
      ) : null}
      <button
        type="button"
        disabled={disabled || busy}
        onClick={() => void fetchSnapshot(!baseline)}
        className="mt-3 rounded-xl border border-white/20 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
      >
        {busy
          ? "Перевіряємо…"
          : baseline
            ? "Я підключив адаптер"
            : result
              ? "Почати знову"
              : "Знайти новий адаптер"}
      </button>
    </section>
  );
}
