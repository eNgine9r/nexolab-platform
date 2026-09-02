"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  Cable,
  Check,
  ClipboardCheck,
  Cpu,
  LoaderCircle,
  RadioTower,
  Save,
  ShieldCheck,
  Unplug,
} from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import type { RefrigerationEquipment } from "@/data/refrigeration";
import {
  CommissioningRepositoryError,
  createCommissioningIdempotencyKey,
  type CommissioningPreflightAttempt,
  type CommissioningRepository,
  type CommissioningSession,
  type CommissioningSessionWrite,
  type SupportedDeviceProfile,
} from "@/features/equipment/commissioning-repository";
import { createEquipmentRegistryRuntime } from "@/features/equipment/runtime";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";

const steps = [
  { label: "Пристрій", icon: Cpu },
  { label: "Підключення", icon: Cable },
  { label: "Профіль", icon: RadioTower },
  { label: "Прив'язка до обладнання", icon: Unplug },
  { label: "Перевірка чернетки", icon: ClipboardCheck },
] as const;

const emptyDraft: CommissioningSessionWrite = {
  deviceClass: "temperature-controller",
  manufacturer: "",
  model: "",
  profileId: null,
  nodeId: null,
  busId: null,
  stableTransportIdentifier: null,
  unitId: null,
  ipAddress: null,
  targetEquipmentKey: null,
};

export function CommissioningWizardScreen({ commissioningId }: { commissioningId: string | null }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [profiles, setProfiles] = useState<SupportedDeviceProfile[]>([]);
  const [equipment, setEquipment] = useState<RefrigerationEquipment[]>([]);
  const [session, setSession] = useState<CommissioningSession | null>(null);
  const [loadedRepository, setLoadedRepository] = useState<CommissioningRepository | null>(null);
  const [draft, setDraft] = useState<CommissioningSessionWrite>(emptyDraft);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<CommissioningPreflightAttempt | null>(null);
  const [preflightLoadKey, setPreflightLoadKey] = useState<string | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const idempotencyKey = useRef<string | null>(null);
  const preflightIdempotencyKey = useRef<string | null>(null);
  const organizationId = security.membership?.organizationId ?? null;
  const runtime = useMemo(
    () => createEquipmentRegistryRuntime({ organizationId: organizationId ?? undefined }),
    [organizationId],
  );
  const repository = runtime.commissioningRepository;
  const activeRepository = useRef(repository);
  const canManage = security.membership?.permissions.includes("equipment.manage") ?? false;

  useLayoutEffect(() => {
    activeRepository.current = repository;
  }, [repository]);

  useEffect(() => {
    if (security.state !== "ready" || !organizationId || !repository || !runtime.equipmentRepository) return;
    const controller = new AbortController();
    const target = normalize(searchParams.get("target"));
    void Promise.all([
      repository.listProfiles(controller.signal),
      runtime.equipmentRepository.list(),
      commissioningId ? repository.getSession(commissioningId, controller.signal) : Promise.resolve(null),
    ])
      .then(([loadedProfiles, loadedEquipment, loadedSession]) => {
        if (controller.signal.aborted) return;
        setProfiles(loadedProfiles);
        setEquipment(loadedEquipment.filter((item) => item.lifecycleStatus !== "retired"));
        setSession(loadedSession);
        if (loadedSession) {
          setDraft(sessionToWrite(loadedSession));
        } else {
          setDraft({ ...emptyDraft, targetEquipmentKey: target });
          idempotencyKey.current = null;
        }
        setStep(0);
        setError(null);
        setLoadedRepository(repository);
        setLoadState("ready");
        setBusy(false);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setProfiles([]);
        setEquipment([]);
        setSession(null);
        setDraft(emptyDraft);
        setLoadedRepository(repository);
        setLoadState("error");
        setBusy(false);
        setError(message(cause));
      });
    return () => controller.abort();
  }, [
    commissioningId,
    organizationId,
    repository,
    runtime.equipmentRepository,
    searchParams,
    security.state,
  ]);

  useEffect(() => {
    if (security.state !== "ready" || !organizationId || !repository || !commissioningId) return;
    const controller = new AbortController();
    const operationRepository = repository;
    const loadKey = `${organizationId}:${commissioningId}`;
    void repository
      .getLatestPreflight(commissioningId, controller.signal)
      .then((attempt) => {
        if (!controller.signal.aborted && activeRepository.current === operationRepository) {
          setPreflight(attempt);
          setPreflightError(null);
          setPreflightLoadKey(loadKey);
        }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || activeRepository.current !== operationRepository) return;
        setPreflight(null);
        setPreflightError(
          cause instanceof CommissioningRepositoryError && cause.status === 404 ? null : message(cause),
        );
        setPreflightLoadKey(loadKey);
      });
    return () => controller.abort();
  }, [commissioningId, organizationId, repository, security.state]);

  if (
    security.state === "loading" ||
    security.state === "unauthenticated" ||
    security.state === "forbidden" ||
    security.state === "error"
  ) {
    return (
      <SecurityGate
        state={security.state}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  }

  if (security.mode === "demo" || !security.membership) {
    return <Unavailable message="Комісіонування доступне лише в authenticated LOCAL_LAN live mode." />;
  }

  if (!repository || !runtime.equipmentRepository) {
    return (
      <Unavailable message={runtime.error ?? "Локальний API чернеток комісіонування не налаштований."} />
    );
  }

  const loadIsCurrent = loadedRepository === repository;
  const visibleLoadState = loadIsCurrent ? loadState : "loading";
  const visibleSession = loadIsCurrent ? session : null;
  const cancelled = visibleSession?.lifecycle === "cancelled";
  const currentPreflightLoadKey =
    visibleSession && organizationId ? `${organizationId}:${visibleSession.id}` : null;
  const visiblePreflight = preflightLoadKey === currentPreflightLoadKey ? preflight : null;
  const visiblePreflightError = preflightLoadKey === currentPreflightLoadKey ? preflightError : null;

  const selectProfile = (profileId: string) => {
    if (profileId === "unsupported") {
      setDraft((current) => ({ ...current, profileId: null, manufacturer: "", model: "" }));
      return;
    }
    const profile = profiles.find((item) => item.id === profileId);
    if (!profile) return;
    setDraft((current) => ({
      ...current,
      profileId: profile.id,
      deviceClass: profile.deviceClass,
      manufacturer: profile.manufacturer,
      model: profile.models[0] ?? "",
    }));
  };

  const save = async () => {
    if (cancelled || !canManage) return;
    if (!draft.deviceClass.trim() || !draft.manufacturer.trim() || !draft.model.trim()) {
      setError("Вкажіть клас, виробника і модель пристрою.");
      setStep(0);
      return;
    }
    setBusy(true);
    setError(null);
    const operationRepository = repository;
    try {
      const saved = visibleSession
        ? await repository.updateSession(visibleSession.id, normalizedDraft(draft), visibleSession.version)
        : await repository.createSession(normalizedDraft(draft), ensureIdempotencyKey(idempotencyKey));
      if (activeRepository.current !== operationRepository) return;
      setSession(saved);
      setDraft(sessionToWrite(saved));
      if (!commissioningId) router.replace(`/equipment/onboarding/${encodeURIComponent(saved.id)}`);
    } catch (cause: unknown) {
      if (activeRepository.current !== operationRepository) return;
      setError(message(cause));
    } finally {
      if (activeRepository.current === operationRepository) setBusy(false);
    }
  };

  const cancel = async () => {
    if (!visibleSession || cancelled || !canManage) return;
    setBusy(true);
    setError(null);
    const operationRepository = repository;
    try {
      const saved = await repository.cancelSession(visibleSession.id, visibleSession.version);
      if (activeRepository.current !== operationRepository) return;
      setSession(saved);
      setDraft(sessionToWrite(saved));
    } catch (cause: unknown) {
      if (activeRepository.current !== operationRepository) return;
      setError(message(cause));
    } finally {
      if (activeRepository.current === operationRepository) setBusy(false);
    }
  };

  const runPreflight = async () => {
    if (!visibleSession || visibleSession.lifecycle !== "ready_for_preflight" || !canManage) return;
    setPreflightBusy(true);
    setPreflightError(null);
    const operationRepository = repository;
    try {
      const result = await repository.runPreflight(
        visibleSession.id,
        visibleSession.version,
        ensureIdempotencyKey(preflightIdempotencyKey),
      );
      if (activeRepository.current !== operationRepository) return;
      setPreflight(result);
      setPreflightLoadKey(`${organizationId}:${visibleSession.id}`);
      preflightIdempotencyKey.current = null;
    } catch (cause: unknown) {
      if (activeRepository.current !== operationRepository) return;
      setPreflightError(message(cause));
    } finally {
      if (activeRepository.current === operationRepository) setPreflightBusy(false);
    }
  };

  const selectedProfile = profiles.find((profile) => profile.id === draft.profileId) ?? null;
  const selectedEquipment = equipment.find((item) => item.id === draft.targetEquipmentKey) ?? null;
  const unsupported =
    visibleSession?.lifecycle === "unsupported" || (!draft.profileId && draft.manufacturer !== "");

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Обладнання"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Чернетка підключення"
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => void security.signOut().then(() => router.replace("/login"))}
        />
        <main className="p-3 sm:p-4 xl:p-5">
          <div className="mx-auto max-w-[1900px]">
            <header className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-white/[0.07] bg-[#091a31]/85 p-3">
              <Link
                href="/equipment?section=connections"
                aria-label="Назад до підключень"
                className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 text-slate-400 hover:text-white focus:ring-2 focus:ring-cyan-300 focus:outline-none"
              >
                <ArrowLeft className="h-4 w-4" />
              </Link>
              <div className="min-w-0 flex-1">
                <p className="text-[9px] tracking-[0.16em] text-cyan-300 uppercase">Commissioning intent</p>
                <h1 className="truncate text-base font-semibold text-white sm:text-lg">
                  {visibleSession
                    ? `${visibleSession.manufacturer} ${visibleSession.model}`
                    : "Нова чернетка підключення"}
                </h1>
              </div>
              <span className="rounded-full border border-amber-400/20 bg-amber-400/[0.07] px-3 py-1 text-[10px] text-amber-100">
                Не активний acquisition target
              </span>
            </header>

            {visibleLoadState === "loading" ? (
              <div
                role="status"
                className="grid min-h-[420px] place-items-center rounded-3xl border border-white/[0.07] bg-[#08182e]/80 text-sm text-slate-400"
              >
                <span className="flex items-center gap-2">
                  <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> Завантаження чернетки…
                </span>
              </div>
            ) : null}
            {visibleLoadState === "error" ? <Unavailable message={error ?? "Чернетка недоступна."} /> : null}
            {visibleLoadState === "ready" ? (
              <div className="grid gap-4 xl:grid-cols-[250px_minmax(0,1fr)_330px]">
                <aside className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-3 xl:sticky xl:top-24 xl:self-start">
                  <p className="px-2 pb-2 text-[9px] tracking-[0.16em] text-slate-500 uppercase">
                    Етапи чернетки
                  </p>
                  <nav aria-label="Етапи комісіонування" className="space-y-1">
                    {steps.map((item, index) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.label}
                          type="button"
                          aria-current={step === index ? "step" : undefined}
                          onClick={() => setStep(index)}
                          className={`flex min-h-11 w-full items-center gap-3 rounded-xl border px-3 text-left text-xs transition focus:ring-2 focus:ring-cyan-300 focus:outline-none ${step === index ? "border-cyan-300/20 bg-cyan-400/10 text-cyan-100" : "border-transparent text-slate-500 hover:bg-white/[0.035] hover:text-slate-200"}`}
                        >
                          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg border border-white/[0.08] text-[9px]">
                            {index + 1}
                          </span>
                          <Icon className="h-4 w-4 shrink-0" /> {item.label}
                        </button>
                      );
                    })}
                  </nav>
                </aside>

                <section className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-4 sm:p-6">
                  {cancelled ? (
                    <div
                      role="status"
                      className="mb-5 flex items-start gap-2 rounded-xl border border-slate-400/20 bg-slate-400/[0.06] p-3 text-sm text-slate-300"
                    >
                      <Ban className="mt-0.5 h-4 w-4 shrink-0" /> Чернетку скасовано. Вона збережена для
                      аудиту та доступна лише для перегляду.
                    </div>
                  ) : null}
                  {error ? (
                    <div
                      role="alert"
                      className="mb-5 flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-400/[0.06] p-3 text-sm text-rose-200"
                    >
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
                    </div>
                  ) : null}
                  <WizardStep
                    step={step}
                    draft={draft}
                    setDraft={setDraft}
                    profiles={profiles}
                    equipment={equipment}
                    selectedProfile={selectedProfile}
                    selectedEquipment={selectedEquipment}
                    unsupported={unsupported}
                    disabled={cancelled || busy || !canManage}
                    onSelectProfile={selectProfile}
                  />

                  {visibleSession ? (
                    <PreflightPanel
                      session={visibleSession}
                      attempt={visiblePreflight}
                      busy={preflightBusy}
                      error={visiblePreflightError}
                      canManage={canManage}
                      onRun={() => void runPreflight()}
                    />
                  ) : null}

                  <div className="mt-7 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] pt-5">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={step === 0}
                        onClick={() => setStep((value) => Math.max(0, value - 1))}
                        className={secondaryButton}
                      >
                        Назад
                      </button>
                      <button
                        type="button"
                        disabled={step === steps.length - 1}
                        onClick={() => setStep((value) => Math.min(steps.length - 1, value + 1))}
                        className={secondaryButton}
                      >
                        Далі
                      </button>
                    </div>
                    <div className="flex gap-2">
                      {visibleSession && !cancelled && canManage ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void cancel()}
                          className="rounded-xl border border-rose-400/20 px-4 py-2 text-xs text-rose-200 hover:bg-rose-400/[0.07] disabled:opacity-50"
                        >
                          Скасувати чернетку
                        </button>
                      ) : null}
                      {!cancelled && canManage ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void save()}
                          className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
                        >
                          <Save className="h-4 w-4" /> {busy ? "Збереження…" : "Зберегти чернетку"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                </section>

                <CommissioningSummary
                  session={visibleSession}
                  draft={draft}
                  profile={selectedProfile}
                  equipment={selectedEquipment}
                  unsupported={unsupported}
                  preflight={visiblePreflight}
                />
              </div>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}

function WizardStep({
  step,
  draft,
  setDraft,
  profiles,
  equipment,
  selectedProfile,
  selectedEquipment,
  unsupported,
  disabled,
  onSelectProfile,
}: {
  step: number;
  draft: CommissioningSessionWrite;
  setDraft: React.Dispatch<React.SetStateAction<CommissioningSessionWrite>>;
  profiles: SupportedDeviceProfile[];
  equipment: RefrigerationEquipment[];
  selectedProfile: SupportedDeviceProfile | null;
  selectedEquipment: RefrigerationEquipment | null;
  unsupported: boolean;
  disabled: boolean;
  onSelectProfile: (profileId: string) => void;
}) {
  if (step === 0)
    return (
      <DeviceStep
        draft={draft}
        setDraft={setDraft}
        profiles={profiles}
        disabled={disabled}
        onSelectProfile={onSelectProfile}
      />
    );
  if (step === 1) return <ConnectionStep draft={draft} setDraft={setDraft} disabled={disabled} />;
  if (step === 2) return <ProfileStep profile={selectedProfile} unsupported={unsupported} />;
  if (step === 3)
    return <BindingStep draft={draft} setDraft={setDraft} equipment={equipment} disabled={disabled} />;
  return (
    <ReviewStep
      draft={draft}
      profile={selectedProfile}
      equipment={selectedEquipment}
      unsupported={unsupported}
    />
  );
}

function DeviceStep({
  draft,
  setDraft,
  profiles,
  disabled,
  onSelectProfile,
}: {
  draft: CommissioningSessionWrite;
  setDraft: React.Dispatch<React.SetStateAction<CommissioningSessionWrite>>;
  profiles: SupportedDeviceProfile[];
  disabled: boolean;
  onSelectProfile: (profileId: string) => void;
}) {
  const custom = !draft.profileId;
  return (
    <StepFrame
      eyebrow="Крок 1"
      title="Ідентифікуйте пристрій"
      description="Оберіть лише репозиторно підтримувану сім’ю або збережіть невідому модель як unsupported."
    >
      <label className={labelClass}>
        Підтримуваний профіль
        <select
          disabled={disabled}
          value={draft.profileId ?? (draft.manufacturer ? "unsupported" : "")}
          onChange={(event) => onSelectProfile(event.target.value)}
          className={inputClass}
        >
          <option value="">Оберіть пристрій</option>
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.displayName}
            </option>
          ))}
          <option value="unsupported">Інша / невідома модель</option>
        </select>
      </label>
      {custom ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className={labelClass}>
            Виробник
            <input
              disabled={disabled}
              value={draft.manufacturer}
              onChange={(event) => setDraft((current) => ({ ...current, manufacturer: event.target.value }))}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            Модель
            <input
              disabled={disabled}
              value={draft.model}
              onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            Клас пристрою
            <input
              disabled={disabled}
              value={draft.deviceClass}
              onChange={(event) => setDraft((current) => ({ ...current, deviceClass: event.target.value }))}
              className={inputClass}
            />
          </label>
        </div>
      ) : null}
    </StepFrame>
  );
}

function ConnectionStep({
  draft,
  setDraft,
  disabled,
}: {
  draft: CommissioningSessionWrite;
  setDraft: React.Dispatch<React.SetStateAction<CommissioningSessionWrite>>;
  disabled: boolean;
}) {
  const field = (key: keyof CommissioningSessionWrite, value: string | number | null) =>
    setDraft((current) => ({ ...current, [key]: value }));
  return (
    <StepFrame
      eyebrow="Крок 2"
      title="Намір підключення"
      description="Ці поля описують майбутнє підключення. До запуску безпечного preflight жодна адреса не опитується."
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={labelClass}>
          Node intent
          <input
            disabled={disabled}
            value={draft.nodeId ?? ""}
            onChange={(event) => field("nodeId", normalize(event.target.value))}
            placeholder="edge-01"
            className={inputClass}
          />
        </label>
        <label className={labelClass}>
          Bus intent
          <input
            disabled={disabled}
            value={draft.busId ?? ""}
            onChange={(event) => field("busId", normalize(event.target.value))}
            placeholder="rs485-main"
            className={inputClass}
          />
        </label>
        <label className={`${labelClass} sm:col-span-2`}>
          Стабільний transport identity
          <input
            disabled={disabled}
            value={draft.stableTransportIdentifier ?? ""}
            onChange={(event) => field("stableTransportIdentifier", normalize(event.target.value))}
            placeholder="/dev/serial/by-id/..."
            className={inputClass}
          />
        </label>
        <label className={labelClass}>
          Modbus Unit ID
          <input
            disabled={disabled}
            type="number"
            min={1}
            max={247}
            value={draft.unitId ?? ""}
            onChange={(event) => field("unitId", event.target.value ? Number(event.target.value) : null)}
            className={inputClass}
          />
        </label>
      </div>
      <p className="mt-4 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.035] p-3 text-xs leading-5 text-slate-400">
        Редагування наміру не виконує Modbus read/write, не сканує Unit ID і не змінює Device Agent.
      </p>
    </StepFrame>
  );
}

function ProfileStep({
  profile,
  unsupported,
}: {
  profile: SupportedDeviceProfile | null;
  unsupported: boolean;
}) {
  return (
    <StepFrame
      eyebrow="Крок 3"
      title="Профіль можливостей"
      description="Каталог походить з уже наявних read-only acquisition contracts."
    >
      {profile ? (
        <div className="rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.04] p-4">
          <div className="flex items-center gap-2">
            <Check className="h-4 w-4 text-emerald-300" />
            <h3 className="font-semibold text-white">{profile.displayName}</h3>
          </div>
          <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
            <SummaryRow label="Profile ID" value={profile.id} />
            <SummaryRow label="Версія" value={profile.version} />
            <SummaryRow label="Transport" value="Modbus RTU" />
            <SummaryRow label="Capability" value={profile.capabilityStatus} />
          </dl>
          <p className="mt-4 text-xs leading-5 text-slate-400">{profile.evidenceNote}</p>
        </div>
      ) : (
        <div className="rounded-2xl border border-rose-400/20 bg-rose-400/[0.05] p-4 text-sm text-rose-100">
          <p className="font-semibold">Unsupported / Profile required</p>
          <p className="mt-2 text-xs leading-5 text-rose-100/70">
            Невідома модель може залишитися чернеткою, але не переходить до preflight чи activation.
          </p>
        </div>
      )}
      {unsupported && profile ? null : null}
    </StepFrame>
  );
}

function BindingStep({
  draft,
  setDraft,
  equipment,
  disabled,
}: {
  draft: CommissioningSessionWrite;
  setDraft: React.Dispatch<React.SetStateAction<CommissioningSessionWrite>>;
  equipment: RefrigerationEquipment[];
  disabled: boolean;
}) {
  return (
    <StepFrame
      eyebrow="Крок 4"
      title="Прив'язка до обладнання"
      description="Оберіть актив, для якого створюється намір підключення контролера."
    >
      <label className={labelClass}>
        Цільове обладнання
        <select
          disabled={disabled}
          value={draft.targetEquipmentKey ?? ""}
          onChange={(event) =>
            setDraft((current) => ({ ...current, targetEquipmentKey: normalize(event.target.value) }))
          }
          className={inputClass}
        >
          <option value="">Не вибрано</option>
          {equipment.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.code}
            </option>
          ))}
        </select>
      </label>
    </StepFrame>
  );
}

function ReviewStep({
  draft,
  profile,
  equipment,
  unsupported,
}: {
  draft: CommissioningSessionWrite;
  profile: SupportedDeviceProfile | null;
  equipment: RefrigerationEquipment | null;
  unsupported: boolean;
}) {
  return (
    <StepFrame
      eyebrow="Крок 5"
      title="Перевірка чернетки"
      description="Перевірте намір перед збереженням і запустіть bounded read-only preflight після готовності чернетки."
    >
      <dl className="grid gap-3 sm:grid-cols-2">
        <SummaryRow label="Пристрій" value={`${draft.manufacturer || "—"} ${draft.model || ""}`} />
        <SummaryRow label="Профіль" value={profile?.displayName ?? "Unsupported / Profile required"} />
        <SummaryRow label="Node / bus" value={`${draft.nodeId ?? "—"} / ${draft.busId ?? "—"}`} />
        <SummaryRow label="Unit ID" value={draft.unitId?.toString() ?? "—"} />
        <SummaryRow label="Stable identity" value={draft.stableTransportIdentifier ?? "—"} />
        <SummaryRow label="Цільове обладнання" value={equipment?.name ?? "Не вибрано"} />
      </dl>
      <div
        className={`mt-5 rounded-xl border p-3 text-xs leading-5 ${unsupported ? "border-rose-400/20 bg-rose-400/[0.05] text-rose-100" : "border-amber-400/20 bg-amber-400/[0.05] text-amber-100"}`}
      >
        {unsupported
          ? "Чернетка буде fail-closed як unsupported і не зможе перейти до preflight."
          : "Збереження створює лише commissioning intent. Воно не активує опитування."}
      </div>
    </StepFrame>
  );
}

function PreflightPanel({
  session,
  attempt,
  busy,
  error,
  canManage,
  onRun,
}: {
  session: CommissioningSession;
  attempt: CommissioningPreflightAttempt | null;
  busy: boolean;
  error: string | null;
  canManage: boolean;
  onRun: () => void;
}) {
  const ready = session.lifecycle === "ready_for_preflight";
  const stale = attempt !== null && attempt.sessionVersion !== session.version;
  const evidence = attempt?.evidence ?? null;
  return (
    <section className="mt-7 rounded-2xl border border-cyan-300/10 bg-cyan-400/[0.025] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[9px] tracking-[0.16em] text-cyan-300 uppercase">Safe preflight</p>
          <h3 className="mt-1 flex items-center gap-2 font-semibold text-white">
            <ShieldCheck className="h-4 w-4 text-cyan-300" /> Read-only перевірка підключення
          </h3>
          <p className="mt-2 max-w-2xl text-xs leading-5 text-slate-400">
            Exact node / bus / stable adapter / Unit ID / profile. Дозволений лише repository-owned FC03 read
            path.
          </p>
        </div>
        <button
          type="button"
          disabled={!ready || busy || !canManage}
          onClick={onRun}
          className="rounded-xl bg-cyan-400 px-4 py-2 text-xs font-semibold text-[#04111f] hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Безпечна перевірка…" : "Запустити безпечну перевірку"}
        </button>
      </div>
      {!ready ? (
        <p className="mt-3 rounded-xl border border-amber-400/15 bg-amber-400/[0.04] p-3 text-xs text-amber-100">
          Спочатку збережіть повний supported commissioning intent у стані ready_for_preflight.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-xs text-rose-200">
          {error}
        </p>
      ) : null}
      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
        <EvidenceStatus
          label="software verified"
          state="passed"
          detail="Fixed repository-owned FC03-only contract; write fields are not representable."
        />
        <EvidenceStatus
          label={attempt ? evidenceLabel(attempt.evidenceLevel) : "hardware unverified"}
          state={attempt?.result === "passed" && !stale ? "passed" : "neutral"}
          detail={
            stale
              ? "Evidence belongs to an older commissioning version."
              : (attempt?.code ?? "Live preflight has not completed.")
          }
        />
        <EvidenceStatus
          label="Modbus writes"
          state={evidence?.modbusWrites === "none" ? "passed" : "neutral"}
          detail={evidence?.modbusWrites === "none" ? "none" : "No persisted live evidence yet"}
        />
        <EvidenceStatus
          label="Hardware writes"
          state={evidence?.hardwareWrites === "none" ? "passed" : "neutral"}
          detail={evidence?.hardwareWrites === "none" ? "none" : "No persisted live evidence yet"}
        />
      </div>
      {evidence?.checks.length ? (
        <div className="mt-4 space-y-2">
          {evidence.checks.map((check) => (
            <EvidenceStatus
              key={check.key}
              label={check.key.replaceAll("_", " ")}
              state={check.state}
              detail={check.detail}
            />
          ))}
        </div>
      ) : null}
      {evidence?.observations.length ? (
        <div className="mt-4 rounded-xl border border-white/[0.06] p-3">
          <p className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">Observed semantics</p>
          <div className="mt-2 space-y-1 text-xs text-slate-300">
            {evidence.observations.map((item) => (
              <p key={item.key}>
                {item.key}: {item.semantic ?? "unverified engineering value"} · {item.quality}
              </p>
            ))}
          </div>
        </div>
      ) : null}
      {evidence?.warnings.length ? (
        <ul className="mt-4 space-y-1 text-xs leading-5 text-amber-100/80">
          {evidence.warnings.map((warning) => (
            <li key={warning}>• {warning}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function EvidenceStatus({
  label,
  state,
  detail,
}: {
  label: string;
  state: "passed" | "failed" | "neutral";
  detail: string;
}) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-white/[0.06] bg-[#06142a]/55 p-3">
      {state === "passed" ? (
        <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
      ) : (
        <AlertTriangle
          className={`mt-0.5 h-4 w-4 shrink-0 ${state === "failed" ? "text-rose-300" : "text-slate-500"}`}
        />
      )}
      <div>
        <p className="font-medium text-slate-200">{label}</p>
        <p className="mt-1 leading-5 text-slate-500">{detail}</p>
      </div>
    </div>
  );
}

function evidenceLabel(level: CommissioningPreflightAttempt["evidenceLevel"]): string {
  if (level === "hardware_verified") return "hardware verified";
  if (level === "partially_verified") return "partially verified";
  if (level === "unsupported") return "unsupported";
  if (level === "unverified") return "unverified";
  return "hardware unverified";
}

function StepFrame({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-[9px] tracking-[0.18em] text-cyan-300 uppercase">{eyebrow}</p>
      <h2 className="mt-2 text-xl font-semibold text-white">{title}</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">{description}</p>
      <div className="mt-6 space-y-4">{children}</div>
    </div>
  );
}

function CommissioningSummary({
  session,
  draft,
  profile,
  equipment,
  unsupported,
  preflight,
}: {
  session: CommissioningSession | null;
  draft: CommissioningSessionWrite;
  profile: SupportedDeviceProfile | null;
  equipment: RefrigerationEquipment | null;
  unsupported: boolean;
  preflight: CommissioningPreflightAttempt | null;
}) {
  return (
    <aside className="rounded-3xl border border-white/[0.07] bg-[#08182e]/80 p-4 xl:sticky xl:top-24 xl:self-start">
      <p className="text-[9px] tracking-[0.16em] text-cyan-300 uppercase">Live summary</p>
      <h2 className="mt-2 font-semibold text-white">Чернетка комісіонування</h2>
      <dl className="mt-5 space-y-3">
        <SummaryRow
          label="Lifecycle"
          value={session?.lifecycle ?? (unsupported ? "unsupported after save" : "not saved")}
        />
        <SummaryRow label="Пристрій" value={`${draft.manufacturer || "—"} ${draft.model || ""}`} />
        <SummaryRow label="Профіль" value={profile?.displayName ?? "Profile required"} />
        <SummaryRow label="Connection" value={`${draft.nodeId ?? "—"} · ${draft.busId ?? "—"}`} />
        <SummaryRow label="Binding" value={equipment?.name ?? "Не вибрано"} />
        <SummaryRow label="Версія" value={session ? String(session.version) : "—"} />
      </dl>
      <div className="mt-5 rounded-xl border border-amber-400/15 bg-amber-400/[0.04] p-3 text-[10px] leading-4 text-amber-100/80">
        Hardware verification: {preflight ? evidenceLabel(preflight.evidenceLevel) : "не виконувалась"}
        <br />
        Acquisition activation: не виконувалась
        <br />
        Modbus writes: відсутні
      </div>
    </aside>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-b border-white/[0.06] pb-2">
      <dt className="text-[9px] tracking-[0.1em] text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 text-xs font-medium break-words text-slate-200">{value}</dd>
    </div>
  );
}

function Unavailable({ message: value }: { message: string }) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="max-w-lg rounded-3xl border border-rose-400/15 bg-[#091a31] p-6">
        <AlertTriangle className="h-6 w-6 text-rose-300" />
        <h1 className="mt-3 text-lg font-semibold">Комісіонування недоступне</h1>
        <p className="mt-2 text-sm leading-6 text-slate-400">{value}</p>
        <Link href="/equipment?section=connections" className="mt-5 inline-block text-sm text-cyan-300">
          До підключень
        </Link>
      </section>
    </main>
  );
}

function sessionToWrite(session: CommissioningSession): CommissioningSessionWrite {
  return {
    deviceClass: session.deviceClass,
    manufacturer: session.manufacturer,
    model: session.model,
    profileId: session.profileId,
    nodeId: session.nodeId,
    busId: session.busId,
    stableTransportIdentifier: session.stableTransportIdentifier,
    unitId: session.unitId,
    ipAddress: session.ipAddress,
    targetEquipmentKey: session.targetEquipmentKey,
  };
}
function normalizedDraft(draft: CommissioningSessionWrite): CommissioningSessionWrite {
  return {
    ...draft,
    deviceClass: draft.deviceClass.trim(),
    manufacturer: draft.manufacturer.trim(),
    model: draft.model.trim(),
    profileId: normalize(draft.profileId),
    nodeId: normalize(draft.nodeId),
    busId: normalize(draft.busId),
    stableTransportIdentifier: normalize(draft.stableTransportIdentifier),
    ipAddress: normalize(draft.ipAddress),
    targetEquipmentKey: normalize(draft.targetEquipmentKey),
  };
}
function normalize(value: string | null): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}
function ensureIdempotencyKey(ref: React.MutableRefObject<string | null>): string {
  ref.current ??= createCommissioningIdempotencyKey();
  return ref.current;
}
function message(cause: unknown): string {
  if (
    cause instanceof CommissioningRepositoryError &&
    cause.code === "commissioning_session_version_conflict"
  )
    return "Чернетку вже змінено в іншій вкладці. Поверніться до списку та відкрийте актуальну версію.";
  return cause instanceof Error ? cause.message : "Операцію з чернеткою не виконано.";
}

const labelClass = "grid gap-1.5 text-xs font-medium text-slate-300";
const inputClass =
  "min-h-11 w-full rounded-xl border border-white/[0.09] bg-[#06142a]/80 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-60";
const secondaryButton =
  "rounded-xl border border-white/[0.09] px-4 py-2 text-xs text-slate-300 hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-40";
