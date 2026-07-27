"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Ban,
  CheckCircle2,
  Clock3,
  Copy,
  KeyRound,
  LoaderCircle,
  Network,
  PauseCircle,
  PlayCircle,
  Plus,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { createNodeApiClient, createNodeIdempotencyKey } from "@/lib/nodes/api-client";
import type {
  CentralNode,
  NodeClockStatus,
  NodeLifecycleState,
  NodeOperationalState,
} from "@/lib/nodes/types";

import { NodeOperationalPanel } from "./node-operational-panel";

function formatDate(value: string | null): string {
  if (!value) return "Ще не підключався";
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatOffset(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("uk-UA").format(value)} мс`;
}

function stateLabel(value: NodeLifecycleState): string {
  return {
    pending: "Очікує активації",
    active: "Активний",
    suspended: "Призупинений",
    revoked: "Відкликаний",
  }[value];
}

function clockLabel(value: NodeClockStatus): string {
  return {
    unknown: "Немає спостереження",
    ok: "Синхронізовано",
    warning: "Попередження",
    critical: "Критичне зміщення",
  }[value];
}

function stateClass(value: NodeLifecycleState): string {
  if (value === "active") return "border-emerald-300/20 bg-emerald-400/[0.07] text-emerald-200";
  if (value === "pending") return "border-cyan-300/20 bg-cyan-400/[0.07] text-cyan-200";
  if (value === "suspended") return "border-amber-300/20 bg-amber-400/[0.07] text-amber-200";
  return "border-red-300/20 bg-red-400/[0.07] text-red-200";
}

function clockClass(value: NodeClockStatus): string {
  if (value === "ok") return "text-emerald-300";
  if (value === "warning") return "text-amber-300";
  if (value === "critical") return "text-red-300";
  return "text-slate-500";
}

export function NodesWorkspace({ canManage }: { canManage: boolean }) {
  const [nodes, setNodes] = useState<CentralNode[]>([]);
  const [operationalStates, setOperationalStates] = useState<Record<string, NodeOperationalState | null>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nodeId, setNodeId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [clockWarningMs, setClockWarningMs] = useState("30000");
  const [clockCriticalMs, setClockCriticalMs] = useState("120000");
  const [reason, setReason] = useState("Controlled multi-node commissioning");
  const [oneTimeSecret, setOneTimeSecret] = useState<{
    nodeId: string;
    generation: number;
    secret: string;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );
  const selectedOperationalState = selectedNodeId ? (operationalStates[selectedNodeId] ?? null) : null;

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const client = createNodeApiClient();
      const result = await client.listNodes(signal);
      const operationalEntries = await Promise.all(
        result.map(async (node) => {
          try {
            const state = await client.getOperationalState(node.node_id, signal);
            return [node.node_id, state] as const;
          } catch (operationalError) {
            if (signal?.aborted) throw operationalError;
            return [node.node_id, null] as const;
          }
        }),
      );
      setNodes(result);
      setOperationalStates(Object.fromEntries(operationalEntries));
      setSelectedNodeId((current) => {
        if (current && result.some((node) => node.node_id === current)) return current;
        return result[0]?.node_id ?? null;
      });
      setError(null);
    } catch (nextError) {
      if (!signal?.aborted) {
        setError(nextError instanceof Error ? nextError : new Error("Node registry недоступний."));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      controller.abort();
      window.clearTimeout(initial);
    };
  }, [load]);

  const provision = async () => {
    const warning = Number(clockWarningMs);
    const critical = Number(clockCriticalMs);
    if (!nodeId.trim() || !displayName.trim() || !Number.isFinite(warning) || !Number.isFinite(critical)) {
      return;
    }
    setAction("provision");
    setError(null);
    setOneTimeSecret(null);
    try {
      const response = await createNodeApiClient().provisionNode(
        {
          nodeId: nodeId.trim(),
          displayName: displayName.trim(),
          clockWarningMs: warning,
          clockCriticalMs: critical,
        },
        createNodeIdempotencyKey("provision", nodeId.trim()),
      );
      if (response.provisioning_secret) {
        setOneTimeSecret({
          nodeId: response.node.node_id,
          generation: response.credential.generation,
          secret: response.provisioning_secret,
        });
      }
      setNodeId("");
      setDisplayName("");
      await load();
      setSelectedNodeId(response.node.node_id);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Вузол не вдалося створити."));
    } finally {
      setAction(null);
    }
  };

  const changeState = async (nextAction: "activate" | "suspend" | "revoke") => {
    if (!selectedNode || !reason.trim()) return;
    setAction(nextAction);
    setError(null);
    try {
      const updated = await createNodeApiClient().changeState(selectedNode.node_id, nextAction, reason);
      setNodes((current) => current.map((node) => (node.node_id === updated.node_id ? updated : node)));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Lifecycle action не виконано."));
    } finally {
      setAction(null);
    }
  };

  const rotateCredential = async () => {
    if (!selectedNode || !reason.trim()) return;
    setAction("rotate");
    setError(null);
    setOneTimeSecret(null);
    try {
      const response = await createNodeApiClient().rotateCredential(
        selectedNode.node_id,
        reason,
        createNodeIdempotencyKey("rotate", selectedNode.node_id),
      );
      if (response.provisioning_secret) {
        setOneTimeSecret({
          nodeId: response.node.node_id,
          generation: response.credential.generation,
          secret: response.provisioning_secret,
        });
      }
      await load();
      setSelectedNodeId(response.node.node_id);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Credential rotation не виконано."));
    } finally {
      setAction(null);
    }
  };

  const copySecret = async () => {
    if (!oneTimeSecret) return;
    await navigator.clipboard.writeText(oneTimeSecret.secret);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const counts = useMemo(
    () => ({
      active: nodes.filter((node) => node.state === "active").length,
      attention: nodes.filter((node) => {
        const availability = operationalStates[node.node_id]?.availability;
        return (
          node.state === "suspended" ||
          node.clock_status === "warning" ||
          node.clock_status === "critical" ||
          availability === "offline" ||
          availability === "stale"
        );
      }).length,
      total: nodes.length,
    }),
    [nodes, operationalStates],
  );

  return (
    <div className="space-y-4" data-testid="nodes-workspace">
      <section className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              M6 · Central Gateway
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">Реєстр edge-вузлів</h1>
            <p className="mt-2 max-w-3xl text-[12px] leading-6 text-slate-400">
              Організаційно ізольовані identity, one-time provisioning credentials, MQTT namespace ownership,
              replay cursor та контроль зміщення часу.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:min-w-[420px]">
            <Summary label="Всього" value={counts.total} />
            <Summary label="Активних" value={counts.active} />
            <Summary label="Увага" value={counts.attention} />
          </div>
        </div>
      </section>

      {canManage ? (
        <section className="panel p-4 sm:p-5" data-testid="node-provision-panel">
          <div className="grid gap-3 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_160px_160px_auto] xl:items-end">
            <Field label="Node ID">
              <input
                value={nodeId}
                onChange={(event) => setNodeId(event.target.value)}
                placeholder="edge-02"
                className="form-input"
                data-testid="node-id-input"
              />
            </Field>
            <Field label="Назва">
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Холодильна камера B"
                className="form-input"
                data-testid="node-name-input"
              />
            </Field>
            <Field label="Clock warning, мс">
              <input
                value={clockWarningMs}
                onChange={(event) => setClockWarningMs(event.target.value)}
                inputMode="numeric"
                className="form-input"
              />
            </Field>
            <Field label="Clock critical, мс">
              <input
                value={clockCriticalMs}
                onChange={(event) => setClockCriticalMs(event.target.value)}
                inputMode="numeric"
                className="form-input"
              />
            </Field>
            <button
              type="button"
              onClick={() => void provision()}
              disabled={action !== null || !nodeId.trim() || !displayName.trim()}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-400/10 px-4 text-[11px] font-semibold text-cyan-100 transition hover:bg-cyan-400/15 disabled:cursor-not-allowed disabled:opacity-45"
              data-testid="provision-node"
            >
              {action === "provision" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Provision
            </button>
          </div>
        </section>
      ) : (
        <section className="panel flex items-center gap-3 p-4 text-[11px] text-slate-400">
          <ShieldCheck className="h-5 w-5 text-cyan-300" />
          Поточна роль має read-only доступ. Provisioning і lifecycle потребують permission
          <code className="rounded bg-white/[0.04] px-1.5 py-0.5 text-cyan-200">nodes.manage</code>.
        </section>
      )}

      {oneTimeSecret ? (
        <section
          className="rounded-2xl border border-amber-300/20 bg-amber-400/[0.06] p-4 sm:p-5"
          data-testid="one-time-node-secret"
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="flex items-center gap-2 text-[10px] font-semibold text-amber-200">
                <KeyRound className="h-4 w-4" />
                One-time credential · {oneTimeSecret.nodeId} · generation {oneTimeSecret.generation}
              </p>
              <p className="mt-2 text-[10px] leading-5 text-amber-100/65">
                Секрет не зберігається у відкритому вигляді й більше не буде повернутий API. Передайте його
                лише до контрольованого broker credential store.
              </p>
              <code className="mt-3 block max-w-4xl overflow-x-auto rounded-xl border border-amber-200/10 bg-slate-950/40 p-3 text-[11px] text-amber-100">
                {oneTimeSecret.secret}
              </code>
            </div>
            <button
              type="button"
              onClick={() => void copySecret()}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-amber-200/20 px-3 py-2 text-[10px] font-semibold text-amber-100"
            >
              <Copy className="h-3.5 w-3.5" />
              {copied ? "Скопійовано" : "Копіювати"}
            </button>
          </div>
        </section>
      ) : null}

      {error ? (
        <section className="rounded-2xl border border-red-300/20 bg-red-400/[0.06] p-4 text-[11px] text-red-200">
          {error.message}
        </section>
      ) : null}

      <section className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.055] p-4 sm:p-5">
          <div>
            <h2 className="text-sm font-semibold text-white">Central node inventory</h2>
            <p className="mt-1 text-[10px] text-slate-500">Trusted-broker identity та operational state</p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="icon-button"
            aria-label="Оновити вузли"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        {loading && nodes.length === 0 ? (
          <Status
            icon={LoaderCircle}
            title="Завантаження вузлів"
            detail="Читаємо organization-scoped registry…"
            spin
          />
        ) : nodes.length === 0 ? (
          <Status
            icon={Network}
            title="Вузлів ще немає"
            detail="Створіть перший software-provisioned edge node."
          />
        ) : (
          <div className="grid min-h-[560px] xl:grid-cols-[360px_minmax(0,1fr)]">
            <div className="border-b border-white/[0.055] xl:border-r xl:border-b-0">
              {nodes.map((node) => (
                <button
                  type="button"
                  key={node.id}
                  onClick={() => setSelectedNodeId(node.node_id)}
                  className={`block w-full border-b border-white/[0.045] p-4 text-left transition ${
                    selectedNodeId === node.node_id ? "bg-cyan-400/[0.06]" : "hover:bg-white/[0.025]"
                  }`}
                  data-testid={`node-row-${node.node_id}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[12px] font-semibold text-slate-100">{node.display_name}</p>
                      <p className="mt-1 font-mono text-[10px] text-cyan-300/80">{node.node_id}</p>
                    </div>
                    <span
                      className={`rounded-lg border px-2 py-1 text-[9px] font-semibold ${stateClass(node.state)}`}
                    >
                      {node.state}
                    </span>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2 text-[9px] text-slate-500">
                    <span>Last seen: {formatDate(node.last_seen_at)}</span>
                    <span
                      className={
                        operationalStates[node.node_id]?.availability === "online"
                          ? "text-emerald-300"
                          : operationalStates[node.node_id]?.availability === "offline"
                            ? "text-red-300"
                            : operationalStates[node.node_id]?.availability === "stale"
                              ? "text-amber-300"
                              : "text-slate-600"
                      }
                      data-testid={`node-row-availability-${node.node_id}`}
                    >
                      {operationalStates[node.node_id]?.availability ?? "unknown"}
                    </span>
                  </div>
                </button>
              ))}
            </div>

            <div className="p-4 sm:p-5" data-testid="node-detail">
              {selectedNode ? (
                <NodeDetail
                  node={selectedNode}
                  operationalState={selectedOperationalState}
                  canManage={canManage}
                  reason={reason}
                  action={action}
                  onReasonChange={setReason}
                  onChangeState={changeState}
                  onRotate={rotateCredential}
                />
              ) : (
                <Status icon={Network} title="Оберіть вузол" detail="Виберіть node identity у registry." />
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function NodeDetail({
  node,
  operationalState,
  canManage,
  reason,
  action,
  onReasonChange,
  onChangeState,
  onRotate,
}: {
  node: CentralNode;
  operationalState: NodeOperationalState | null;
  canManage: boolean;
  reason: string;
  action: string | null;
  onReasonChange: (value: string) => void;
  onChangeState: (action: "activate" | "suspend" | "revoke") => Promise<void>;
  onRotate: () => Promise<void>;
}) {
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[9px] font-semibold tracking-[0.14em] text-cyan-300 uppercase">{node.node_id}</p>
          <h3 className="mt-2 text-xl font-semibold text-white">{node.display_name}</h3>
          <p className="mt-2 text-[11px] text-slate-500">
            {node.state_reason ?? "Lifecycle reason не задано"}
          </p>
        </div>
        <span className={`rounded-xl border px-3 py-2 text-[10px] font-semibold ${stateClass(node.state)}`}>
          {stateLabel(node.state)}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Meta icon={Activity} label="Last seen" value={formatDate(node.last_seen_at)} />
        <Meta
          icon={Clock3}
          label="Clock offset"
          value={`${formatOffset(node.last_clock_offset_ms)} · ${clockLabel(node.clock_status)}`}
          valueClass={clockClass(node.clock_status)}
        />
        <Meta
          icon={KeyRound}
          label="Credential"
          value={
            node.current_credential
              ? `generation ${node.current_credential.generation} · ${node.current_credential.secret_fingerprint}`
              : "Немає активного credential"
          }
        />
        <Meta
          icon={TriangleAlert}
          label="Clock policy"
          value={`${node.clock_warning_ms} / ${node.clock_critical_ms} мс`}
        />
      </div>

      <NodeOperationalPanel state={operationalState} />

      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.018] p-4">
        <p className="text-[10px] font-semibold text-slate-200">Owned MQTT namespaces</p>
        <div className="mt-2 space-y-1 overflow-x-auto font-mono text-[10px] text-cyan-200">
          <p>
            nexolab/v1/{node.organization_id}/{node.node_id}/telemetry
          </p>
          <p>
            nexolab/v1/{node.organization_id}/{node.node_id}/health
          </p>
          <p>
            nexolab/v1/{node.organization_id}/{node.node_id}/status
          </p>
        </div>
      </div>

      {canManage && node.state !== "revoked" ? (
        <div className="space-y-3 border-t border-white/[0.06] pt-4" data-testid="node-actions">
          <Field label="Audit reason">
            <input
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
              className="form-input"
              data-testid="node-action-reason"
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            {node.state === "pending" || node.state === "suspended" ? (
              <ActionButton
                testId="activate-node"
                label="Активувати"
                icon={PlayCircle}
                busy={action === "activate"}
                onClick={() => void onChangeState("activate")}
              />
            ) : null}
            {node.state === "active" ? (
              <ActionButton
                testId="suspend-node"
                label="Призупинити"
                icon={PauseCircle}
                busy={action === "suspend"}
                onClick={() => void onChangeState("suspend")}
              />
            ) : null}
            <ActionButton
              testId="rotate-node-credential"
              label="Rotate credential"
              icon={RotateCw}
              busy={action === "rotate"}
              onClick={() => void onRotate()}
            />
            <ActionButton
              testId="revoke-node"
              label="Відкликати"
              icon={Ban}
              busy={action === "revoke"}
              danger
              onClick={() => void onChangeState("revoke")}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] px-3 py-3 text-center">
      <p className="text-lg font-semibold text-white">{value}</p>
      <p className="mt-1 text-[9px] text-slate-500">{label}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-2">
      <span className="text-[10px] font-semibold tracking-[0.12em] text-slate-500 uppercase">{label}</span>
      {children}
    </label>
  );
}

function Meta({
  icon: Icon,
  label,
  value,
  valueClass = "text-slate-300",
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.055] bg-white/[0.018] p-3">
      <p className="flex items-center gap-2 text-[9px] text-slate-600">
        <Icon className="h-3.5 w-3.5 text-cyan-300" />
        {label}
      </p>
      <p className={`mt-2 text-[10px] leading-5 break-all ${valueClass}`}>{value}</p>
    </div>
  );
}

function ActionButton({
  testId,
  label,
  icon: Icon,
  busy,
  danger = false,
  onClick,
}: {
  testId: string;
  label: string;
  icon: typeof CheckCircle2;
  busy: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-[10px] font-semibold transition disabled:opacity-45 ${
        danger
          ? "border-red-300/20 bg-red-400/[0.06] text-red-200 hover:bg-red-400/[0.1]"
          : "border-white/[0.08] bg-white/[0.025] text-slate-200 hover:border-cyan-300/25 hover:text-cyan-200"
      }`}
      data-testid={testId}
    >
      {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </button>
  );
}

function Status({
  icon: Icon,
  title,
  detail,
  spin = false,
}: {
  icon: typeof Network;
  title: string;
  detail: string;
  spin?: boolean;
}) {
  return (
    <div className="grid min-h-64 place-items-center p-8 text-center">
      <div>
        <Icon className={`mx-auto h-8 w-8 text-slate-600 ${spin ? "animate-spin" : ""}`} />
        <p className="mt-4 text-sm font-semibold text-slate-200">{title}</p>
        <p className="mt-2 max-w-lg text-[11px] leading-5 text-slate-500">{detail}</p>
      </div>
    </div>
  );
}
