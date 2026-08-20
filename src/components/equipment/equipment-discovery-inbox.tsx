"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Ban,
  CheckCircle2,
  Link2,
  LoaderCircle,
  Network,
  Radar,
  RefreshCcw,
  ScanSearch,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import type { EquipmentRegistryAsset } from "@/features/equipment/asset-registry";
import {
  EquipmentDiscoveryRepositoryError,
  type EquipmentDiscoveryCandidate,
  type EquipmentDiscoveryCandidateAction,
  type EquipmentDiscoveryOverview,
  type EquipmentDiscoveryRepository,
} from "@/features/equipment/discovery-repository";

export function EquipmentDiscoveryInbox({
  repository,
  canManage,
  assets,
}: {
  repository: EquipmentDiscoveryRepository | null;
  canManage: boolean;
  assets: EquipmentRegistryAsset[];
}) {
  const [overview, setOverview] = useState<EquipmentDiscoveryOverview | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [cidrs, setCidrs] = useState("");
  const [ports, setPorts] = useState("");
  const [pendingCandidateId, setPendingCandidateId] = useState<string | null>(null);
  const [adoptNames, setAdoptNames] = useState<Record<string, string>>({});
  const [linkTargets, setLinkTargets] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    if (!repository) return;
    setState((current) => (current === "ready" ? "ready" : "loading"));
    setError(null);
    try {
      const next = await repository.getOverview();
      setOverview(next);
      setCidrs((current) => current || next.policy.allowedCidrs.join(", "));
      setPorts((current) => current || next.policy.allowedPorts.join(", "));
      setState("ready");
    } catch (loadError) {
      setState("error");
      setError(discoveryErrorMessage(loadError));
    }
  }, [repository]);

  useEffect(() => {
    if (!repository) return;
    const id = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(id);
  }, [refresh, repository]);

  const activeScan = overview?.activeScan ?? null;
  useEffect(() => {
    if (!repository || !activeScan) return;
    const id = window.setTimeout(() => void refresh(), 1000);
    return () => window.clearTimeout(id);
  }, [activeScan, refresh, repository]);

  const sortedCandidates = useMemo(
    () =>
      [...(overview?.candidates ?? [])].sort((left, right) => {
        if (left.present !== right.present) return left.present ? -1 : 1;
        if (left.lifecycle === "new" && right.lifecycle !== "new") return -1;
        if (right.lifecycle === "new" && left.lifecycle !== "new") return 1;
        return right.lastSeenAt.localeCompare(left.lastSeenAt);
      }),
    [overview?.candidates],
  );

  if (!repository) return null;

  const startScan = async () => {
    setError(null);
    try {
      const parsedCidrs = parseCsv(cidrs);
      const parsedPorts = parsePorts(ports);
      await repository.startScan({
        cidrs: parsedCidrs.length > 0 ? parsedCidrs : undefined,
        ports: parsedPorts.length > 0 ? parsedPorts : undefined,
      });
      await refresh();
    } catch (scanError) {
      setError(discoveryErrorMessage(scanError));
    }
  };

  const cancelScan = async () => {
    if (!overview?.activeScan) return;
    setError(null);
    try {
      await repository.cancelScan(overview.activeScan.id);
      await refresh();
    } catch (cancelError) {
      setError(discoveryErrorMessage(cancelError));
    }
  };

  const act = async (candidate: EquipmentDiscoveryCandidate, action: EquipmentDiscoveryCandidateAction) => {
    setPendingCandidateId(candidate.id);
    setError(null);
    try {
      await repository.actOnCandidate(candidate.id, action, candidate.version);
      await refresh();
    } catch (actionError) {
      setError(discoveryErrorMessage(actionError));
    } finally {
      setPendingCandidateId(null);
    }
  };

  return (
    <section className="rounded-3xl border border-cyan-300/10 bg-[#08182e]/90 p-4 shadow-xl shadow-black/10 sm:p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-cyan-300 uppercase">
            <Radar className="h-4 w-4" />
            LOCAL_LAN discovery inbox
          </div>
          <h2 className="mt-2 text-xl font-semibold text-white">Нові пристрої</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">
            Виявлення працює тільки в явно дозволених приватних CIDR і виконує лише TCP connect-перевірки без
            передачі application payload. Знайдений пристрій не стає acquisition target автоматично.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {state === "loading" ? <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> : null}
          <button
            type="button"
            onClick={() => void refresh()}
            aria-label="Оновити inbox виявлення"
            className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/[0.06] hover:text-white"
          >
            <RefreshCcw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {error ? (
        <div className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/[0.07] px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      {overview ? (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <DiscoveryMetric label="Кандидати" value={overview.candidates.length} />
            <DiscoveryMetric
              label="Активні network assets"
              value={overview.networkAssets.filter((item) => item.status === "active").length}
            />
            <DiscoveryMetric label="Макс. hosts" value={overview.policy.maxHosts} />
            <DiscoveryMetric label="Payload bytes / probe" value={overview.policy.payloadBytesSentPerProbe} />
          </div>

          <div className="mt-4 rounded-2xl border border-white/8 bg-white/[0.025] p-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <ShieldCheck className="h-4 w-4 text-emerald-300" />
              <span>Mode: {overview.policy.probeMode}</span>
              <span>·</span>
              <span>Timeout: {overview.policy.connectTimeoutSeconds}s</span>
              <span>·</span>
              <span>Concurrency: {overview.policy.concurrency}</span>
              <span>·</span>
              <span>
                Schedule:{" "}
                {overview.policy.scheduleIntervalSeconds > 0
                  ? `${overview.policy.scheduleIntervalSeconds}s`
                  : "off"}
              </span>
            </div>

            {!overview.policy.enabled ? (
              <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-300/15 bg-amber-300/[0.05] px-3 py-2 text-sm text-amber-100">
                <Ban className="mt-0.5 h-4 w-4 shrink-0" />
                Discovery вимкнено fail-closed: налаштуйте явний EQUIPMENT_DISCOVERY_ALLOWED_CIDRS у LOCAL_LAN
                runtime.
              </div>
            ) : (
              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_auto]">
                <label className="text-xs text-slate-400">
                  Дозволений CIDR scope
                  <input
                    value={cidrs}
                    onChange={(event) => setCidrs(event.target.value)}
                    disabled={!canManage || Boolean(overview.activeScan)}
                    className={inputClass}
                    aria-label="CIDR scope discovery"
                  />
                </label>
                <label className="text-xs text-slate-400">
                  TCP ports
                  <input
                    value={ports}
                    onChange={(event) => setPorts(event.target.value)}
                    disabled={!canManage || Boolean(overview.activeScan)}
                    className={inputClass}
                    aria-label="TCP ports discovery"
                  />
                </label>
                <div className="flex items-end gap-2">
                  {overview.activeScan ? (
                    <button
                      type="button"
                      onClick={() => void cancelScan()}
                      disabled={!canManage}
                      className={secondaryButtonClass}
                    >
                      <XCircle className="h-4 w-4" /> Скасувати scan
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void startScan()}
                      disabled={!canManage}
                      className={primaryButtonClass}
                    >
                      <ScanSearch className="h-4 w-4" /> Запустити scan
                    </button>
                  )}
                </div>
              </div>
            )}

            <ScanSummary overview={overview} />
          </div>

          <div className="mt-4 space-y-3">
            {sortedCandidates.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-500">
                Кандидатів ще немає. Scan не запускається автоматично — потрібна явна дія оператора.
              </div>
            ) : (
              sortedCandidates.map((candidate) => (
                <CandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  canManage={canManage}
                  assets={assets}
                  pending={pendingCandidateId === candidate.id}
                  adoptName={
                    adoptNames[candidate.id] ?? candidate.hostname ?? `Network device ${candidate.ipAddress}`
                  }
                  linkTarget={linkTargets[candidate.id] ?? ""}
                  onAdoptNameChange={(value) =>
                    setAdoptNames((current) => ({ ...current, [candidate.id]: value }))
                  }
                  onLinkTargetChange={(value) =>
                    setLinkTargets((current) => ({ ...current, [candidate.id]: value }))
                  }
                  onAction={(action) => void act(candidate, action)}
                />
              ))
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}

function CandidateCard({
  candidate,
  canManage,
  assets,
  pending,
  adoptName,
  linkTarget,
  onAdoptNameChange,
  onLinkTargetChange,
  onAction,
}: {
  candidate: EquipmentDiscoveryCandidate;
  canManage: boolean;
  assets: EquipmentRegistryAsset[];
  pending: boolean;
  adoptName: string;
  linkTarget: string;
  onAdoptNameChange: (value: string) => void;
  onLinkTargetChange: (value: string) => void;
  onAction: (action: EquipmentDiscoveryCandidateAction) => void;
}) {
  const closed = candidate.lifecycle === "adopted" || candidate.lifecycle === "ignored";
  return (
    <article className="rounded-2xl border border-white/8 bg-[#071326]/80 p-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Network className="h-4 w-4 text-cyan-300" />
            <strong className="text-sm text-white">{candidate.hostname ?? candidate.ipAddress}</strong>
            <span className={statusClass(candidate.lifecycle)}>
              {candidateLifecycleLabel(candidate.lifecycle)}
            </span>
            {!candidate.present ? (
              <span className="text-xs text-slate-500">не знайдений у останньому scan</span>
            ) : null}
            {candidate.changedSincePreviousScan ? (
              <span className="text-xs text-amber-200">зміни з попереднього scan</span>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
            <span>IP: {candidate.ipAddress}</span>
            <span>MAC: {candidate.macAddress ?? "не спостерігається"}</span>
            <span>Subnet: {candidate.sourceSubnet}</span>
            <span>Interface: {candidate.sourceInterface ?? "не визначено"}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {candidate.services.length > 0 ? (
              candidate.services.map((service) => (
                <span
                  key={`${candidate.id}:${service.port}`}
                  className="rounded-lg border border-cyan-300/10 bg-cyan-400/[0.05] px-2 py-1 text-[11px] text-cyan-100"
                >
                  TCP {service.port} · {service.service} · connect succeeded
                </span>
              ))
            ) : (
              <span className="text-xs text-slate-500">
                TCP service evidence відсутнє; candidate може походити з neighbor table.
              </span>
            )}
          </div>
          {candidate.linkedEquipmentKey ? (
            <p className="mt-2 text-xs text-emerald-200">Canonical link: {candidate.linkedEquipmentKey}</p>
          ) : null}
        </div>

        {pending ? <LoaderCircle className="h-5 w-5 shrink-0 animate-spin text-cyan-300" /> : null}
      </div>

      {canManage && !closed ? (
        <div className="mt-4 grid gap-3 border-t border-white/8 pt-4 xl:grid-cols-[auto_1fr_auto_1fr_auto] xl:items-end">
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pending}
              onClick={() => onAction({ action: "review" })}
              className={secondaryButtonClass}
            >
              <CheckCircle2 className="h-4 w-4" /> Переглянуто
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => onAction({ action: "ignore" })}
              className={secondaryButtonClass}
            >
              <Ban className="h-4 w-4" /> Ігнорувати
            </button>
          </div>
          <label className="text-xs text-slate-400">
            Зв’язати з існуючим активом
            <select
              value={linkTarget}
              onChange={(event) => onLinkTargetChange(event.target.value)}
              className={inputClass}
              aria-label={`Canonical asset for ${candidate.ipAddress}`}
            >
              <option value="">Оберіть актив…</option>
              {assets.map((asset) => (
                <option key={asset.key} value={asset.key}>
                  {asset.primaryIdentifier} · {asset.displayName}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={pending || !linkTarget}
            onClick={() => onAction({ action: "link_existing", linkedEquipmentKey: linkTarget })}
            className={secondaryButtonClass}
          >
            <Link2 className="h-4 w-4" /> Зв’язати
          </button>
          <label className="text-xs text-slate-400">
            Administrative network asset
            <input
              value={adoptName}
              onChange={(event) => onAdoptNameChange(event.target.value)}
              className={inputClass}
              aria-label={`Adopted asset name for ${candidate.ipAddress}`}
            />
          </label>
          <button
            type="button"
            disabled={pending || !adoptName.trim()}
            onClick={() => onAction({ action: "adopt", displayName: adoptName.trim() })}
            className={primaryButtonClass}
          >
            <CheckCircle2 className="h-4 w-4" /> Adopt
          </button>
        </div>
      ) : !canManage ? (
        <p className="mt-4 border-t border-white/8 pt-3 text-xs text-slate-500">
          Доступ лише для перегляду discovery evidence.
        </p>
      ) : null}
    </article>
  );
}

function ScanSummary({ overview }: { overview: EquipmentDiscoveryOverview }) {
  const scan = overview.activeScan ?? overview.lastScan;
  if (!scan) return <p className="mt-3 text-xs text-slate-500">Scan ще не запускався.</p>;
  return (
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
      <span
        className={
          scan.status === "completed"
            ? "text-emerald-200"
            : scan.status === "failed"
              ? "text-rose-200"
              : "text-cyan-200"
        }
      >
        {scan.status === "running" ? "Scan виконується" : `Останній scan: ${scan.status}`}
      </span>
      <span>
        Hosts {scan.hostsConsidered}/{scan.hostBudget}
      </span>
      <span>
        Probes {scan.probesAttempted}/{scan.probeBudget}
      </span>
      <span>Responsive {scan.responsiveHosts}</span>
      <span>Trigger {scan.trigger}</span>
      <span>Duration {scan.durationMs} ms</span>
      <span>CPU {scan.processCpuMs} ms</span>
      <span>Connect attempts {scan.networkConnectAttempts}</span>
      <span>Payload {scan.networkPayloadBytes} B</span>
      <span>New {scan.newCandidates}</span>
      <span>Changed {scan.changedCandidates}</span>
      <span>Disappeared {scan.disappearedCandidates}</span>
      {scan.errorMessage ? <span className="text-rose-200">{scan.errorMessage}</span> : null}
    </div>
  );
}

function DiscoveryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.025] px-3 py-3">
      <div className="text-[10px] font-semibold tracking-[0.12em] text-slate-500 uppercase">{label}</div>
      <div className="mt-1 text-xl font-semibold text-white">{value}</div>
    </div>
  );
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parsePorts(value: string): number[] {
  const items = parseCsv(value);
  const ports = items.map((item) => Number(item));
  if (ports.some((port) => !Number.isInteger(port) || port < 1 || port > 65535)) {
    throw new Error("TCP ports мають бути цілими числами 1–65535.");
  }
  return ports;
}

function discoveryErrorMessage(error: unknown): string {
  if (error instanceof EquipmentDiscoveryRepositoryError) return error.message;
  return error instanceof Error ? error.message : "Операція discovery не виконана.";
}

function candidateLifecycleLabel(value: EquipmentDiscoveryCandidate["lifecycle"]): string {
  if (value === "new") return "Новий";
  if (value === "reviewed") return "Переглянуто";
  if (value === "matched_existing") return "Зв’язано";
  if (value === "adopted") return "Adopted";
  if (value === "ignored") return "Ignored";
  return "Disappeared";
}

function statusClass(value: EquipmentDiscoveryCandidate["lifecycle"]): string {
  const base = "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]";
  if (value === "new") return `${base} bg-cyan-400/10 text-cyan-200`;
  if (value === "adopted" || value === "matched_existing")
    return `${base} bg-emerald-400/10 text-emerald-200`;
  if (value === "ignored" || value === "disappeared") return `${base} bg-slate-400/10 text-slate-400`;
  return `${base} bg-amber-400/10 text-amber-200`;
}

const inputClass =
  "mt-1 h-10 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/40 disabled:cursor-not-allowed disabled:opacity-50";
const primaryButtonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-blue-500 px-4 text-sm font-medium text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-40";
const secondaryButtonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-slate-200 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-40";
