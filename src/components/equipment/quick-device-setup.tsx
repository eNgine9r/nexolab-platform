"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
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
  profiles: SupportedDeviceProfile[];
  inventory: CommissioningConnectionInventory | null;
  inventoryError: string | null;
  draft: CommissioningSessionWrite;
  onDraft: (draft: CommissioningSessionWrite) => void;
  onInventory: (inventory: CommissioningConnectionInventory) => void;
  onSaved: (session: CommissioningSession) => void;
  onAdvanced: () => void;
  onNew?: () => void;
  canManage: boolean;
};

const fieldClass =
  "mt-2 min-h-11 w-full rounded-xl border border-white/15 bg-[#0b203b] px-3 text-sm text-white";

export function QuickDeviceSetup(props: Props) {
  const { repository, profiles, inventory, draft } = props;
  const [name, setName] = useState<string | null>(null);
  const [searchProfileId, setSearchProfileId] = useState(draft.profileId);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<CommissioningSession | null>(null);
  const [done, setDone] = useState(false);
  const pending = useRef(false);
  const alive = useRef(true);
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
  const instrumentName =
    name ?? draft.displayName ?? (profile && draft.unitId ? `${profile.displayName} · ${draft.unitId}` : "");
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
      !instrumentName.trim()
    )
      return;
    pending.current = true;
    setBusy(true);
    setError(null);
    setStatus("Зберігаємо прилад…");
    try {
      let session =
        saved ??
        (await repository.createSession(
          { ...draft, displayName: instrumentName.trim(), targetEquipmentKey: null },
          keys.current.create,
        ));
      if (!alive.current) return;
      setSaved(session);
      props.onSaved(session);
      if (session.lifecycle !== "verified" && session.lifecycle !== "active") {
        if (!["ready_for_preflight", "activation_failed", "rolled_back"].includes(session.lifecycle))
          throw new Error("Прилад збережено. Перевірте підключення або відкрийте розширені налаштування.");
        setStatus("Перевіряємо зв’язок із приладом…");
        const result = await repository.runPreflight(session.id, session.version, keys.current.preflight);
        session = await repository.getSession(session.id);
        if (!alive.current) return;
        setSaved(session);
        props.onSaved(session);
        if (result.result !== "passed") {
          keys.current.preflight = createCommissioningIdempotencyKey();
          throw new Error(preflightMessage(result.code));
        }
      }
      if (profile.activationSupported && session.lifecycle !== "active") {
        setStatus("Вмикаємо зчитування показників…");
        const activation = await repository.runActivation(session.id, session.version, keys.current.activate);
        if (!alive.current) return;
        session = await repository.getSession(session.id);
        if (!alive.current) return;
        setSaved(session);
        props.onSaved(session);
        if (activation.state !== "active") {
          keys.current.activate = createCommissioningIdempotencyKey();
          keys.current.preflight = createCommissioningIdempotencyKey();
          throw new Error(
            "Прилад збережено й зв’язок перевірено. Зчитування ще не запущене; повторіть перевірку.",
          );
        }
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
              value={searchProfileId ?? ""}
              onChange={(event) => {
                setSearchProfileId(event.target.value || null);
                const item = profiles.find((entry) => entry.id === event.target.value);
                if (item)
                  patch({
                    profileId: item.id,
                    deviceClass: item.deviceClass,
                    manufacturer: item.manufacturer,
                    model: item.models[0] ?? item.displayName,
                    unitId: item.id === "danfoss-ak-cc25-pro" ? 35 : null,
                  });
                else patch({ profileId: null, manufacturer: "", model: "", unitId: null });
              }}
            >
              <option value="">Автовизначення підтримуваних приладів</option>
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
        {!connection ? (
          <p className="text-sm text-slate-400">Спочатку оберіть адаптер.</p>
        ) : connection.availableForReadSearch === true || connection.availableForIsolatedSearch === true ? (
          <Rs485AddressSearch
            repository={repository}
            connection={{
              nodeId: inventory!.nodeId,
              busId: connection.busId,
              stableTransportIdentifier: connection.stableTransportIdentifier,
            }}
            disabled={busy || saved !== null || !props.canManage}
            profiles={searchProfileId ? profiles.filter((item) => item.id === searchProfileId) : profiles}
            serial={connection.serial}
            onSelect={(unitId, profileId) => {
              const found = profiles.find((item) => item.id === profileId);
              patch(
                found
                  ? {
                      unitId,
                      profileId: found.id,
                      manufacturer: found.manufacturer,
                      model: found.models[0] ?? found.displayName,
                      deviceClass: found.deviceClass,
                    }
                  : { unitId },
              );
            }}
            onRunningChange={setSearching}
          />
        ) : (
          <p className="text-sm text-slate-300">
            Для пошуку потрібне доступне підключення. Перевірте адаптер або вкажіть адресу вручну.
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
          <label className="text-sm text-slate-200">
            Назва приладу
            <input
              aria-label="Назва приладу"
              className={fieldClass}
              placeholder="Наприклад, Dixell — тестовий стенд"
              value={instrumentName}
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <p className="mt-2 text-xs text-slate-400">
            Прилад працюватиме самостійно. Вітрину обирати не потрібно.
          </p>
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
              !instrumentName.trim()
            }
            onClick={() => void add()}
            className="min-h-11 rounded-xl bg-cyan-300 px-6 py-3 text-sm font-semibold text-slate-950 disabled:opacity-40"
          >
            {busy ? "Додаємо…" : saved ? "Повторити перевірку" : "Додати прилад"}
          </button>
        ) : (
          <Link
            href="/equipment?section=connections"
            className="rounded-xl bg-cyan-300 px-6 py-3 text-sm font-semibold text-slate-950"
          >
            Відкрити прилади
          </Link>
        )}
        {done ? (
          <button
            type="button"
            className="min-h-11 rounded-xl border border-cyan-300/30 px-4 text-sm text-cyan-200"
            onClick={() => {
              setSaved(null);
              setDone(false);
              setName(null);
              setError(null);
              setStatus("");
              keys.current = {
                create: createCommissioningIdempotencyKey(),
                preflight: createCommissioningIdempotencyKey(),
                activate: createCommissioningIdempotencyKey(),
              };
              props.onNew?.();
              patch({ unitId: null, displayName: null, targetEquipmentKey: null });
            }}
          >
            Додати ще один
          </button>
        ) : null}
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

function preflightMessage(code: string | null): string {
  if (code === "unit_id_conflict")
    return "Прилад збережено. Ця адреса вже зайнята іншим профілем у налаштуваннях зчитування; потрібно оновити старе підключення.";
  if (code === "adapter_unavailable" || code === "bus_unavailable")
    return "Прилад збережено. Адаптер недоступний — підключіть його та повторіть перевірку.";
  return "Прилад збережено, але він не відповідає. Перевірте живлення та підключення й повторіть перевірку.";
}
