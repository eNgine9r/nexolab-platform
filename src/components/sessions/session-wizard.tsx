"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, LoaderCircle, ShieldCheck } from "lucide-react";

import {
  buildSessionTelemetrySelectionModel,
  resolveSelectedSessionBindings,
} from "@/features/test-sessions/telemetry-selection";
import { invalidateSessionListReadModels } from "@/features/test-sessions/use-session-list-read-model";
import { useLiveDashboardInventory } from "@/hooks/use-live-dashboard-inventory";
import {
  createIdempotencyKey,
  createOperatorCommand,
  createSessionApiClient,
} from "@/lib/sessions/api-client";
import type { SessionBindingOption } from "@/lib/sessions/types";

import {
  EquipmentStep,
  GeneralStep,
  LimitsStep,
  MethodStep,
  ObjectStep,
  ReviewStep,
  SamplingStep,
  StagesStep,
} from "./wizard-steps";
import {
  createInitialWizardForm,
  isWizardStepValid,
  WIZARD_STEPS,
  type SessionWizardForm,
} from "./wizard-model";

type SelectionLoadStatus = "loading" | "ready" | "error";

function bindingIdentity(binding: SessionBindingOption): string {
  return [binding.node_id, binding.equipment_id, binding.channel_id, binding.metric, binding.unit]
    .map(encodeURIComponent)
    .join("|");
}

function sameSelection(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((value) => rightSet.has(value));
}

export function SessionWizard() {
  const router = useRouter();
  const sessionClient = useMemo(() => createSessionApiClient(), []);
  const configuredOrganizationId = process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null;
  const hierarchyOrganizationId = configuredOrganizationId ?? "__current_organization__";
  const [step, setStep] = useState(0);
  const selectionEnabled = step >= 3;
  const [form, setForm] = useState<SessionWizardForm>(createInitialWizardForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [createdSessionId, setCreatedSessionId] = useState<string | null>(null);
  const [bindingOptions, setBindingOptions] = useState<SessionBindingOption[]>([]);
  const [bindingOptionsStatus, setBindingOptionsStatus] = useState<SelectionLoadStatus>("loading");
  const [bindingOptionsError, setBindingOptionsError] = useState<Error | null>(null);
  const [bindingOptionsRevision, setBindingOptionsRevision] = useState(0);
  const inventory = useLiveDashboardInventory({
    enabled: selectionEnabled,
    organizationId: configuredOrganizationId,
  });
  const operation = useRef({
    sessionId: null as string | null,
    selectionKeys: null as string[] | null,
    createKey: createIdempotencyKey("session-create"),
    bindingKeys: new Map<string, string>(),
    limitsKey: createIdempotencyKey("limit-version"),
  });

  useEffect(() => {
    if (!selectionEnabled) return;
    const controller = new AbortController();
    setBindingOptionsStatus("loading");
    setBindingOptionsError(null);
    void sessionClient
      .listProductionBindingOptions(controller.signal)
      .then((options) => {
        if (controller.signal.aborted) return;
        setBindingOptions(options);
        setBindingOptionsStatus("ready");
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted) return;
        setBindingOptionsError(
          nextError instanceof Error ? nextError : new Error("Не вдалося завантажити session contract."),
        );
        setBindingOptionsStatus("error");
      });
    return () => controller.abort();
  }, [bindingOptionsRevision, selectionEnabled, sessionClient]);

  const selectionModel = useMemo(
    () => buildSessionTelemetrySelectionModel(hierarchyOrganizationId, inventory.items, bindingOptions),
    [bindingOptions, hierarchyOrganizationId, inventory.items],
  );
  const selectedBindings = useMemo(
    () => resolveSelectedSessionBindings(selectionModel, form.selectedTelemetryKeys),
    [form.selectedTelemetryKeys, selectionModel],
  );
  const selectionStatus: SelectionLoadStatus =
    inventory.status === "error" || bindingOptionsStatus === "error"
      ? "error"
      : inventory.status === "ready" && bindingOptionsStatus === "ready"
        ? "ready"
        : "loading";
  const selectionError = bindingOptionsError ?? inventory.error;
  const selectedKeyCount = new Set(form.selectedTelemetryKeys).size;
  const baseStepValid = useMemo(() => isWizardStepValid(step, form), [form, step]);
  const stepValid =
    step === 3
      ? baseStepValid &&
        selectionStatus === "ready" &&
        selectedBindings.length === selectedKeyCount &&
        selectedKeyCount > 0
      : baseStepValid;

  const update = <K extends keyof SessionWizardForm>(key: K, value: SessionWizardForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const retrySelection = () => {
    inventory.retry();
    setBindingOptionsRevision((value) => value + 1);
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (selectionStatus !== "ready" || selectedBindings.length === 0 || selectedBindings.length !== selectedKeyCount) {
        throw new Error("Telemetry selection застарів або не відповідає валідованому session contract. Оновіть вибір.");
      }

      if (operation.current.selectionKeys) {
        if (!sameSelection(operation.current.selectionKeys, form.selectedTelemetryKeys)) {
          throw new Error(
            "Draft уже створено з попереднім telemetry selection. Повторіть операцію з початковим вибором без зміни каналів.",
          );
        }
      } else {
        operation.current.selectionKeys = [...form.selectedTelemetryKeys];
      }

      const frozenBindings = resolveSelectedSessionBindings(selectionModel, operation.current.selectionKeys);
      if (frozenBindings.length !== operation.current.selectionKeys.length) {
        throw new Error("Збережений telemetry selection більше не доступний у поточному локальному inventory.");
      }

      let sessionId = operation.current.sessionId;

      if (!sessionId) {
        const created = await sessionClient.createSession(
          {
            session_number: form.sessionNumber.trim(),
            title: form.title.trim(),
            test_object: form.testObject.trim(),
            node_id: "edge-01",
            customer: form.customer.trim(),
            model: form.model.trim(),
            serial_number: form.serialNumber.trim(),
            standard: form.standard.trim(),
            method: form.method.trim(),
            operator_id: form.operatorId.trim() || null,
            responsible_engineer_id: form.engineerId.trim() || null,
            metadata_payload: {
              sampling_policy: {
                interval_seconds: form.samplingSeconds,
                mode: "fixed_interval",
              },
              stage_plan: form.stages,
              telemetry_selection_count: frozenBindings.length,
              created_by: "nexolab-dashboard-wizard-v2",
            },
            ...createOperatorCommand("Created from the NEXOLAB 8-step laboratory wizard"),
          },
          operation.current.createKey,
        );
        sessionId = created.session.id;
        operation.current.sessionId = sessionId;
        setCreatedSessionId(sessionId);
        invalidateSessionListReadModels();
      }

      for (const binding of frozenBindings) {
        const identity = bindingIdentity(binding);
        let idempotencyKey = operation.current.bindingKeys.get(identity);
        if (!idempotencyKey) {
          idempotencyKey = createIdempotencyKey("session-binding");
          operation.current.bindingKeys.set(identity, idempotencyKey);
        }
        await sessionClient.addBinding(
          sessionId,
          {
            ...createOperatorCommand("Assigned selected validated telemetry point from wizard"),
            node_id: binding.node_id,
            equipment_id: binding.equipment_id,
            channel_id: binding.channel_id,
            metric: binding.metric,
            unit: binding.unit,
            binding_metadata: {
              source: "nexolab-dashboard-wizard-v2",
              selection_mode: "telemetry-point-selector",
            },
          },
          idempotencyKey,
        );
      }

      await sessionClient.addLimitSet(
        sessionId,
        {
          ...createOperatorCommand("Created initial laboratory limit version from wizard"),
          limits: [
            {
              metric: "temperature.probe",
              unit: "degC",
              lower_limit: form.temperatureLower,
              upper_limit: form.temperatureUpper,
              hysteresis: form.temperatureHysteresis,
              duration_seconds: form.temperatureDurationSeconds,
              payload: { applies_to: ["106-03", "106-04"] },
            },
            {
              metric: "electrical.power.active",
              unit: "W",
              upper_limit: form.powerUpper,
              hysteresis: 50,
              duration_seconds: 30,
              payload: {
                applies_to: ["LE01MP-200", "LE01MP-201", "LE01MP-202", "LE01MP-203"],
              },
            },
          ],
        },
        operation.current.limitsKey,
      );

      router.push(`/sessions/${sessionId}`);
    } catch (nextError) {
      if (operation.current.selectionKeys) {
        setForm((current) => ({
          ...current,
          selectedTelemetryKeys: [...(operation.current.selectionKeys ?? current.selectedTelemetryKeys)],
        }));
      }
      setError(nextError instanceof Error ? nextError : new Error("Не вдалося створити сесію."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="panel h-fit p-4 xl:sticky xl:top-[98px]">
        <p className="px-2 text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">Creation wizard</p>
        <div className="mt-4 space-y-1">
          {WIZARD_STEPS.map((label, index) => {
            const completed = index < step;
            const active = index === step;
            return (
              <button
                key={label}
                onClick={() => index <= step && setStep(index)}
                disabled={index > step || submitting}
                className={`flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition ${
                  active
                    ? "border-blue-400/35 bg-blue-500/10 text-white"
                    : completed
                      ? "border-transparent text-emerald-300 hover:bg-white/[0.03]"
                      : "border-transparent text-slate-600"
                }`}
              >
                <span
                  className={`grid h-6 w-6 place-items-center rounded-full border text-[9px] ${
                    completed
                      ? "border-emerald-300/25 bg-emerald-400/10"
                      : "border-white/[0.08] bg-white/[0.025]"
                  }`}
                >
                  {completed ? <Check className="h-3.5 w-3.5" /> : index + 1}
                </span>
                <span className="text-[10px] font-semibold">{label}</span>
              </button>
            );
          })}
        </div>
        <div className="mt-5 rounded-2xl border border-cyan-300/10 bg-cyan-400/[0.035] p-4 text-[10px] leading-5 text-slate-400">
          <ShieldCheck className="mr-2 inline h-4 w-4 text-cyan-300" />
          Реальний draft і стабільні idempotency keys для повторної доставки.
        </div>
      </aside>

      <section className="panel min-h-[680px]">
        <div className="border-b border-white/[0.055] p-5 sm:p-6">
          <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">Крок {step + 1} з 8</p>
          <h1 className="mt-2 text-2xl font-semibold text-white">{WIZARD_STEPS[step]}</h1>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            Конфігурація версіонується, а під час start фіксується immutable snapshot.
          </p>
        </div>

        <div className="p-5 sm:p-6">
          {step === 0 && <GeneralStep form={form} update={update} />}
          {step === 1 && <ObjectStep form={form} update={update} />}
          {step === 2 && <MethodStep form={form} update={update} />}
          {step === 3 && (
            <EquipmentStep
              form={form}
              update={update}
              hierarchy={selectionModel.hierarchy}
              eligibleCount={selectionModel.eligibleInventoryCount}
              selectionStatus={selectionStatus}
              selectionError={selectionError}
              onRetry={retrySelection}
            />
          )}
          {step === 4 && <SamplingStep form={form} update={update} />}
          {step === 5 && <LimitsStep form={form} update={update} />}
          {step === 6 && <StagesStep form={form} update={update} />}
          {step === 7 && <ReviewStep form={form} />}

          {error && (
            <div className="mt-5 rounded-2xl border border-red-300/15 bg-red-400/[0.045] p-4">
              <p className="text-[10px] font-semibold text-red-200">Операцію не завершено</p>
              <p className="mt-1 text-[10px] leading-5 text-slate-400">{error.message}</p>
              {createdSessionId && (
                <p className="mt-2 font-mono text-[9px] text-cyan-300">
                  Draft {createdSessionId} уже існує; повтор використає ті самі ключі та початковий telemetry selection.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/[0.055] p-5 sm:p-6">
          <button
            className="secondary-button gap-2"
            disabled={step === 0 || submitting}
            onClick={() => setStep((value) => Math.max(0, value - 1))}
          >
            <ArrowLeft className="h-4 w-4" />
            Назад
          </button>
          {step < WIZARD_STEPS.length - 1 ? (
            <button
              className="primary-button gap-2 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!stepValid || submitting}
              onClick={() => setStep((value) => Math.min(WIZARD_STEPS.length - 1, value + 1))}
            >
              Далі
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              className="primary-button gap-2 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={submitting || selectedKeyCount === 0}
              onClick={() => void submit()}
            >
              {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {createdSessionId ? "Повторити без дублювання" : "Створити реальний draft"}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
