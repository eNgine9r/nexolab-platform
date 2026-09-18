"use client";

import { AlertTriangle, CheckCircle2, Gauge, Plus, RefreshCw, Save } from "lucide-react";
import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import {
  InstrumentationRegistryRepositoryError,
  type InstrumentAcceptanceRecord,
  type InstrumentationRegistryRepository,
  type InstrumentRegistryRecord,
  type InstrumentWriteInput,
  type PressureReference,
  type RegistryLifecycleState,
  type SignalRegistryRecord,
  type SignalWriteInput,
} from "@/features/instrumentation/instrumentation-repository";

type InstrumentDetails = {
  signals: SignalRegistryRecord[];
  acceptance: InstrumentAcceptanceRecord[];
};

type InstrumentDraft = {
  inventoryKey: string;
  displayName: string;
  instrumentKind: string;
  manufacturer: string;
  model: string;
  serialNumber: string;
  pressureReference: PressureReference | "";
  lifecycleState: RegistryLifecycleState;
};

type SignalDraft = {
  businessKey: string;
  displayName: string;
  physicalQuantity: string;
  engineeringUnit: string;
  lifecycleState: RegistryLifecycleState;
};

const emptyInstrumentDraft: InstrumentDraft = {
  inventoryKey: "",
  displayName: "",
  instrumentKind: "",
  manufacturer: "",
  model: "",
  serialNumber: "",
  pressureReference: "",
  lifecycleState: "active",
};

const emptySignalDraft: SignalDraft = {
  businessKey: "",
  displayName: "",
  physicalQuantity: "",
  engineeringUnit: "",
  lifecycleState: "active",
};

export function InstrumentationRegistryWorkspace({
  repository,
  canManage,
}: {
  repository: InstrumentationRegistryRepository | null;
  canManage: boolean;
}) {
  const [instruments, setInstruments] = useState<InstrumentRegistryRecord[]>([]);
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<string | null>(null);
  const [details, setDetails] = useState<InstrumentDetails | null>(null);
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [loading, setLoading] = useState(repository !== null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [createInstrumentOpen, setCreateInstrumentOpen] = useState(false);
  const [instrumentDraft, setInstrumentDraft] = useState<InstrumentDraft>(emptyInstrumentDraft);
  const [signalDraft, setSignalDraft] = useState<SignalDraft>(emptySignalDraft);
  const [acceptanceValue, setAcceptanceValue] = useState<"accepted" | "rejected">("accepted");
  const [acceptanceLabel, setAcceptanceLabel] = useState("");
  const [acceptanceAt, setAcceptanceAt] = useState(() => localDateTimeValue(new Date()));

  const loadBase = useCallback(
    async (preferredInstrumentId?: string) => {
      if (!repository) return;
      setLoading(true);
      setError(null);
      try {
        const next = await repository.listInstruments();
        setInstruments(next);
        const preferred =
          preferredInstrumentId && next.some((item) => item.id === preferredInstrumentId)
            ? preferredInstrumentId
            : selectedInstrumentId && next.some((item) => item.id === selectedInstrumentId)
              ? selectedInstrumentId
              : (next[0]?.id ?? null);
        setSelectedInstrumentId(preferred);
        if (next.length === 0) {
          setDetails(null);
          setSelectedSignalId(null);
        }
      } catch (cause) {
        setError(readError(cause, "Не вдалося завантажити Instrumentation Registry."));
      } finally {
        setLoading(false);
      }
    },
    [repository, selectedInstrumentId],
  );

  const loadDetails = useCallback(
    async (instrumentId: string) => {
      if (!repository) return;
      setDetailsLoading(true);
      setError(null);
      try {
        const [signals, acceptance] = await Promise.all([
          repository.listSignals(instrumentId),
          repository.listAcceptanceHistory(instrumentId),
        ]);
        setDetails({ signals, acceptance });
        setSelectedSignalId((current) =>
          current && signals.some((item) => item.id === current) ? current : (signals[0]?.id ?? null),
        );
      } catch (cause) {
        setDetails(null);
        setSelectedSignalId(null);
        setError(readError(cause, "Не вдалося завантажити Signals та acceptance history."));
      } finally {
        setDetailsLoading(false);
      }
    },
    [repository],
  );

  useEffect(() => {
    if (!repository) return;
    let active = true;
    const controller = new AbortController();

    void repository
      .listInstruments(controller.signal)
      .then((next) => {
        if (!active) return;
        setInstruments(next);
        setSelectedInstrumentId((current) =>
          current && next.some((item) => item.id === current) ? current : (next[0]?.id ?? null),
        );
        if (next.length === 0) {
          setDetails(null);
          setSelectedSignalId(null);
        }
      })
      .catch((cause) => {
        if (!active || controller.signal.aborted) return;
        setError(readError(cause, "Не вдалося завантажити Instrumentation Registry."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [repository]);

  useEffect(() => {
    if (!repository || !selectedInstrumentId) return;
    let active = true;
    const controller = new AbortController();

    setDetailsLoading(true);
    void Promise.all([
      repository.listSignals(selectedInstrumentId, controller.signal),
      repository.listAcceptanceHistory(selectedInstrumentId, controller.signal),
    ])
      .then(([signals, acceptance]) => {
        if (!active) return;
        setDetails({ signals, acceptance });
        setSelectedSignalId((current) =>
          current && signals.some((item) => item.id === current) ? current : (signals[0]?.id ?? null),
        );
      })
      .catch((cause) => {
        if (!active || controller.signal.aborted) return;
        setDetails(null);
        setSelectedSignalId(null);
        setError(readError(cause, "Не вдалося завантажити Signals та acceptance history."));
      })
      .finally(() => {
        if (active) setDetailsLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [repository, selectedInstrumentId]);

  const selectedInstrument = useMemo(
    () => instruments.find((item) => item.id === selectedInstrumentId) ?? null,
    [instruments, selectedInstrumentId],
  );
  const selectedSignal = useMemo(
    () => details?.signals.find((item) => item.id === selectedSignalId) ?? null,
    [details?.signals, selectedSignalId],
  );
  const filteredInstruments = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("uk-UA");
    if (!normalized) return instruments;
    return instruments.filter((item) =>
      [
        item.inventoryKey,
        item.displayName,
        item.instrumentKind,
        item.manufacturer ?? "",
        item.model ?? "",
        item.serialNumber ?? "",
      ]
        .join(" ")
        .toLocaleLowerCase("uk-UA")
        .includes(normalized),
    );
  }, [instruments, query]);

  if (!repository) {
    return (
      <PanelMessage
        title="Instrumentation Registry недоступний"
        text="Live API реєстру не підключено. Demo-значення не використовуються як canonical state."
      />
    );
  }

  async function mutate(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (cause) {
      setError(readError(cause, "Операцію Instrumentation Registry відхилено."));
    } finally {
      setBusy(false);
    }
  }

  async function createInstrument(event: FormEvent) {
    event.preventDefault();
    if (!canManage || !validInstrumentDraft(instrumentDraft)) return;
    await mutate(async () => {
      const created = await repository!.createInstrument(toInstrumentInput(instrumentDraft));
      setInstrumentDraft(emptyInstrumentDraft);
      setCreateInstrumentOpen(false);
      setNotice(`Прилад ${created.displayName} створено. Calculation acceptance ще не надано.`);
      await loadBase(created.id);
    });
  }

  async function saveInstrument(record: InstrumentRegistryRecord, input: InstrumentWriteInput) {
    if (!canManage) return;
    await mutate(async () => {
      const updated = await repository!.updateInstrument(record.id, input, record.version);
      setNotice(`Прилад ${updated.displayName} оновлено до v${updated.version}.`);
      await loadBase(updated.id);
    });
  }

  async function createSignal(event: FormEvent) {
    event.preventDefault();
    if (!canManage || !selectedInstrument || !validSignalDraft(signalDraft)) return;
    await mutate(async () => {
      const created = await repository!.createSignal(selectedInstrument.id, toSignalInput(signalDraft));
      setSignalDraft(emptySignalDraft);
      setSelectedSignalId(created.id);
      setNotice(`Signal ${created.displayName} створено.`);
      await loadDetails(selectedInstrument.id);
    });
  }

  async function saveSignal(record: SignalRegistryRecord, input: SignalWriteInput) {
    if (!canManage || !selectedInstrument) return;
    await mutate(async () => {
      const updated = await repository!.updateSignal(
        selectedInstrument.id,
        record.id,
        input,
        record.version,
      );
      setSelectedSignalId(updated.id);
      setNotice(`Signal ${updated.displayName} оновлено до v${updated.version}.`);
      await loadDetails(selectedInstrument.id);
    });
  }

  async function appendAcceptance(event: FormEvent) {
    event.preventDefault();
    if (!canManage || !selectedInstrument) return;
    await mutate(async () => {
      const appended = await repository!.appendAcceptance(selectedInstrument.id, {
        acceptedForCalculation: acceptanceValue === "accepted",
        effectiveFrom: parseLocalDateTime(acceptanceAt),
        stateLabel: acceptanceLabel.trim() || null,
      });
      setAcceptanceLabel("");
      setNotice(
        appended.acceptedForCalculation
          ? "Instrument accepted for calculation. Це не є hardware verification або calibration."
          : "Calculation acceptance відкликано з указаного effective time.",
      );
      await loadDetails(selectedInstrument.id);
    });
  }

  return (
    <div className="space-y-4" data-testid="instrumentation-registry-workspace">
      <section className="rounded-3xl border border-cyan-300/10 bg-[#091a31]/90 p-5 shadow-2xl shadow-black/20 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex items-start gap-3">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
              <Gauge className="h-6 w-6 text-cyan-200" />
            </div>
            <div>
              <p className="text-xs tracking-[0.22em] text-cyan-300 uppercase">
                Canonical Instrumentation Registry
              </p>
              <h1 className="mt-1 text-2xl font-semibold text-white">Прилади та сигнали</h1>
              <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">
                Організаційний реєстр Instrument → Signal. Semantic refrigeration role визначається окремо
                backend authority під час binding; назва каналу або контролера не використовується як семантика.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void loadBase(selectedInstrumentId ?? undefined)}
            disabled={loading || busy}
            className={secondaryButtonClass}
          >
            <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Оновити
          </button>
        </div>

        {!canManage ? (
          <div className="mt-4 rounded-xl border border-slate-400/15 bg-slate-400/[0.05] p-3 text-xs text-slate-300">
            Режим перегляду. Створення та зміни потребують <code>equipment.manage</code>.
          </div>
        ) : null}
        {error ? <Notice tone="error" text={error} /> : null}
        {notice ? <Notice tone="success" text={notice} /> : null}
      </section>

      <section className="grid gap-4 2xl:grid-cols-[minmax(340px,0.75fr)_minmax(0,1.25fr)]">
        <div className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[10px] tracking-[0.16em] text-slate-500 uppercase">Instruments</p>
              <h2 className="mt-1 text-lg font-semibold text-white">Реєстр приладів</h2>
            </div>
            {canManage ? (
              <button
                type="button"
                onClick={() => setCreateInstrumentOpen((value) => !value)}
                className={primaryButtonClass}
              >
                <Plus className="h-3.5 w-3.5" /> Новий прилад
              </button>
            ) : null}
          </div>
          <input
            aria-label="Пошук приладів"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Пошук за назвою, inventory key, model…"
            className="mt-3 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-300/40"
          />
          {createInstrumentOpen && canManage ? (
            <InstrumentCreateForm
              draft={instrumentDraft}
              setDraft={setInstrumentDraft}
              busy={busy}
              onSubmit={createInstrument}
            />
          ) : null}
          <div className="mt-3 grid gap-2">
            {!loading && filteredInstruments.length === 0 ? (
              <p className="rounded-xl border border-white/[0.06] p-4 text-sm text-slate-500">
                Canonical Instruments не знайдено.
              </p>
            ) : null}
            {filteredInstruments.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={item.id === selectedInstrumentId}
                onClick={() => {
                  setSelectedInstrumentId(item.id);
                  setError(null);
                  setNotice(null);
                }}
                className={
                  item.id === selectedInstrumentId
                    ? "rounded-2xl border border-cyan-300/25 bg-cyan-400/[0.08] p-3 text-left"
                    : "rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 text-left hover:border-white/15"
                }
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-white">{item.displayName}</p>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {item.inventoryKey} · {item.instrumentKind}
                    </p>
                  </div>
                  <StatusChip text={lifecycleLabel(item.lifecycleState)} />
                </div>
                <p className="mt-2 text-[10px] text-slate-600">
                  v{item.version}
                  {item.pressureReference ? ` · ${item.pressureReference}` : ""}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          {!selectedInstrument ? (
            <PanelMessage
              title={loading ? "Завантаження…" : "Виберіть Instrument"}
              text="Signal та calculation acceptance показуються для вибраного canonical Instrument."
            />
          ) : (
            <>
              <InstrumentEditor
                key={`${selectedInstrument.id}-v${selectedInstrument.version}`}
                instrument={selectedInstrument}
                canManage={canManage}
                busy={busy}
                onSave={saveInstrument}
              />

              <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] tracking-[0.16em] text-slate-500 uppercase">Signals</p>
                    <h2 className="mt-1 text-lg font-semibold text-white">
                      Signals · {selectedInstrument.displayName}
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      Physical quantity залишається process-neutral; refrigeration role не вводиться тут.
                    </p>
                  </div>
                  {detailsLoading ? <span className="text-xs text-slate-500">Оновлення…</span> : null}
                </div>

                {canManage ? (
                  <SignalCreateForm
                    draft={signalDraft}
                    setDraft={setSignalDraft}
                    busy={busy}
                    onSubmit={createSignal}
                  />
                ) : null}

                <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,0.65fr)_minmax(0,1.35fr)]">
                  <div className="grid content-start gap-2">
                    {(details?.signals ?? []).length === 0 ? (
                      <p className="rounded-xl border border-white/[0.06] p-3 text-xs text-slate-500">
                        Signals для цього Instrument відсутні.
                      </p>
                    ) : null}
                    {(details?.signals ?? []).map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        aria-pressed={item.id === selectedSignalId}
                        onClick={() => setSelectedSignalId(item.id)}
                        className={
                          item.id === selectedSignalId
                            ? "rounded-xl border border-cyan-300/25 bg-cyan-400/[0.07] p-3 text-left"
                            : "rounded-xl border border-white/[0.06] p-3 text-left"
                        }
                      >
                        <p className="text-xs font-medium text-white">{item.displayName}</p>
                        <p className="mt-1 text-[10px] text-slate-500">
                          {item.physicalQuantity} · {item.engineeringUnit} · v{item.version}
                        </p>
                      </button>
                    ))}
                  </div>
                  {selectedSignal ? (
                    <SignalEditor
                      key={`${selectedSignal.id}-v${selectedSignal.version}`}
                      signal={selectedSignal}
                      canManage={canManage}
                      busy={busy}
                      onSave={saveSignal}
                    />
                  ) : (
                    <div className="grid min-h-36 place-items-center rounded-xl border border-white/[0.06] text-xs text-slate-500">
                      Виберіть Signal.
                    </div>
                  )}
                </div>
              </section>

              <AcceptanceSection
                history={details?.acceptance ?? []}
                canManage={canManage}
                busy={busy}
                value={acceptanceValue}
                setValue={setAcceptanceValue}
                label={acceptanceLabel}
                setLabel={setAcceptanceLabel}
                effectiveAt={acceptanceAt}
                setEffectiveAt={setAcceptanceAt}
                onSubmit={appendAcceptance}
              />
            </>
          )}
        </div>
      </section>
    </div>
  );
}

function InstrumentCreateForm({
  draft,
  setDraft,
  busy,
  onSubmit,
}: {
  draft: InstrumentDraft;
  setDraft: (value: InstrumentDraft) => void;
  busy: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="mt-4 rounded-2xl border border-cyan-300/12 bg-cyan-400/[0.03] p-3">
      <p className="text-xs font-medium text-white">Новий canonical Instrument</p>
      <InstrumentFields draft={draft} setDraft={setDraft} prefix="create" />
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-[10px] text-amber-200">
          Після створення Instrument не буде auto-accepted for calculation.
        </p>
        <button type="submit" disabled={busy || !validInstrumentDraft(draft)} className={primaryButtonClass}>
          Створити
        </button>
      </div>
    </form>
  );
}

function InstrumentEditor({
  instrument,
  canManage,
  busy,
  onSave,
}: {
  instrument: InstrumentRegistryRecord;
  canManage: boolean;
  busy: boolean;
  onSave: (record: InstrumentRegistryRecord, input: InstrumentWriteInput) => Promise<void>;
}) {
  const [draft, setDraft] = useState<InstrumentDraft>(() => instrumentDraftFrom(instrument));

  return (
    <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">Instrument identity</p>
          <h2 className="mt-1 text-xl font-semibold text-white">{instrument.displayName}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {instrument.id} · canonical version {instrument.version}
          </p>
        </div>
        <StatusChip text={lifecycleLabel(instrument.lifecycleState)} />
      </div>

      {canManage ? (
        <form
          className="mt-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (validInstrumentDraft(draft)) void onSave(instrument, toInstrumentInput(draft));
          }}
        >
          <InstrumentFields draft={draft} setDraft={setDraft} prefix="edit" />
          <div className="mt-3 flex justify-end">
            <button type="submit" disabled={busy || !validInstrumentDraft(draft)} className={primaryButtonClass}>
              <Save className="h-3.5 w-3.5" /> Зберегти Instrument
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          <Fact label="Inventory key" value={instrument.inventoryKey} />
          <Fact label="Kind" value={instrument.instrumentKind} />
          <Fact label="Pressure reference" value={instrument.pressureReference ?? "Не задано"} />
          <Fact label="Manufacturer" value={instrument.manufacturer ?? "—"} />
          <Fact label="Model" value={instrument.model ?? "—"} />
          <Fact label="Serial" value={instrument.serialNumber ?? "—"} />
        </div>
      )}
    </section>
  );
}

function InstrumentFields({
  draft,
  setDraft,
  prefix,
}: {
  draft: InstrumentDraft;
  setDraft: (value: InstrumentDraft) => void;
  prefix: "create" | "edit";
}) {
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <Field label="Inventory key">
        <input
          aria-label={`${prefix} instrument inventory key`}
          value={draft.inventoryKey}
          onChange={(event) => setDraft({ ...draft, inventoryKey: event.target.value })}
          className={inputClass}
          required
        />
      </Field>
      <Field label="Display name">
        <input
          aria-label={`${prefix} instrument display name`}
          value={draft.displayName}
          onChange={(event) => setDraft({ ...draft, displayName: event.target.value })}
          className={inputClass}
          required
        />
      </Field>
      <Field label="Instrument kind">
        <input
          aria-label={`${prefix} instrument kind`}
          value={draft.instrumentKind}
          onChange={(event) => setDraft({ ...draft, instrumentKind: event.target.value })}
          placeholder="pressure_transmitter"
          className={inputClass}
          required
        />
      </Field>
      <Field label="Manufacturer">
        <input
          value={draft.manufacturer}
          onChange={(event) => setDraft({ ...draft, manufacturer: event.target.value })}
          className={inputClass}
        />
      </Field>
      <Field label="Model">
        <input
          value={draft.model}
          onChange={(event) => setDraft({ ...draft, model: event.target.value })}
          className={inputClass}
        />
      </Field>
      <Field label="Serial number">
        <input
          value={draft.serialNumber}
          onChange={(event) => setDraft({ ...draft, serialNumber: event.target.value })}
          className={inputClass}
        />
      </Field>
      <Field label="Pressure reference">
        <select
          aria-label={`${prefix} instrument pressure reference`}
          value={draft.pressureReference}
          onChange={(event) =>
            setDraft({ ...draft, pressureReference: event.target.value as PressureReference | "" })
          }
          className={inputClass}
        >
          <option value="">Не задано</option>
          <option value="gauge">gauge</option>
          <option value="absolute">absolute</option>
        </select>
      </Field>
      <Field label="Lifecycle">
        <select
          value={draft.lifecycleState}
          onChange={(event) =>
            setDraft({ ...draft, lifecycleState: event.target.value as RegistryLifecycleState })
          }
          className={inputClass}
        >
          <option value="active">active</option>
          <option value="inactive">inactive</option>
          <option value="retired">retired</option>
        </select>
      </Field>
      <div className="rounded-xl border border-amber-400/15 bg-amber-400/[0.04] p-3 text-[10px] leading-5 text-amber-100">
        Pressure reference вводиться явно. RFX-10 backend candidate authority відхилить pressure binding,
        якщо reference відсутній або несумісний.
      </div>
    </div>
  );
}

function SignalCreateForm({
  draft,
  setDraft,
  busy,
  onSubmit,
}: {
  draft: SignalDraft;
  setDraft: (value: SignalDraft) => void;
  busy: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="mt-4 rounded-2xl border border-white/[0.07] bg-[#06142a]/70 p-3">
      <p className="text-xs font-medium text-white">Новий Signal</p>
      <SignalFields draft={draft} setDraft={setDraft} prefix="create" />
      <div className="mt-3 flex justify-end">
        <button type="submit" disabled={busy || !validSignalDraft(draft)} className={primaryButtonClass}>
          <Plus className="h-3.5 w-3.5" /> Створити Signal
        </button>
      </div>
    </form>
  );
}

function SignalEditor({
  signal,
  canManage,
  busy,
  onSave,
}: {
  signal: SignalRegistryRecord;
  canManage: boolean;
  busy: boolean;
  onSave: (record: SignalRegistryRecord, input: SignalWriteInput) => Promise<void>;
}) {
  const [draft, setDraft] = useState<SignalDraft>(() => signalDraftFrom(signal));

  if (!canManage) {
    return (
      <div className="rounded-xl border border-white/[0.06] p-4">
        <p className="text-sm font-medium text-white">{signal.displayName}</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <Fact label="Business key" value={signal.businessKey} />
          <Fact label="Physical quantity" value={signal.physicalQuantity} />
          <Fact label="Engineering unit" value={signal.engineeringUnit} />
          <Fact label="Lifecycle" value={signal.lifecycleState} />
        </div>
      </div>
    );
  }

  return (
    <form
      className="rounded-xl border border-white/[0.06] p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (validSignalDraft(draft)) void onSave(signal, toSignalInput(draft));
      }}
    >
      <p className="text-xs text-cyan-300">Signal v{signal.version}</p>
      <SignalFields draft={draft} setDraft={setDraft} prefix="edit" />
      <div className="mt-3 flex justify-end">
        <button type="submit" disabled={busy || !validSignalDraft(draft)} className={primaryButtonClass}>
          <Save className="h-3.5 w-3.5" /> Зберегти Signal
        </button>
      </div>
    </form>
  );
}

function SignalFields({
  draft,
  setDraft,
  prefix,
}: {
  draft: SignalDraft;
  setDraft: (value: SignalDraft) => void;
  prefix: "create" | "edit";
}) {
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <Field label="Business key">
        <input
          aria-label={`${prefix} signal business key`}
          value={draft.businessKey}
          onChange={(event) => setDraft({ ...draft, businessKey: event.target.value })}
          className={inputClass}
          required
        />
      </Field>
      <Field label="Display name">
        <input
          aria-label={`${prefix} signal display name`}
          value={draft.displayName}
          onChange={(event) => setDraft({ ...draft, displayName: event.target.value })}
          className={inputClass}
          required
        />
      </Field>
      <Field label="Physical quantity">
        <input
          aria-label={`${prefix} signal physical quantity`}
          value={draft.physicalQuantity}
          onChange={(event) => setDraft({ ...draft, physicalQuantity: event.target.value })}
          placeholder="pressure | temperature | relative_humidity"
          className={inputClass}
          required
        />
      </Field>
      <Field label="Engineering unit">
        <input
          aria-label={`${prefix} signal engineering unit`}
          value={draft.engineeringUnit}
          onChange={(event) => setDraft({ ...draft, engineeringUnit: event.target.value })}
          placeholder="bar | degC | %RH"
          className={inputClass}
          required
        />
      </Field>
      <Field label="Lifecycle">
        <select
          value={draft.lifecycleState}
          onChange={(event) =>
            setDraft({ ...draft, lifecycleState: event.target.value as RegistryLifecycleState })
          }
          className={inputClass}
        >
          <option value="active">active</option>
          <option value="inactive">inactive</option>
          <option value="retired">retired</option>
        </select>
      </Field>
      <div className="rounded-xl border border-cyan-300/10 bg-cyan-400/[0.03] p-3 text-[10px] leading-5 text-slate-400">
        Вказуйте process-neutral quantity. Наприклад <code>pressure</code>, а не{" "}
        <code>suction_pressure</code>. Остаточну role compatibility перевіряє backend.
      </div>
    </div>
  );
}

function AcceptanceSection({
  history,
  canManage,
  busy,
  value,
  setValue,
  label,
  setLabel,
  effectiveAt,
  setEffectiveAt,
  onSubmit,
}: {
  history: InstrumentAcceptanceRecord[];
  canManage: boolean;
  busy: boolean;
  value: "accepted" | "rejected";
  setValue: (value: "accepted" | "rejected") => void;
  label: string;
  setLabel: (value: string) => void;
  effectiveAt: string;
  setEffectiveAt: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  const current = [...history].reverse().find((item) => item.effectiveTo === null) ?? null;
  return (
    <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.16em] text-slate-500 uppercase">
            Calculation acceptance
          </p>
          <h2 className="mt-1 text-lg font-semibold text-white">Append-only acceptance history</h2>
        </div>
        <StatusChip
          text={
            current
              ? current.acceptedForCalculation
                ? "Accepted for calculation"
                : "Not accepted"
              : "Acceptance unresolved"
          }
        />
      </div>
      <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.05] p-3 text-xs leading-5 text-amber-100">
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        Accepted for calculation ≠ calibrated ≠ hardware verified. Ця дія лише керує canonical calculation
        eligibility.
      </div>
      <div className="mt-3 grid gap-2">
        {history.length === 0 ? (
          <p className="text-xs text-slate-500">Acceptance history відсутня. RFX-10 candidate не з’явиться.</p>
        ) : null}
        {history.map((item) => (
          <div key={item.id} className="rounded-xl border border-white/[0.06] bg-[#06142a]/70 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-slate-200">
                r{item.revision} · {item.acceptedForCalculation ? "accepted" : "rejected"}
              </p>
              <span className="text-[10px] text-slate-600">{item.stateLabel ?? "no label"}</span>
            </div>
            <p className="mt-1 text-[10px] text-slate-500">
              {formatTimestamp(item.effectiveFrom)} →{" "}
              {item.effectiveTo ? formatTimestamp(item.effectiveTo) : "поточний"}
            </p>
          </div>
        ))}
      </div>

      {canManage ? (
        <form onSubmit={onSubmit} className="mt-4 grid gap-3 md:grid-cols-3">
          <Field label="Calculation eligibility">
            <select
              value={value}
              onChange={(event) => setValue(event.target.value as "accepted" | "rejected")}
              className={inputClass}
            >
              <option value="accepted">Accepted for calculation</option>
              <option value="rejected">Not accepted</option>
            </select>
          </Field>
          <Field label="State label">
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="lab-approved"
              className={inputClass}
            />
          </Field>
          <Field label="Діє з">
            <input
              type="datetime-local"
              value={effectiveAt}
              onChange={(event) => setEffectiveAt(event.target.value)}
              className={inputClass}
              required
            />
          </Field>
          <div className="flex justify-end md:col-span-3">
            <button type="submit" disabled={busy || !effectiveAt} className={primaryButtonClass}>
              <CheckCircle2 className="h-3.5 w-3.5" /> Додати acceptance record
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <p className="text-[10px] text-slate-500">{label}</p>
      <p className="mt-1 break-words text-xs text-slate-200">{value}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1.5 text-xs text-slate-400">
      <span>{label}</span>
      {children}
    </label>
  );
}

function StatusChip({ text }: { text: string }) {
  return (
    <span className="rounded-full border border-white/[0.08] bg-white/[0.035] px-2.5 py-1 text-[10px] text-slate-300">
      {text}
    </span>
  );
}

function Notice({ tone, text }: { tone: "error" | "success"; text: string }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={
        tone === "error"
          ? "mt-4 rounded-xl border border-rose-400/20 bg-rose-400/[0.06] p-3 text-xs text-rose-200"
          : "mt-4 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.06] p-3 text-xs text-emerald-200"
      }
    >
      {text}
    </div>
  );
}

function PanelMessage({ title, text }: { title: string; text: string }) {
  return (
    <section className="rounded-3xl border border-white/[0.08] bg-[#091a31]/90 p-8 text-center">
      <Gauge className="mx-auto h-6 w-6 text-slate-600" />
      <h2 className="mt-3 text-sm font-semibold text-white">{title}</h2>
      <p className="mt-2 text-xs text-slate-500">{text}</p>
    </section>
  );
}

function instrumentDraftFrom(record: InstrumentRegistryRecord): InstrumentDraft {
  return {
    inventoryKey: record.inventoryKey,
    displayName: record.displayName,
    instrumentKind: record.instrumentKind,
    manufacturer: record.manufacturer ?? "",
    model: record.model ?? "",
    serialNumber: record.serialNumber ?? "",
    pressureReference: record.pressureReference ?? "",
    lifecycleState: record.lifecycleState,
  };
}

function signalDraftFrom(record: SignalRegistryRecord): SignalDraft {
  return {
    businessKey: record.businessKey,
    displayName: record.displayName,
    physicalQuantity: record.physicalQuantity,
    engineeringUnit: record.engineeringUnit,
    lifecycleState: record.lifecycleState,
  };
}

function toInstrumentInput(draft: InstrumentDraft): InstrumentWriteInput {
  return {
    inventoryKey: draft.inventoryKey.trim(),
    displayName: draft.displayName.trim(),
    instrumentKind: draft.instrumentKind.trim(),
    manufacturer: optionalText(draft.manufacturer),
    model: optionalText(draft.model),
    serialNumber: optionalText(draft.serialNumber),
    pressureReference: draft.pressureReference || null,
    lifecycleState: draft.lifecycleState,
    metadata: {},
  };
}

function toSignalInput(draft: SignalDraft): SignalWriteInput {
  return {
    businessKey: draft.businessKey.trim(),
    displayName: draft.displayName.trim(),
    physicalQuantity: draft.physicalQuantity.trim(),
    engineeringUnit: draft.engineeringUnit.trim(),
    lifecycleState: draft.lifecycleState,
    metadata: {},
  };
}

function validInstrumentDraft(draft: InstrumentDraft): boolean {
  return Boolean(draft.inventoryKey.trim() && draft.displayName.trim() && draft.instrumentKind.trim());
}

function validSignalDraft(draft: SignalDraft): boolean {
  return Boolean(
    draft.businessKey.trim() &&
      draft.displayName.trim() &&
      draft.physicalQuantity.trim() &&
      draft.engineeringUnit.trim(),
  );
}

function optionalText(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

function lifecycleLabel(value: RegistryLifecycleState): string {
  if (value === "active") return "Активний";
  if (value === "inactive") return "Неактивний";
  return "Виведений";
}

function localDateTimeValue(date: Date): string {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function parseLocalDateTime(value: string): Date {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) {
    throw new Error("Вкажіть коректний effective time.");
  }
  return date;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString("uk-UA") : value;
}

function readError(cause: unknown, fallback: string): string {
  if (cause instanceof InstrumentationRegistryRepositoryError) {
    const versionHint =
      cause.actualVersion !== null
        ? ` Canonical version: ${cause.actualVersion}; очікувалась ${cause.expectedVersion ?? "—"}.`
        : "";
    return `${cause.message} (${cause.code}).${versionHint}`;
  }
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

const inputClass =
  "w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-cyan-300/40";
const primaryButtonClass =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-xl bg-cyan-500 px-3.5 py-2 text-xs font-semibold text-[#031021] disabled:cursor-not-allowed disabled:opacity-40";
const secondaryButtonClass =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-xl border border-cyan-300/15 bg-cyan-400/[0.05] px-3.5 py-2 text-xs text-cyan-100 disabled:opacity-40";
