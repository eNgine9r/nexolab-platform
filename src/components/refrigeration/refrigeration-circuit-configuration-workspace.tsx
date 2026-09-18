"use client";

import { AlertTriangle, CheckCircle2, Link2, Plus, RefreshCw, Snowflake } from "lucide-react";
import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import {
  CANONICAL_PROPERTY_PROVIDER_PROFILE,
  CIRCUIT_PROCESS_ROLES,
  type CalculationPolicyRecord,
  type CircuitBindingCandidate,
  type CircuitBindingRecord,
  type CircuitConfigurationRecord,
  type CircuitLifecycleRecord,
  type CircuitLifecycleState,
  type CircuitProcessRole,
  type RefrigerationCircuitConfigurationRepository,
  type RefrigerationCircuitRecord,
} from "@/features/refrigeration/circuit-configuration-repository";

const roleLabels: Record<CircuitProcessRole, string> = {
  suction_pressure: "Тиск кипіння / всмоктування",
  condensing_pressure: "Тиск конденсації",
  suction_line_temperature: "Температура на виході випарника",
  liquid_line_temperature: "Температура рідини / входу у вітрину",
  atmospheric_pressure: "Атмосферний тиск",
  relative_humidity: "Відносна вологість",
};

const lifecycleLabels: Record<CircuitLifecycleState, string> = {
  active: "Активний",
  inactive: "Неактивний",
  retired: "Виведений",
};

type CircuitDetails = {
  lifecycle: CircuitLifecycleRecord[];
  configurations: CircuitConfigurationRecord[];
  bindings: CircuitBindingRecord[];
};

export function RefrigerationCircuitConfigurationWorkspace({
  equipmentId,
  repository,
  canManage,
}: {
  equipmentId: string;
  repository: RefrigerationCircuitConfigurationRepository | null;
  canManage: boolean;
}) {
  const [circuits, setCircuits] = useState<RefrigerationCircuitRecord[]>([]);
  const [policies, setPolicies] = useState<CalculationPolicyRecord[]>([]);
  const [selectedCircuitId, setSelectedCircuitId] = useState<string | null>(null);
  const [details, setDetails] = useState<CircuitDetails | null>(null);
  const [loading, setLoading] = useState(repository !== null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [mutationBusy, setMutationBusy] = useState(false);

  const [newBusinessKey, setNewBusinessKey] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newInitialState, setNewInitialState] = useState<CircuitLifecycleState>("active");
  const [createAt, setCreateAt] = useState(() => localDateTimeValue(new Date()));

  const [lifecycleState, setLifecycleState] = useState<CircuitLifecycleState>("active");
  const [lifecycleAt, setLifecycleAt] = useState(() => localDateTimeValue(new Date()));

  const [refrigerantCode, setRefrigerantCode] = useState("");
  const [policyVersion, setPolicyVersion] = useState("");
  const [configurationAt, setConfigurationAt] = useState(() => localDateTimeValue(new Date()));

  const [bindingAt, setBindingAt] = useState(() => localDateTimeValue(new Date()));
  const [candidateRole, setCandidateRole] = useState<CircuitProcessRole | null>(null);
  const [candidates, setCandidates] = useState<CircuitBindingCandidate[]>([]);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateSignalId, setCandidateSignalId] = useState("");

  const loadBase = useCallback(
    async (preferredCircuitId?: string) => {
      if (!repository) return;
      setLoading(true);
      setError(null);
      try {
        const [nextCircuits, nextPolicies] = await Promise.all([
          repository.listCircuits(equipmentId),
          repository.listPolicies(),
        ]);
        setCircuits(nextCircuits);
        setPolicies(nextPolicies);
        const preferred =
          preferredCircuitId && nextCircuits.some((item) => item.id === preferredCircuitId)
            ? preferredCircuitId
            : selectedCircuitId && nextCircuits.some((item) => item.id === selectedCircuitId)
              ? selectedCircuitId
              : (nextCircuits[0]?.id ?? null);
        setSelectedCircuitId(preferred);
        setPolicyVersion((current) => current || nextPolicies[0]?.version || "");
      } catch (cause) {
        setError(readError(cause, "Не вдалося завантажити конфігурацію холодильного контуру."));
      } finally {
        setLoading(false);
      }
    },
    [equipmentId, repository, selectedCircuitId],
  );

  const loadDetails = useCallback(
    async (circuitId: string) => {
      if (!repository) return;
      setDetailsLoading(true);
      setError(null);
      try {
        const [lifecycle, configurations, bindings] = await Promise.all([
          repository.listLifecycle(circuitId),
          repository.listConfigurations(circuitId),
          repository.listBindings(circuitId, true),
        ]);
        setDetails({ lifecycle, configurations, bindings });
        const currentLifecycle = latestOpen(lifecycle);
        if (currentLifecycle) setLifecycleState(currentLifecycle.state);
        const currentConfiguration = latestOpen(configurations);
        if (currentConfiguration) {
          setRefrigerantCode(currentConfiguration.refrigerantCode);
          setPolicyVersion(currentConfiguration.calculationPolicyVersion);
        }
      } catch (cause) {
        setDetails(null);
        setError(readError(cause, "Не вдалося завантажити історію холодильного контуру."));
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

    void Promise.all([
      repository.listCircuits(equipmentId, controller.signal),
      repository.listPolicies(controller.signal),
    ])
      .then(([nextCircuits, nextPolicies]) => {
        if (!active) return;
        setCircuits(nextCircuits);
        setPolicies(nextPolicies);
        setSelectedCircuitId((current) =>
          current && nextCircuits.some((item) => item.id === current)
            ? current
            : (nextCircuits[0]?.id ?? null),
        );
        setPolicyVersion((current) => current || nextPolicies[0]?.version || "");
        if (nextCircuits.length === 0) setDetails(null);
      })
      .catch((cause) => {
        if (!active || controller.signal.aborted) return;
        setError(readError(cause, "Не вдалося завантажити конфігурацію холодильного контуру."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [equipmentId, repository]);

  useEffect(() => {
    if (!repository || !selectedCircuitId) return;
    let active = true;
    const controller = new AbortController();

    void Promise.all([
      repository.listLifecycle(selectedCircuitId, controller.signal),
      repository.listConfigurations(selectedCircuitId, controller.signal),
      repository.listBindings(selectedCircuitId, true, controller.signal),
    ])
      .then(([lifecycle, configurations, bindings]) => {
        if (!active) return;
        setDetails({ lifecycle, configurations, bindings });
        const currentLifecycle = latestOpen(lifecycle);
        if (currentLifecycle) setLifecycleState(currentLifecycle.state);
        const currentConfiguration = latestOpen(configurations);
        if (currentConfiguration) {
          setRefrigerantCode(currentConfiguration.refrigerantCode);
          setPolicyVersion(currentConfiguration.calculationPolicyVersion);
        }
      })
      .catch((cause) => {
        if (!active || controller.signal.aborted) return;
        setDetails(null);
        setError(readError(cause, "Не вдалося завантажити історію холодильного контуру."));
      })
      .finally(() => {
        if (active) setDetailsLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [repository, selectedCircuitId]);

  const selectedCircuit = useMemo(
    () => circuits.find((item) => item.id === selectedCircuitId) ?? null,
    [circuits, selectedCircuitId],
  );

  const mutate = useCallback(async (action: () => Promise<void>) => {
    setMutationBusy(true);
    setMutationError(null);
    try {
      await action();
    } catch (cause) {
      setMutationError(readError(cause, "Операцію конфігурації відхилено."));
    } finally {
      setMutationBusy(false);
    }
  }, []);

  if (!repository) {
    return (
      <PanelMessage
        title="Конфігурація контуру недоступна"
        text="Live API конфігурації не підключено. Demo-дані не використовуються як authoritative state."
      />
    );
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!canManage || !newBusinessKey.trim() || !newDisplayName.trim()) return;
    await mutate(async () => {
      const created = await repository!.createCircuit({
        equipmentId,
        businessKey: newBusinessKey.trim(),
        displayName: newDisplayName.trim(),
        initialState: newInitialState,
        validFrom: parseLocalDateTime(createAt),
      });
      setNewBusinessKey("");
      setNewDisplayName("");
      await loadBase(created.id);
    });
  }

  async function handleLifecycle(event: FormEvent) {
    event.preventDefault();
    if (!canManage || !selectedCircuit) return;
    await mutate(async () => {
      await repository!.appendLifecycle(selectedCircuit.id, {
        state: lifecycleState,
        validFrom: parseLocalDateTime(lifecycleAt),
      });
      await loadDetails(selectedCircuit.id);
    });
  }

  async function handleConfiguration(event: FormEvent) {
    event.preventDefault();
    if (
      !canManage ||
      !selectedCircuit ||
      !refrigerantCode.trim() ||
      !policyVersion ||
      !policies.some((policy) => policy.version === policyVersion)
    )
      return;
    await mutate(async () => {
      await repository!.appendConfiguration(selectedCircuit.id, {
        refrigerantCode: refrigerantCode.trim().toUpperCase(),
        calculationPolicyVersion: policyVersion,
        propertyProviderProfile: CANONICAL_PROPERTY_PROVIDER_PROFILE,
        validFrom: parseLocalDateTime(configurationAt),
      });
      await loadDetails(selectedCircuit.id);
    });
  }

  async function loadCandidates(role: CircuitProcessRole) {
    setCandidateRole(role);
    setCandidateSignalId("");
    setCandidateLoading(true);
    setMutationError(null);
    try {
      const next = await repository!.listBindingCandidates(role, parseLocalDateTime(bindingAt));
      setCandidates(next);
      setCandidateSignalId(next[0]?.signalId ?? "");
    } catch (cause) {
      setCandidates([]);
      setMutationError(readError(cause, "Не вдалося отримати сумісні сигнали."));
    } finally {
      setCandidateLoading(false);
    }
  }

  async function bindRole(role: CircuitProcessRole) {
    if (!canManage || !selectedCircuit || !candidateSignalId) return;
    await mutate(async () => {
      await repository!.appendBinding(selectedCircuit.id, {
        role,
        signalId: candidateSignalId,
        validFrom: parseLocalDateTime(bindingAt),
      });
      setCandidateRole(null);
      setCandidates([]);
      setCandidateSignalId("");
      await loadDetails(selectedCircuit.id);
    });
  }

  async function endRole(role: CircuitProcessRole) {
    if (!canManage || !selectedCircuit) return;
    await mutate(async () => {
      await repository!.endBinding(selectedCircuit.id, role, parseLocalDateTime(bindingAt));
      await loadDetails(selectedCircuit.id);
    });
  }

  return (
    <div className="grid gap-3 xl:gap-4" data-testid="refrigeration-circuit-configuration">
      <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-200">
              <Snowflake className="h-4 w-4" />
            </span>
            <div>
              <p className="text-[10px] tracking-[0.16em] text-cyan-300 uppercase">
                Refrigeration Circuit · canonical state
              </p>
              <h2 className="mt-1 text-lg font-semibold text-white">Конфігурація холодильного контуру</h2>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">
                Refrigerant, calculation policy та semantic Signal→role bindings. Історія append-only;
                контролер і Modbus тут не налаштовуються.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void loadBase(selectedCircuitId ?? undefined)}
            disabled={loading}
            className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 text-xs text-slate-300 disabled:opacity-50"
          >
            <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            Оновити
          </button>
        </div>

        {!canManage ? (
          <div className="mt-4 rounded-xl border border-slate-400/15 bg-slate-400/[0.05] p-3 text-xs text-slate-300">
            Режим перегляду. Зміни доступні лише користувачу з правом <code>equipment.manage</code>.
          </div>
        ) : null}
        {error ? <ErrorBox text={error} /> : null}
        {mutationError ? <ErrorBox text={mutationError} /> : null}

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,0.65fr)_minmax(0,1.35fr)]">
          <div className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 p-3">
            <p className="text-[10px] tracking-[0.14em] text-slate-500 uppercase">Контури обладнання</p>
            {circuits.length === 0 && !loading ? (
              <p className="mt-3 text-xs text-slate-400">Для цього обладнання контурів ще немає.</p>
            ) : (
              <div className="mt-2 grid gap-2">
                {circuits.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedCircuitId(item.id)}
                    aria-pressed={item.id === selectedCircuitId}
                    className={
                      item.id === selectedCircuitId
                        ? "rounded-xl border border-cyan-300/25 bg-cyan-400/[0.08] p-3 text-left"
                        : "rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-left"
                    }
                  >
                    <span className="block text-sm font-medium text-white">{item.displayName}</span>
                    <span className="mt-1 block text-[10px] text-slate-500">{item.businessKey}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 p-3">
            <p className="text-[10px] tracking-[0.14em] text-slate-500 uppercase">Новий контур</p>
            {canManage ? (
              <form onSubmit={handleCreate} className="mt-3 grid gap-2 sm:grid-cols-2">
                <Field label="Business key">
                  <input
                    value={newBusinessKey}
                    onChange={(event) => setNewBusinessKey(event.target.value)}
                    required
                    className={inputClass}
                  />
                </Field>
                <Field label="Назва">
                  <input
                    value={newDisplayName}
                    onChange={(event) => setNewDisplayName(event.target.value)}
                    required
                    className={inputClass}
                  />
                </Field>
                <Field label="Початковий стан">
                  <select
                    value={newInitialState}
                    onChange={(event) => setNewInitialState(event.target.value as CircuitLifecycleState)}
                    className={inputClass}
                  >
                    {(["active", "inactive", "retired"] as const).map((state) => (
                      <option key={state} value={state}>
                        {lifecycleLabels[state]}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Діє з">
                  <input
                    type="datetime-local"
                    value={createAt}
                    onChange={(event) => setCreateAt(event.target.value)}
                    className={inputClass}
                    required
                  />
                </Field>
                <div className="flex items-center justify-between gap-3 pt-1 sm:col-span-2">
                  <p className="text-[10px] text-slate-500">
                    Буде створено Circuit + початковий lifecycle record. Без hardware action.
                  </p>
                  <button
                    type="submit"
                    disabled={mutationBusy || !newBusinessKey.trim() || !newDisplayName.trim()}
                    className={primaryButtonClass}
                  >
                    <Plus className="h-3.5 w-3.5" /> Створити контур
                  </button>
                </div>
              </form>
            ) : (
              <p className="mt-3 text-xs text-slate-500">Створення вимкнено у read-only режимі.</p>
            )}
          </div>
        </div>
      </section>

      {selectedCircuit ? (
        <>
          <CircuitLifecycleSection
            circuit={selectedCircuit}
            history={details?.lifecycle ?? []}
            loading={detailsLoading}
            canManage={canManage}
            busy={mutationBusy}
            state={lifecycleState}
            setState={setLifecycleState}
            effectiveAt={lifecycleAt}
            setEffectiveAt={setLifecycleAt}
            onSubmit={handleLifecycle}
          />
          <CircuitConfigurationSection
            history={details?.configurations ?? []}
            policies={policies}
            canManage={canManage}
            busy={mutationBusy}
            refrigerantCode={refrigerantCode}
            setRefrigerantCode={setRefrigerantCode}
            policyVersion={policyVersion}
            setPolicyVersion={setPolicyVersion}
            effectiveAt={configurationAt}
            setEffectiveAt={setConfigurationAt}
            onSubmit={handleConfiguration}
          />
          <CircuitBindingsSection
            history={details?.bindings ?? []}
            canManage={canManage}
            busy={mutationBusy}
            effectiveAt={bindingAt}
            setEffectiveAt={(value) => {
              setBindingAt(value);
              setCandidateRole(null);
              setCandidates([]);
              setCandidateSignalId("");
            }}
            candidateRole={candidateRole}
            candidates={candidates}
            candidateLoading={candidateLoading}
            candidateSignalId={candidateSignalId}
            setCandidateSignalId={setCandidateSignalId}
            onLoadCandidates={loadCandidates}
            onBind={bindRole}
            onEnd={endRole}
          />
        </>
      ) : null}
    </div>
  );
}

function CircuitLifecycleSection({
  circuit,
  history,
  loading,
  canManage,
  busy,
  state,
  setState,
  effectiveAt,
  setEffectiveAt,
  onSubmit,
}: {
  circuit: RefrigerationCircuitRecord;
  history: CircuitLifecycleRecord[];
  loading: boolean;
  canManage: boolean;
  busy: boolean;
  state: CircuitLifecycleState;
  setState: (value: CircuitLifecycleState) => void;
  effectiveAt: string;
  setEffectiveAt: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  const current = latestOpen(history);
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-slate-500 uppercase">Lifecycle</p>
          <h3 className="mt-1 text-base font-semibold text-white">{circuit.displayName}</h3>
        </div>
        <StatusChip text={current ? lifecycleLabels[current.state] : loading ? "Завантаження" : "Невідомо"} />
      </div>
      <HistoryRows
        rows={history.map((item) => ({
          id: item.id,
          title: `r${item.revision} · ${lifecycleLabels[item.state]}`,
          meta: intervalText(item.validFrom, item.validTo),
        }))}
        empty="Lifecycle history відсутня."
      />
      {canManage ? (
        <form onSubmit={onSubmit} className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <Field label="Новий стан">
            <select
              value={state}
              onChange={(event) => setState(event.target.value as CircuitLifecycleState)}
              className={inputClass}
            >
              {(["active", "inactive", "retired"] as const).map((item) => (
                <option key={item} value={item}>
                  {lifecycleLabels[item]}
                </option>
              ))}
            </select>
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
          <button type="submit" disabled={busy} className={primaryButtonClass}>
            <CheckCircle2 className="h-3.5 w-3.5" /> Додати стан
          </button>
          <p className="text-[10px] text-slate-500 sm:col-span-3">
            Буде додано нову lifecycle-версію з effective time {effectiveAt || "—"}.
          </p>
        </form>
      ) : null}
    </section>
  );
}

function CircuitConfigurationSection({
  history,
  policies,
  canManage,
  busy,
  refrigerantCode,
  setRefrigerantCode,
  policyVersion,
  setPolicyVersion,
  effectiveAt,
  setEffectiveAt,
  onSubmit,
}: {
  history: CircuitConfigurationRecord[];
  policies: CalculationPolicyRecord[];
  canManage: boolean;
  busy: boolean;
  refrigerantCode: string;
  setRefrigerantCode: (value: string) => void;
  policyVersion: string;
  setPolicyVersion: (value: string) => void;
  effectiveAt: string;
  setEffectiveAt: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  const selectedPolicy = policies.find((item) => item.version === policyVersion) ?? null;
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4">
      <p className="text-[10px] tracking-[0.14em] text-slate-500 uppercase">
        Refrigerant + calculation policy
      </p>
      <HistoryRows
        rows={history.map((item) => ({
          id: item.id,
          title: `r${item.revision} · ${item.refrigerantCode} · ${item.calculationPolicyVersion}`,
          meta: `${intervalText(item.validFrom, item.validTo)} · ${item.propertyProviderProfile ?? "provider unresolved"}`,
        }))}
        empty="Configuration history відсутня — derived values мають залишатися unavailable."
      />
      {canManage ? (
        <form onSubmit={onSubmit} className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Холодоагент">
            <input
              value={refrigerantCode}
              onChange={(event) => setRefrigerantCode(event.target.value)}
              placeholder="R290"
              className={inputClass}
              required
            />
          </Field>
          <Field label="Calculation policy">
            <select
              value={policyVersion}
              onChange={(event) => setPolicyVersion(event.target.value)}
              className={inputClass}
              required
            >
              <option value="">Оберіть policy</option>
              {policies.map((policy) => (
                <option key={policy.id} value={policy.version}>
                  {policy.version}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Property provider">
            <input value={CANONICAL_PROPERTY_PROVIDER_PROFILE} readOnly className={inputClass} />
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
          {selectedPolicy ? (
            <PolicySummary policy={selectedPolicy} />
          ) : (
            <div className="rounded-xl border border-amber-400/15 bg-amber-400/[0.05] p-3 text-xs text-amber-200 md:col-span-2 xl:col-span-4">
              Canonical calculation policy не вибрано. Frontend не створює прихованих/default thresholds.
            </div>
          )}
          <div className="flex justify-end md:col-span-2 xl:col-span-4">
            <button
              type="submit"
              disabled={busy || !selectedPolicy || !refrigerantCode.trim()}
              className={primaryButtonClass}
            >
              Додати версію конфігурації
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function CircuitBindingsSection({
  history,
  canManage,
  busy,
  effectiveAt,
  setEffectiveAt,
  candidateRole,
  candidates,
  candidateLoading,
  candidateSignalId,
  setCandidateSignalId,
  onLoadCandidates,
  onBind,
  onEnd,
}: {
  history: CircuitBindingRecord[];
  canManage: boolean;
  busy: boolean;
  effectiveAt: string;
  setEffectiveAt: (value: string) => void;
  candidateRole: CircuitProcessRole | null;
  candidates: CircuitBindingCandidate[];
  candidateLoading: boolean;
  candidateSignalId: string;
  setCandidateSignalId: (value: string) => void;
  onLoadCandidates: (role: CircuitProcessRole) => Promise<void>;
  onBind: (role: CircuitProcessRole) => Promise<void>;
  onEnd: (role: CircuitProcessRole) => Promise<void>;
}) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] tracking-[0.14em] text-slate-500 uppercase">
            Semantic Signal → role bindings
          </p>
          <h3 className="mt-1 text-base font-semibold text-white">Точки холодильного контуру</h3>
        </div>
        {canManage ? (
          <Field label="Effective time для наступної binding-операції">
            <input
              type="datetime-local"
              value={effectiveAt}
              onChange={(event) => setEffectiveAt(event.target.value)}
              className={inputClass}
            />
          </Field>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {CIRCUIT_PROCESS_ROLES.map((role) => {
          const roleHistory = history.filter((item) => item.role === role);
          const current = latestOpen(roleHistory);
          const editing = candidateRole === role;
          return (
            <article key={role} className="rounded-xl border border-white/[0.07] bg-[#06142a]/70 p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-white">{roleLabels[role]}</p>
                  <code className="mt-1 block text-[9px] text-slate-600">{role}</code>
                </div>
                <StatusChip text={current ? "Прив’язано" : "Не налаштовано"} />
              </div>
              {current ? (
                <div className="mt-3 rounded-lg border border-emerald-400/12 bg-emerald-400/[0.04] p-2.5">
                  <p className="text-xs text-slate-200">{current.signalId}</p>
                  <p className="mt-1 text-[10px] text-slate-500">
                    {current.physicalQuantity} · {current.engineeringUnit}
                    {current.pressureReference ? ` · ${current.pressureReference}` : ""}
                  </p>
                  <p className="mt-1 text-[9px] text-slate-600">
                    {intervalText(current.validFrom, current.validTo)}
                  </p>
                </div>
              ) : (
                <p className="mt-3 text-xs text-slate-500">Canonical binding відсутній.</p>
              )}
              {roleHistory.length > 1 ? (
                <p className="mt-2 text-[9px] text-slate-600">Історичних версій: {roleHistory.length}</p>
              ) : null}
              {canManage ? (
                <div className="mt-3 grid gap-2">
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busy || candidateLoading}
                      onClick={() => void onLoadCandidates(role)}
                      className={secondaryButtonClass}
                    >
                      <Link2 className="h-3.5 w-3.5" /> {current ? "Замінити сигнал" : "Обрати сигнал"}
                    </button>
                    {current ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void onEnd(role)}
                        className={dangerButtonClass}
                      >
                        Завершити binding
                      </button>
                    ) : null}
                  </div>
                  {editing ? (
                    <div className="rounded-xl border border-cyan-300/12 bg-cyan-400/[0.035] p-2.5">
                      {candidateLoading ? (
                        <p className="text-xs text-slate-500">Перевірка canonical candidates…</p>
                      ) : candidates.length === 0 ? (
                        <p className="text-xs text-amber-200">
                          Немає accepted сумісних Signals для цього role та effective time.
                        </p>
                      ) : (
                        <>
                          <select
                            value={candidateSignalId}
                            onChange={(event) => setCandidateSignalId(event.target.value)}
                            className={inputClass}
                          >
                            {candidates.map((candidate) => (
                              <option key={candidate.signalId} value={candidate.signalId}>
                                {candidate.instrumentDisplayName} · {candidate.signalDisplayName} ·{" "}
                                {candidate.engineeringUnit}
                              </option>
                            ))}
                          </select>
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <p className="text-[9px] text-slate-600">
                              Список сформовано backend authority на {effectiveAt || "—"}.
                            </p>
                            <button
                              type="button"
                              disabled={busy || !candidateSignalId}
                              onClick={() => void onBind(role)}
                              className={primaryButtonClass}
                            >
                              {current ? "Замінити" : "Прив’язати"}
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PolicySummary({ policy }: { policy: CalculationPolicyRecord }) {
  return (
    <div className="grid gap-2 rounded-xl border border-cyan-300/12 bg-cyan-400/[0.035] p-3 text-[10px] text-slate-400 sm:grid-cols-2 md:col-span-2 xl:col-span-4 xl:grid-cols-4">
      <span>Max age: {formatDuration(policy.maximumAgeMs)}</span>
      <span>Future skew: {formatDuration(policy.maximumFutureClockSkewMs)}</span>
      <span>Cross-input skew: {formatDuration(policy.maximumCrossInputSkewMs)}</span>
      <span>
        Calibration: {policy.acceptedCalibrationStates.join(", ")}
        {policy.requireCalibrationAtObservation ? " · observation required" : ""}
      </span>
    </div>
  );
}

function HistoryRows({
  rows,
  empty,
}: {
  rows: Array<{ id: string; title: string; meta: string }>;
  empty: string;
}) {
  if (rows.length === 0) return <p className="mt-3 text-xs text-slate-500">{empty}</p>;
  return (
    <div className="mt-3 grid gap-1.5">
      {rows.map((row) => (
        <div key={row.id} className="rounded-lg border border-white/[0.06] bg-[#06142a]/70 px-3 py-2">
          <p className="text-xs text-slate-200">{row.title}</p>
          <p className="mt-0.5 text-[9px] text-slate-600">{row.meta}</p>
        </div>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-[10px] text-slate-500">
      <span>{label}</span>
      {children}
    </label>
  );
}

function StatusChip({ text }: { text: string }) {
  return (
    <span className="rounded-full border border-white/[0.08] bg-white/[0.035] px-2 py-1 text-[9px] text-slate-300">
      {text}
    </span>
  );
}

function ErrorBox({ text }: { text: string }) {
  return (
    <div
      role="alert"
      className="mt-4 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-400/[0.06] p-3 text-xs text-rose-200"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

function PanelMessage({ title, text }: { title: string; text: string }) {
  return (
    <section className="rounded-2xl border border-white/[0.08] bg-[#081a32] p-8 text-center">
      <Snowflake className="mx-auto h-6 w-6 text-slate-600" />
      <h2 className="mt-3 text-sm font-semibold text-white">{title}</h2>
      <p className="mt-2 text-xs text-slate-500">{text}</p>
    </section>
  );
}

function latestOpen<T extends { validTo: string | null }>(rows: T[]): T | null {
  return [...rows].reverse().find((row) => row.validTo === null) ?? null;
}

function intervalText(validFrom: string, validTo: string | null): string {
  return `${formatTimestamp(validFrom)} → ${validTo ? formatTimestamp(validTo) : "поточний"}`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return date.toLocaleString("uk-UA", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms % 1000 === 0 ? 0 : 1)} s`;
}

function localDateTimeValue(date: Date): string {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function parseLocalDateTime(value: string): Date {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) throw new Error("Вкажіть коректний effective time.");
  return date;
}

function readError(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

const inputClass =
  "min-h-10 w-full rounded-xl border border-white/10 bg-[#07172d] px-3 text-xs text-slate-100 outline-none focus:border-cyan-300/30";
const primaryButtonClass =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-xl bg-cyan-500 px-3 text-xs font-semibold text-[#031021] disabled:cursor-not-allowed disabled:opacity-40";
const secondaryButtonClass =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-xl border border-cyan-300/15 bg-cyan-400/[0.05] px-3 text-xs text-cyan-100 disabled:opacity-40";
const dangerButtonClass =
  "inline-flex min-h-9 items-center justify-center rounded-xl border border-rose-400/20 bg-rose-400/[0.05] px-3 text-xs text-rose-200 disabled:opacity-40";
