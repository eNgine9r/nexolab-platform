"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { RefrigerationEquipment } from "@/data/refrigeration";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import {
  createCommissioningIdempotencyKey,
  type CommissioningConnectionInventory,
  type CommissioningRepository,
  type CommissioningSession,
  type CommissioningSessionWrite,
  type SupportedDeviceProfile,
} from "@/features/equipment/commissioning-repository";
import { Rs485AdapterFinder } from "./rs485-adapter-finder";
import { Rs485AddressSearch } from "./rs485-address-search";

type Props = {
  repository: CommissioningRepository;
  equipmentRepository: RefrigerationEquipmentRepository;
  profiles: SupportedDeviceProfile[];
  inventory: CommissioningConnectionInventory | null;
  inventoryError: string | null;
  equipment: RefrigerationEquipment[];
  draft: CommissioningSessionWrite;
  onDraft: (draft: CommissioningSessionWrite) => void;
  onInventory: (inventory: CommissioningConnectionInventory) => void;
  onSaved: (session: CommissioningSession) => void;
  onAdvanced: () => void;
  canManage: boolean;
};

const fieldClass =
  "mt-2 min-h-11 w-full rounded-xl border border-white/15 bg-[#0b203b] px-3 text-sm text-white";

export function QuickDeviceSetup(props: Props) {
  const { repository, equipmentRepository, profiles, inventory, equipment, draft } = props;
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<CommissioningSession | null>(null);
  const [done, setDone] = useState(false);
  const pending = useRef(false);
  const alive = useRef(true);
  const createdEquipment = useRef<string | null>(null);
  const keys = useRef({
    create: createCommissioningIdempotencyKey(),
    preflight: createCommissioningIdempotencyKey(),
    activate: createCommissioningIdempotencyKey(),
  });
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const profile = profiles.find((item) => item.id === draft.profileId);
  const connection = inventory?.connections.find((item) => item.busId === draft.busId);
  const locked = busy || searching || !props.canManage;
  const patch = (values: Partial<CommissioningSessionWrite>) => props.onDraft({ ...draft, ...values });
  const chooseConnection = (busId: string, source = inventory) => {
    const item = source?.connections.find((entry) => entry.busId === busId && entry.present);
    patch({
      busId: item?.busId ?? null,
      nodeId: item ? source!.nodeId : null,
      stableTransportIdentifier: item?.stableTransportIdentifier ?? null,
      unitId: null,
    });
  };

  const add = async () => {
    if (
      pending.current ||
      !props.canManage ||
      !profile ||
      !connection?.present ||
      !draft.unitId ||
      !Number.isInteger(draft.unitId) ||
      (!draft.targetEquipmentKey && !name.trim())
    )
      return;
    pending.current = true;
    setBusy(true);
    setError(null);
    setStatus("Зберігаємо прилад…");
    try {
      let target = draft.targetEquipmentKey ?? createdEquipment.current;
      if (!target) {
        const item = await equipmentRepository.create({
          code: `DEVICE-${keys.current.create.slice(-12)}`,
          name: name.trim(),
          location: "Не вказано",
          laboratory: "",
          zone: "",
          nodeId: "",
          type: "Контролер",
          manufacturer: profile.manufacturer,
          model: profile.models[0] ?? profile.displayName,
          serialNumber: "Не вказано",
          temperatureClass: "Не вказано",
          installedAt: "",
          servicedAt: "",
          lifecycleStatus: "active",
          totalSensors: profile.id === "dixell-xjp60d" ? 14 : 1,
        });
        if (!alive.current) return;
        target = item.id;
        createdEquipment.current = target;
      }
      let session =
        saved ??
        (await repository.createSession({ ...draft, targetEquipmentKey: target }, keys.current.create));
      if (!alive.current) return;
      setSaved(session);
      props.onSaved(session);
      if (session.lifecycle !== "verified" && session.lifecycle !== "active") {
        if (session.lifecycle !== "ready_for_preflight")
          throw new Error("Прилад збережено. Перевірте підключення або відкрийте розширені налаштування.");
        setStatus("Перевіряємо зв’язок із приладом…");
        const result = await repository.runPreflight(session.id, session.version, keys.current.preflight);
        session = await repository.getSession(session.id);
        if (!alive.current) return;
        setSaved(session);
        props.onSaved(session);
        if (result.result !== "passed") {
          keys.current.preflight = createCommissioningIdempotencyKey();
          throw new Error(
            "Прилад збережено, але він не відповідає. Перевірте живлення та підключення й повторіть перевірку.",
          );
        }
      }
      if (profile.activationSupported && session.lifecycle !== "active") {
        setStatus("Вмикаємо зчитування показників…");
        const activation = await repository.runActivation(session.id, session.version, keys.current.activate);
        if (!alive.current) return;
        if (activation.state !== "active")
          throw new Error("Зв’язок перевірено. Увімкнути моніторинг не вдалося — подробиці в налаштуваннях.");
        session = await repository.getSession(session.id);
        if (!alive.current) return;
        setSaved(session);
        props.onSaved(session);
      }
      setDone(true);
      setStatus(
        session.lifecycle === "active"
          ? "Прилад додано. Моніторинг увімкнено."
          : "Прилад додано до реєстру. Зв’язок перевірено; для цієї моделі моніторинг ще недоступний.",
      );
    } catch (cause) {
      if (alive.current) {
        setStatus("");
        setError(cause instanceof Error ? cause.message : "Не вдалося додати прилад. Спробуйте ще раз.");
      }
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return (
    <section aria-label="Швидке додавання приладу" className="mx-auto max-w-4xl space-y-4">
      <div className="rounded-2xl border border-white/10 bg-[#08182e] p-5">
        <h2 className="text-xl font-semibold text-white">Додати прилад</h2>
        <p className="mt-2 text-sm text-slate-300">
          Оберіть підключення, знайдіть прилад і дайте йому зрозумілу назву.
        </p>
      </div>
      <fieldset disabled={locked || saved !== null} className="grid min-w-0 gap-4 md:grid-cols-2">
        <Card title="1. Який прилад підключаємо?">
          <label className="text-sm text-slate-200">
            Модель приладу
            <select
              aria-label="Модель приладу"
              className={fieldClass}
              value={draft.profileId ?? ""}
              onChange={(event) => {
                const item = profiles.find((entry) => entry.id === event.target.value);
                if (item)
                  patch({
                    profileId: item.id,
                    deviceClass: item.deviceClass,
                    manufacturer: item.manufacturer,
                    model: item.models[0] ?? item.displayName,
                    unitId: item.id === "danfoss-ak-cc25-pro" ? 35 : null,
                  });
              }}
            >
              <option value="">Оберіть модель</option>
              {profiles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayName}
                </option>
              ))}
            </select>
          </label>
        </Card>
        <Card title="2. Через який адаптер?">
          <label className="text-sm text-slate-200">
            USB–RS485
            <select
              aria-label="USB–RS485"
              className={fieldClass}
              value={draft.busId ?? ""}
              onChange={(event) => chooseConnection(event.target.value)}
            >
              <option value="">Оберіть підключення</option>
              {inventory?.connections
                .filter((item) => item.present)
                .map((item, index) => (
                  <option key={item.busId} value={item.busId}>
                    Адаптер {index + 1} · {adapterSerial(item.stableTransportIdentifier)}
                  </option>
                ))}
            </select>
          </label>
          {props.inventoryError ? (
            <p role="alert" className="mt-2 text-sm text-amber-200">
              Не вдалося отримати список адаптерів. {props.inventoryError}
            </p>
          ) : null}
        </Card>
      </fieldset>
      {!saved ? (
        <details className="rounded-2xl border border-white/10 p-4 text-sm text-slate-300">
          <summary className="cursor-pointer">Не знаю, який із адаптерів мій</summary>
          <div className="mt-3">
            <Rs485AdapterFinder
              repository={repository}
              disabled={locked}
              onInventoryChanged={props.onInventory}
              onSelect={chooseConnection}
            />
          </div>
        </details>
      ) : null}
      <Card title="3. Знайти прилад">
        {!profile || !connection ? (
          <p className="text-sm text-slate-400">Спочатку оберіть модель та адаптер.</p>
        ) : profile.id === "dixell-xjp60d" &&
          connection.ownership === "available_commissioning" &&
          connection.availableForIsolatedSearch === true &&
          !saved ? (
          <Rs485AddressSearch
            repository={repository}
            connection={{
              nodeId: inventory!.nodeId,
              busId: connection.busId,
              stableTransportIdentifier: connection.stableTransportIdentifier,
            }}
            disabled={busy || !props.canManage}
            onSelect={(unitId) => patch({ unitId })}
            onRunningChange={setSearching}
            selectFirstMatch
          />
        ) : (
          <p className="text-sm text-slate-300">
            Вкажіть адресу приладу нижче. Автоматичний пошук для цього підключення недоступний.
          </p>
        )}
        {draft.unitId ? <p className="mt-3 text-sm text-emerald-200">Обрано адресу {draft.unitId}</p> : null}
        <details className="mt-3 text-sm text-slate-300">
          <summary className="cursor-pointer">Знаю адресу — ввести вручну</summary>
          <label className="mt-2 block">
            Адреса приладу
            <input
              aria-label="Адреса приладу"
              type="number"
              min={1}
              max={247}
              className={fieldClass}
              disabled={locked || saved !== null}
              value={draft.unitId ?? ""}
              onChange={(event) => patch({ unitId: event.target.value ? Number(event.target.value) : null })}
            />
          </label>
        </details>
      </Card>
      <Card title="4. Назва в моніторингу">
        <fieldset disabled={locked || saved !== null}>
          {!draft.targetEquipmentKey ? (
            <label className="text-sm text-slate-200">
              Назва приладу
              <input
                aria-label="Назва приладу"
                className={fieldClass}
                placeholder="Наприклад, Dixell — тестовий стенд"
                value={name}
                maxLength={255}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
          ) : (
            <p className="text-sm text-slate-200">
              {equipment.find((item) => item.id === draft.targetEquipmentKey)?.name ?? "Обране обладнання"}
            </p>
          )}
          <details className="mt-3 text-sm text-slate-300">
            <summary className="cursor-pointer">Прив’язати до наявного обладнання</summary>
            <select
              aria-label="Наявне обладнання"
              className={fieldClass}
              value={draft.targetEquipmentKey ?? ""}
              onChange={(event) => patch({ targetEquipmentKey: event.target.value || null })}
            >
              <option value="">Створити новий прилад</option>
              {equipment.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </details>
        </fieldset>
      </Card>
      {error ? (
        <p role="alert" className="rounded-xl bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </p>
      ) : null}
      {status ? (
        <p role="status" className="rounded-xl bg-cyan-400/10 p-4 text-sm text-cyan-100">
          {status}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3 pb-4">
        {!done ? (
          <button
            type="button"
            disabled={
              locked ||
              !profile ||
              !connection?.present ||
              !draft.unitId ||
              !Number.isInteger(draft.unitId) ||
              draft.unitId < 1 ||
              draft.unitId > 247 ||
              (!draft.targetEquipmentKey && !name.trim())
            }
            onClick={() => void add()}
            className="min-h-11 rounded-xl bg-cyan-300 px-6 py-3 text-sm font-semibold text-slate-950 disabled:opacity-40"
          >
            {busy ? "Додаємо…" : saved ? "Повторити перевірку" : "Додати прилад"}
          </button>
        ) : (
          <Link
            href="/equipment"
            className="rounded-xl bg-cyan-300 px-6 py-3 text-sm font-semibold text-slate-950"
          >
            Відкрити прилади
          </Link>
        )}
        <button
          type="button"
          disabled={busy || searching}
          onClick={props.onAdvanced}
          className="min-h-11 px-3 text-sm text-slate-400 underline"
        >
          Розширені налаштування
        </button>
      </div>
    </section>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-2xl border border-white/10 bg-[#08182e] p-5">
      <h3 className="mb-3 text-sm font-semibold text-white">{title}</h3>
      {children}
    </div>
  );
}

function adapterSerial(path: string) {
  return (
    path
      .split("/")
      .at(-1)
      ?.replace(/^usb-/, "")
      .replace(/-if\d+-port\d+$/, "")
      .replaceAll("_", " ") ?? path
  );
}
