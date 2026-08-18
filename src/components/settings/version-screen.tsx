"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle2,
  Download,
  History,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { Topbar } from "@/components/dashboard/topbar";
import { VersionOperationProgress } from "@/components/settings/version-operation-progress";
import {
  RuntimeCredentialUnavailableError,
  createAuthenticatedFetch,
  createRuntimeCredentialProvider,
} from "@/features/security/supabase-auth";
import { versionConfirmationPhrase } from "@/features/settings/version-confirmation";
import {
  VersionManagementApiError,
  VersionManagementClient,
  type VersionAction,
  type VersionCatalogItem,
  type VersionSnapshot,
} from "@/features/settings/version-management";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 3000;

export function VersionScreen() {
  const [snapshot, setSnapshot] = useState<VersionSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [policyBusy, setPolicyBusy] = useState(false);
  const [checkBusy, setCheckBusy] = useState(false);
  const [selectedBundleId, setSelectedBundleId] = useState<string | null>(null);
  const [action, setAction] = useState<VersionAction>("update");
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  const client = useMemo(() => {
    const config = getTelemetryRuntimeConfig();
    if (config.mode !== "live") return null;
    try {
      const credentials = createRuntimeCredentialProvider();
      return new VersionManagementClient(
        config.apiBaseUrl,
        createAuthenticatedFetch(fetch.bind(globalThis), credentials),
      );
    } catch {
      return null;
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!client) {
      setLoading(false);
      setError("Version Management доступний лише в локальному live runtime.");
      return;
    }
    try {
      const next = await client.read();
      setSnapshot(next);
      setError(null);
    } catch (refreshError) {
      setError(describeError(refreshError));
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!snapshot?.activeOperation) return;
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, snapshot?.activeOperation]);

  const current = snapshot?.current ?? null;
  const selected = snapshot?.catalog.find((item) => item.bundleId === selectedBundleId) ?? null;
  const availableTargets = useMemo(
    () => snapshot?.catalog.filter((item) => !current || item.bundleId !== current.bundleId) ?? [],
    [current, snapshot?.catalog],
  );
  const updateCheck = snapshot?.updateCheck ?? null;
  const automaticUpdatesEnabled = snapshot?.updatePolicy.automaticUpdatesEnabled ?? false;
  const updateCandidate = useMemo(
    () =>
      updateCheck?.candidateBundleId
        ? (snapshot?.catalog.find((item) => item.bundleId === updateCheck.candidateBundleId) ?? null)
        : null,
    [snapshot?.catalog, updateCheck?.candidateBundleId],
  );

  useEffect(() => {
    if (updateCandidate && updateCheck?.activationEligible) {
      setSelectedBundleId(updateCandidate.bundleId);
      setAction("update");
    }
  }, [updateCandidate, updateCheck?.activationEligible]);

  async function changeAutomaticUpdates(enabled: boolean) {
    if (!client || policyBusy) return;
    setPolicyBusy(true);
    setError(null);
    try {
      await client.setAutomaticUpdates(enabled);
      await refresh();
    } catch (policyError) {
      setError(describeError(policyError));
      await refresh();
    } finally {
      setPolicyBusy(false);
    }
  }

  async function checkForUpdates() {
    if (!client || checkBusy) return;
    setCheckBusy(true);
    setError(null);
    try {
      await client.requestUpdateCheck("operator requested GitHub update discovery");
      await refresh();
    } catch (checkError) {
      setError(describeError(checkError));
    } finally {
      setCheckBusy(false);
    }
  }

  async function submitAction() {
    if (!client || !selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      await client.requestAction({
        action,
        targetBundleId: selected.bundleId,
        confirmation,
        reason,
      });
      setShowConfirm(false);
      setConfirmation("");
      setReason("");
      await refresh();
    } catch (submitError) {
      setError(describeError(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#040c18] text-slate-100">
      <Topbar />
      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 lg:px-6">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium tracking-[.2em] text-cyan-300 uppercase">
              NEXOLAB Security / Local version control
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">Версія системи</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Локальний контроль версій працює тільки через попередньо перевірені offline-пакети. GitHub
              використовується лише як необов’язковий update-plane для виявлення новішої GREEN ревізії;
              браузер не виконує shell-команди і не отримує GitHub credentials.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-cyan-300/25 bg-cyan-300/8 px-3 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/12 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin motion-reduce:animate-none")} />
            Оновити стан
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-rose-400/25 bg-rose-400/8 px-4 py-3 text-sm text-rose-100">
            {error}
          </div>
        ) : null}

        {loading && !snapshot ? (
          <div className="rounded-2xl border border-white/10 bg-[#071426]/90 p-6 text-sm text-slate-400">
            Завантаження локального version state…
          </div>
        ) : (
          <div className="grid gap-4">
            <section className="grid gap-4 xl:grid-cols-[1.15fr_.85fr]">
              <div className="rounded-2xl border border-white/10 bg-[#071426]/90 p-5 shadow-[0_18px_60px_rgba(0,0,0,.28)]">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/8">
                    <PackageCheck className="h-5 w-5 text-cyan-200" />
                  </div>
                  <div>
                    <p className="text-xs tracking-[.18em] text-slate-500 uppercase">Current package</p>
                    <h2 className="text-lg font-semibold">Поточна версія</h2>
                  </div>
                </div>
                {current ? (
                  <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    <Fact label="Release" value={current.release} />
                    <Fact label="Bundle" value={current.bundleId} mono />
                    <Fact
                      label="Commit"
                      value={shortCommit(current.sourceCommit)}
                      mono
                      title={current.sourceCommit}
                    />
                    <Fact label="Schema" value={current.schemaHead} mono />
                    <Fact label="Platform" value={current.platform} />
                    <Fact label="Runtime" value={current.runtimeMode} />
                    <Fact label="Health" value={current.health} />
                    <Fact label="Deployed" value={formatTime(current.deployedAt)} />
                    <Fact label="Packaged evidence" value={current.knownPackagedRelease ? "Так" : "Ні"} />
                  </div>
                ) : (
                  <div className="mt-5 rounded-xl border border-amber-300/20 bg-amber-300/5 px-4 py-4 text-sm text-amber-100">
                    Runtime не має canonical packaged version evidence. Оновлення та rollback заблоковані до
                    bootstrap/import останньої відомої версії.
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-white/10 bg-[#071426]/90 p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-300/20 bg-emerald-300/8">
                    <ShieldCheck className="h-5 w-5 text-emerald-200" />
                  </div>
                  <div>
                    <p className="text-xs tracking-[.18em] text-slate-500 uppercase">Safety boundary</p>
                    <h2 className="text-lg font-semibold">Що перевіряється до активації</h2>
                  </div>
                </div>
                <ul className="mt-5 grid gap-2 text-sm text-slate-300">
                  {[
                    "signed/validated local bundle identity",
                    "host platform and schema compatibility",
                    "deployment capacity before backup/runtime mutation",
                    "PostgreSQL backup before runtime mutation",
                    "offline Compose with pull disabled",
                    "named volumes and edge SQLite are preserved",
                    "post-update API / Dashboard / Device Agent readiness",
                    "no Modbus write or controller mutation path",
                  ].map((item) => (
                    <li key={item} className="flex gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section className="rounded-2xl border border-white/10 bg-[#071426]/90 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs tracking-[.18em] text-slate-500 uppercase">GitHub update plane</p>
                  <h2 className="mt-1 text-lg font-semibold">Автоматичні оновлення</h2>
                  <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">
                    GitHub не потрібен для monitoring runtime. Перевірка виконується host-side; remote commit
                    не стає installation authority без GREEN main CI та відповідного validated local package.
                  </p>
                </div>
                <label className="flex items-center gap-3 rounded-xl border border-white/10 bg-[#06101f]/75 px-4 py-3">
                  <span className="text-sm text-slate-300">
                    {automaticUpdatesEnabled ? "Увімкнено" : "Вимкнено"}
                  </span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={automaticUpdatesEnabled}
                    aria-label="Автоматичні оновлення"
                    disabled={!client || policyBusy || Boolean(snapshot?.activeOperation)}
                    onClick={() => void changeAutomaticUpdates(!automaticUpdatesEnabled)}
                    className={cn(
                      "relative h-6 w-11 rounded-full border transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-60",
                      automaticUpdatesEnabled
                        ? "border-emerald-300/60 bg-emerald-400/30"
                        : "border-white/20 bg-white/5",
                    )}
                  >
                    <span
                      className={cn(
                        "absolute top-0.5 h-4.5 w-4.5 rounded-full bg-slate-100 transition-all",
                        automaticUpdatesEnabled ? "left-5.5" : "left-0.5",
                      )}
                    />
                  </button>
                </label>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <Fact
                  label="Schedule"
                  value={automaticUpdatesEnabled ? "Щодня о 02:00" : "Автоматичний запуск вимкнено"}
                />
                <Fact label="Policy source" value="Локальний host state" />
                <Fact
                  label="Last policy change"
                  value={snapshot?.updatePolicy.updatedAt ? formatTime(snapshot.updatePolicy.updatedAt) : "—"}
                />
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={!client || checkBusy || Boolean(snapshot?.activeOperation)}
                  onClick={() => void checkForUpdates()}
                  className="inline-flex items-center gap-2 rounded-lg border border-cyan-300/25 bg-cyan-300/8 px-3 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/12 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw
                    className={cn("h-4 w-4", checkBusy && "animate-spin motion-reduce:animate-none")}
                  />
                  {checkBusy ? "Запит передано…" : "Перевірити оновлення зараз"}
                </button>
                <span className="text-xs text-slate-500">
                  Працює незалежно від ON/OFF автоматичних оновлень.
                </span>
              </div>

              <div className="mt-4 rounded-xl border border-white/10 bg-[#06101f]/75 px-4 py-4">
                {updateCheck ? (
                  <div className="grid gap-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-100">
                        {updateCheckLabel(updateCheck.resultCode)}
                      </span>
                      <span className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-slate-400">
                        {updateCheck.source === "scheduled" ? "02:00 scheduler" : "manual"}
                      </span>
                      {updateCheck.greenRevisionVerified ? (
                        <span className="rounded-full border border-emerald-300/20 bg-emerald-300/5 px-2 py-0.5 text-[11px] text-emerald-200">
                          GREEN main verified
                        </span>
                      ) : null}
                    </div>
                    {updateCheck.message ? <p className="text-slate-400">{updateCheck.message}</p> : null}
                    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
                      {updateCheck.completedAt ? <span>{formatTime(updateCheck.completedAt)}</span> : null}
                      {updateCheck.currentCommit ? (
                        <span>current {shortCommit(updateCheck.currentCommit)}</span>
                      ) : null}
                      {updateCheck.targetCommit ? (
                        <span>target {shortCommit(updateCheck.targetCommit)}</span>
                      ) : null}
                      {updateCheck.candidateBundleId ? (
                        <span>package {updateCheck.candidateBundleId}</span>
                      ) : null}
                    </div>
                    {updateCheck.candidateAvailable && !updateCheck.activationEligible ? (
                      <div className="mt-1 rounded-lg border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-xs text-amber-100">
                        Оновлення виявлено, але активація заблокована:{" "}
                        {updateBlockReason(updateCheck.blockedReason)}
                      </div>
                    ) : null}
                    {updateCheck.activationEligible && updateCandidate ? (
                      <div className="mt-1 rounded-lg border border-emerald-300/20 bg-emerald-300/5 px-3 py-2 text-xs text-emerald-100">
                        Eligible update: {current?.release ?? "current"} → {updateCandidate.release}. Пакет
                        обрано для existing version-management confirmation flow.
                      </div>
                    ) : null}
                    {updateCheck.automaticActivationOperationId ? (
                      <div className="mt-1 rounded-lg border border-cyan-300/20 bg-cyan-300/5 px-3 py-2 text-xs text-cyan-100">
                        02:00 scheduler передав validated package у existing version manager. Operation ID:{" "}
                        {updateCheck.automaticActivationOperationId}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    Ще не було update-plane перевірки. Monitoring runtime від цього не залежить.
                  </p>
                )}
              </div>
            </section>

            {snapshot?.activeOperation ? (
              <VersionOperationProgress operation={snapshot.activeOperation} />
            ) : null}

            <section className="grid gap-4 xl:grid-cols-[.9fr_1.1fr]">
              <div className="rounded-2xl border border-white/10 bg-[#071426]/90 p-5">
                <div className="flex items-center gap-3">
                  <ArrowLeftRight className="h-5 w-5 text-cyan-300" />
                  <h2 className="text-lg font-semibold">Локальні release packages</h2>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Вибір у цьому списку не запускає update. Активація потребує окремої confirmation phrase і
                  перевіряється backend/host worker повторно.
                </p>
                <div className="mt-4 grid gap-2">
                  {availableTargets.length ? (
                    availableTargets.map((item) => (
                      <PackageRow
                        key={item.bundleId}
                        item={item}
                        selected={selectedBundleId === item.bundleId}
                        onSelect={() => setSelectedBundleId(item.bundleId)}
                      />
                    ))
                  ) : (
                    <div className="rounded-xl border border-white/8 bg-white/3 px-4 py-4 text-sm text-slate-500">
                      Інших validated packages у локальному catalog немає.
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-white/10 bg-[#071426]/90 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs tracking-[.18em] text-slate-500 uppercase">Controlled action</p>
                    <h2 className="mt-1 text-lg font-semibold">Update / rollback</h2>
                  </div>
                  <div className="flex rounded-lg border border-white/10 bg-[#05101e] p-1">
                    {(["update", "rollback"] as const).map((value) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setAction(value)}
                        className={cn(
                          "rounded-md px-3 py-1.5 text-xs font-medium transition",
                          action === value
                            ? "bg-cyan-300/15 text-cyan-100"
                            : "text-slate-500 hover:text-slate-300",
                        )}
                      >
                        {value === "update" ? "Update" : "Rollback"}
                      </button>
                    ))}
                  </div>
                </div>

                {selected ? (
                  <div className="mt-4 grid gap-3">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Fact label="Target release" value={selected.release} />
                      <Fact
                        label="Target commit"
                        value={shortCommit(selected.sourceCommit)}
                        mono
                        title={selected.sourceCommit}
                      />
                      <Fact label="Target schema" value={selected.schemaHead} mono />
                      <Fact label="Platform" value={selected.platform} />
                    </div>
                    <label className="grid gap-1.5 text-sm">
                      <span className="text-slate-400">Reason / operator note</span>
                      <input
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="Optional local audit note"
                        className="rounded-lg border border-white/10 bg-[#040d1a] px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/50"
                      />
                    </label>
                    <button
                      type="button"
                      disabled={!current || !current.runtimeStateKnown || Boolean(snapshot?.activeOperation)}
                      onClick={() => setShowConfirm(true)}
                      className="inline-flex w-fit items-center gap-2 rounded-lg border border-amber-300/30 bg-amber-300/8 px-4 py-2 text-sm text-amber-100 transition hover:bg-amber-300/12 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {action === "update" ? (
                        <Download className="h-4 w-4" />
                      ) : (
                        <RotateCcw className="h-4 w-4" />
                      )}
                      {action === "update" ? "Підготувати update" : "Підготувати rollback"}
                    </button>
                    {!current?.runtimeStateKnown ? (
                      <div className="rounded-xl border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-xs text-amber-100">
                        Runtime state позначений як unknown; нова активація заблокована до operator recovery.
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="mt-4 rounded-xl border border-white/8 bg-white/3 px-4 py-4 text-sm text-slate-500">
                    Оберіть validated package з локального catalog.
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-white/10 bg-[#071426]/90 p-5">
              <div className="flex items-center gap-3">
                <History className="h-5 w-5 text-cyan-300" />
                <h2 className="text-lg font-semibold">Version history</h2>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[860px] text-left text-sm">
                  <thead className="text-xs tracking-[.12em] text-slate-500 uppercase">
                    <tr className="border-b border-white/8">
                      <th className="px-3 py-3 font-medium">Start</th>
                      <th className="px-3 py-3 font-medium">Action</th>
                      <th className="px-3 py-3 font-medium">From → To</th>
                      <th className="px-3 py-3 font-medium">Status</th>
                      <th className="px-3 py-3 font-medium">Actor</th>
                      <th className="px-3 py-3 font-medium">Evidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/6">
                    {snapshot?.history.length ? (
                      snapshot.history.map((operation) => (
                        <tr key={operation.id} className="text-slate-300">
                          <td className="px-3 py-3 text-slate-400">{formatTime(operation.startedAt)}</td>
                          <td className="px-3 py-3">{operation.action}</td>
                          <td className="px-3 py-3">
                            {operation.sourceRelease} → {operation.targetRelease}
                          </td>
                          <td className="px-3 py-3">
                            <OperationBadge status={operation.status} />
                          </td>
                          <td className="px-3 py-3 text-slate-400">{operation.actorSubject}</td>
                          <td className="px-3 py-3 font-mono text-xs text-slate-500">
                            {operation.resultCode ?? "—"}
                            {operation.capacityEvidenceId ? ` · ${operation.capacityEvidenceId}` : ""}
                            {operation.backupEvidenceId ? ` · ${operation.backupEvidenceId}` : ""}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={6} className="px-3 py-5 text-center text-slate-500">
                          Історія update/rollback операцій порожня.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            {snapshot?.rejectedPackages.length ? (
              <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5">
                <div className="flex items-center gap-2 text-amber-100">
                  <AlertTriangle className="h-5 w-5" />
                  <h2 className="font-semibold">Rejected packages</h2>
                </div>
                <div className="mt-3 grid gap-2 text-sm">
                  {snapshot.rejectedPackages.map((item) => (
                    <div
                      key={item.directory}
                      className="rounded-lg border border-amber-300/10 bg-black/10 px-3 py-2"
                    >
                      <span className="font-mono text-xs text-amber-200">{item.directory}</span>
                      <span className="mx-2 text-amber-500">·</span>
                      <span className="text-amber-100">{item.code}</span>
                      <p className="mt-1 text-xs text-amber-100/70">{item.message}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        )}
      </main>

      {showConfirm && selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="version-confirm-title"
            className="w-full max-w-lg rounded-2xl border border-amber-300/25 bg-[#071426] p-5 shadow-2xl"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full border border-amber-300/25 bg-amber-300/8">
                <AlertTriangle className="h-5 w-5 text-amber-200" />
              </div>
              <div>
                <p className="text-xs tracking-[.16em] text-amber-300 uppercase">Explicit confirmation</p>
                <h2 id="version-confirm-title" className="text-lg font-semibold">
                  Підтвердити {action === "update" ? "update" : "rollback"}
                </h2>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-300">
              Target: <strong>{selected.release}</strong> / {shortCommit(selected.sourceCommit)}. Перед
              runtime mutation host worker повторно перевірить package, schema, capacity і створить PostgreSQL
              backup.
            </p>
            <label className="mt-4 grid gap-1.5 text-sm">
              <span className="text-slate-400">
                Введіть{" "}
                <code className="text-cyan-200">{versionConfirmationPhrase(action, selected.bundleId)}</code>
              </span>
              <input
                autoFocus
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                className="rounded-lg border border-white/10 bg-[#040d1a] px-3 py-2 font-mono text-sm text-slate-100 outline-none focus:border-amber-300/50"
              />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowConfirm(false);
                  setConfirmation("");
                }}
                className="rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/5"
              >
                Скасувати
              </button>
              <button
                type="button"
                disabled={busy || confirmation !== versionConfirmationPhrase(action, selected.bundleId)}
                onClick={() => void submitAction()}
                className="inline-flex items-center gap-2 rounded-lg border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100 hover:bg-amber-300/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? <RefreshCw className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
                {busy ? "Запит…" : "Підтвердити"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PackageRow({
  item,
  selected,
  onSelect,
}: {
  item: VersionCatalogItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-xl border px-4 py-3 text-left transition",
        selected
          ? "border-cyan-300/40 bg-cyan-300/8"
          : "border-white/8 bg-white/3 hover:border-white/15 hover:bg-white/5",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-slate-100">{item.release}</div>
          <div className="mt-1 font-mono text-xs text-slate-500">{item.bundleId}</div>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>{shortCommit(item.sourceCommit)}</div>
          <div className="mt-1">schema {item.schemaHead}</div>
        </div>
      </div>
    </button>
  );
}

function Fact({
  label,
  value,
  mono = false,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/3 px-3 py-3">
      <div className="text-[11px] tracking-[.12em] text-slate-500 uppercase">{label}</div>
      <div className={cn("mt-1 truncate text-sm text-slate-200", mono && "font-mono")} title={title ?? value}>
        {value}
      </div>
    </div>
  );
}

function OperationBadge({ status }: { status: "queued" | "running" | "succeeded" | "failed" }) {
  const style =
    status === "succeeded"
      ? "border-emerald-300/25 bg-emerald-300/8 text-emerald-200"
      : status === "failed"
        ? "border-rose-300/25 bg-rose-300/8 text-rose-200"
        : status === "running"
          ? "border-cyan-300/25 bg-cyan-300/8 text-cyan-200"
          : "border-amber-300/25 bg-amber-300/8 text-amber-200";
  return <span className={cn("rounded-full border px-2 py-1 text-xs", style)}>{status}</span>;
}

function updateCheckLabel(resultCode: string | null): string {
  switch (resultCode) {
    case "up_to_date":
      return "Встановлено актуальну версію";
    case "candidate_discovered":
      return "Знайдено новішу revision";
    case "github_unavailable":
    case "github_ci_unavailable":
      return "GitHub/update-plane недоступний";
    case "automatic_updates_disabled":
      return "Автоматичні оновлення вимкнено";
    case null:
      return "Перевірка оновлення";
    default:
      return resultCode;
  }
}

function updateBlockReason(reason: string | null): string {
  switch (reason) {
    case "validated_package_required":
      return "для remote revision ще немає validated local package";
    case "current_release_unverified":
      return "поточний runtime не має повного validated package evidence";
    case "target_release_unverified":
      return "target package не пройшов local validation";
    case "platform_incompatible":
      return "target package не відповідає platform поточного runtime";
    case "schema_compatibility_unknown":
      return "schema compatibility з поточним runtime не підтверджена";
    case "ci_not_green":
      return "main-branch CI для target revision завершився неуспішно";
    case "ci_pending_or_missing":
      return "успішний main-branch CI для target revision ще не зафіксовано";
    case "github_ci_unavailable":
      return "не вдалося перевірити GitHub CI evidence";
    case "github_unavailable":
      return "GitHub/origin недоступний; runtime не змінено";
    case "repository_mismatch":
      return "configured origin не є canonical NEXOLAB repository";
    case "branch_mismatch":
      return "update discovery дозволений лише з main";
    case "tracked_worktree_dirty":
      return "tracked local changes блокують update";
    case "current_revision_unknown":
      return "поточна deployed revision невідома";
    case "non_fast_forward":
      return "target не є fast-forward продовженням deployed lineage";
    case "operation_in_progress":
      return "інша update/rollback operation уже виконується або очікує";
    case "candidate_not_eligible":
    case "candidate_revalidation_failed":
      return "candidate втратив eligibility під час повторної host-side перевірки";
    case null:
      return "host eligibility gate";
    default:
      return reason;
  }
}

function shortCommit(value: string): string {
  return value.slice(0, 12);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(date);
}

function describeError(error: unknown): string {
  if (error instanceof VersionManagementApiError) {
    return `${error.message} (${error.code})`;
  }
  if (error instanceof RuntimeCredentialUnavailableError) {
    return "Локальна auth session недоступна. Увійдіть повторно та повторіть дію.";
  }
  return error instanceof Error ? error.message : "Version Management недоступний.";
}
