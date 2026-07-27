"use client";

import { useEffect, useState } from "react";
import { Activity, Clock3, Database, RadioTower, ServerCog, ShieldCheck, TriangleAlert } from "lucide-react";

import { createNodeApiClient } from "@/lib/nodes/api-client";
import type {
  BrokerDesiredState,
  BrokerSynchronizationState,
  NodeAvailability,
  NodeBrokerControl,
  NodeOperationalState,
} from "@/lib/nodes/types";

function availabilityLabel(value: NodeAvailability): string {
  return {
    online: "Online",
    offline: "Offline",
    stale: "Stale heartbeat",
    unknown: "Немає operational evidence",
  }[value];
}

function availabilityClass(value: NodeAvailability): string {
  if (value === "online") return "border-emerald-300/20 bg-emerald-400/[0.07] text-emerald-200";
  if (value === "offline") return "border-red-300/20 bg-red-400/[0.07] text-red-200";
  if (value === "stale") return "border-amber-300/20 bg-amber-400/[0.07] text-amber-200";
  return "border-slate-400/15 bg-slate-400/[0.05] text-slate-400";
}

function brokerLabel(value: BrokerSynchronizationState): string {
  return {
    disabled: "Control plane вимкнений",
    unknown: "Немає broker evidence",
    pending: "Очікує обробки",
    processing: "Виконується",
    retrying: "Повторна спроба",
    applied: "Синхронізовано",
    failed: "Помилка синхронізації",
    out_of_sync: "Broker drift",
  }[value];
}

function brokerClass(value: BrokerSynchronizationState): string {
  if (value === "applied") return "border-emerald-300/20 bg-emerald-400/[0.07] text-emerald-200";
  if (value === "pending" || value === "processing") {
    return "border-cyan-300/20 bg-cyan-400/[0.07] text-cyan-200";
  }
  if (value === "retrying") return "border-amber-300/20 bg-amber-400/[0.07] text-amber-200";
  if (value === "failed" || value === "out_of_sync") {
    return "border-red-300/20 bg-red-400/[0.07] text-red-200";
  }
  return "border-slate-400/15 bg-slate-400/[0.05] text-slate-400";
}

function desiredLabel(value: BrokerDesiredState): string {
  return {
    provisioned: "Client provisioned",
    enabled: "Client enabled",
    disabled: "Client disabled",
    deleted: "Client deleted",
  }[value];
}

function formatAge(value: number | null): string {
  if (value === null) return "—";
  if (value < 60) return `${Math.round(value)} с`;
  if (value < 3600) return `${Math.floor(value / 60)} хв ${Math.round(value % 60)} с`;
  return `${Math.floor(value / 3600)} год ${Math.floor((value % 3600) / 60)} хв`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

export function NodeOperationalPanel({ state }: { state: NodeOperationalState | null }) {
  return (
    <div className="space-y-3">
      <OperationalStatePanel state={state} />
      {state ? <NodeBrokerControlPanel nodeId={state.node_id} /> : null}
    </div>
  );
}

function OperationalStatePanel({ state }: { state: NodeOperationalState | null }) {
  if (!state) {
    return (
      <section
        className="rounded-2xl border border-white/[0.06] bg-white/[0.018] p-4"
        data-testid="node-operational-state"
      >
        <div className="flex items-start gap-3">
          <RadioTower className="mt-0.5 h-4 w-4 text-slate-600" />
          <div>
            <p className="text-[10px] font-semibold text-slate-300">Operational streams</p>
            <p className="mt-1 text-[10px] leading-5 text-slate-500">
              Health heartbeat і retained status ще не зафіксовані для цього вузла.
            </p>
          </div>
        </div>
      </section>
    );
  }

  const health = state.latest_health;
  const status = state.latest_status;

  return (
    <section
      className="space-y-4 rounded-2xl border border-cyan-300/[0.09] bg-cyan-400/[0.025] p-4"
      data-testid="node-operational-state"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="flex items-center gap-2 text-[10px] font-semibold text-slate-200">
            <RadioTower className="h-4 w-4 text-cyan-300" />
            Health &amp; retained status
          </p>
          <p className="mt-1 text-[9px] text-slate-500">
            Server-derived state · stale after {state.stale_after_seconds} seconds
          </p>
        </div>
        <span
          className={`rounded-xl border px-3 py-2 text-[10px] font-semibold ${availabilityClass(state.availability)}`}
          data-testid="node-availability"
        >
          {availabilityLabel(state.availability)}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <OperationalMetric
          icon={Clock3}
          label="Heartbeat age"
          value={formatAge(state.heartbeat_age_seconds)}
        />
        <OperationalMetric
          icon={Database}
          label="Offline queue"
          value={health ? `${health.queue_depth} events` : "—"}
        />
        <OperationalMetric
          icon={Activity}
          label="Samples total"
          value={health ? new Intl.NumberFormat("uk-UA").format(health.samples_total) : "—"}
        />
        <OperationalMetric
          icon={ServerCog}
          label="Agent build"
          value={
            health ? `${health.software_version} · ${health.device_mode}` : (status?.software_version ?? "—")
          }
        />
      </div>

      {state.degraded_reason ? (
        <div
          className="flex items-start gap-2 rounded-xl border border-amber-300/15 bg-amber-400/[0.05] p-3 text-[10px] leading-5 text-amber-100/80"
          data-testid="node-degraded-reason"
        >
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
          {state.degraded_reason}
        </div>
      ) : null}

      <div className="grid gap-2 text-[9px] text-slate-500 sm:grid-cols-2">
        <p>
          Health sequence: <span className="font-mono text-slate-300">{health?.node_sequence ?? "—"}</span>
        </p>
        <p>
          Status sequence: <span className="font-mono text-slate-300">{status?.node_sequence ?? "—"}</span>
        </p>
        <p>
          Last sample: <span className="text-slate-300">{health?.last_sample_at ?? "—"}</span>
        </p>
        <p>
          Retained event: <span className="text-slate-300">{status?.reason ?? "—"}</span>
        </p>
      </div>
    </section>
  );
}

function NodeBrokerControlPanel({ nodeId }: { nodeId: string }) {
  const [control, setControl] = useState<NodeBrokerControl | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const result = await createNodeApiClient().getBrokerControl(nodeId, controller.signal);
        setControl(result);
        setError(null);
      } catch (nextError) {
        if (!controller.signal.aborted) {
          setError(nextError instanceof Error ? nextError.message : "Broker reconciliation недоступний.");
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 5_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [nodeId]);

  const latest = control?.latest_command ?? null;
  const synchronization = control?.synchronization ?? "unknown";

  return (
    <section
      className="space-y-4 rounded-2xl border border-white/[0.065] bg-white/[0.018] p-4"
      data-testid="node-broker-control"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="flex items-center gap-2 text-[10px] font-semibold text-slate-200">
            <ShieldCheck className="h-4 w-4 text-cyan-300" />
            MQTT broker reconciliation
          </p>
          <p className="mt-1 text-[9px] text-slate-500">
            PostgreSQL outbox → Mosquitto Dynamic Security · refresh 5 s
          </p>
        </div>
        <span
          className={`rounded-xl border px-3 py-2 text-[10px] font-semibold ${brokerClass(synchronization)}`}
          data-testid="node-broker-synchronization"
        >
          {brokerLabel(synchronization)}
        </span>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-300/15 bg-red-400/[0.05] p-3 text-[10px] text-red-200">
          {error}
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <OperationalMetric
          icon={ShieldCheck}
          label="Desired broker state"
          value={control ? desiredLabel(control.desired_state) : "Завантаження…"}
        />
        <OperationalMetric
          icon={Activity}
          label="Latest command"
          value={latest ? `${latest.operation} · ${latest.state}` : "—"}
        />
        <OperationalMetric
          icon={Database}
          label="Attempts"
          value={latest ? new Intl.NumberFormat("uk-UA").format(latest.attempts) : "—"}
        />
        <OperationalMetric icon={Clock3} label="Last update" value={formatDate(latest?.updated_at ?? null)} />
      </div>

      {latest?.error_detail ? (
        <div className="flex items-start gap-2 rounded-xl border border-red-300/15 bg-red-400/[0.05] p-3 text-[10px] leading-5 text-red-100/80">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-300" />
          <span>
            {latest.error_code ? `${latest.error_code}: ` : ""}
            {latest.error_detail}
          </span>
        </div>
      ) : null}

      {control && control.commands.length > 0 ? (
        <div className="space-y-2 border-t border-white/[0.055] pt-3">
          <p className="text-[9px] font-semibold tracking-[0.12em] text-slate-600 uppercase">
            Command history
          </p>
          {control.commands.slice(0, 5).map((command) => (
            <div
              key={command.id}
              className="grid gap-1 rounded-xl border border-white/[0.045] bg-slate-950/10 px-3 py-2 text-[9px] sm:grid-cols-[100px_90px_70px_minmax(0,1fr)]"
            >
              <span className="font-mono text-cyan-200">{command.operation}</span>
              <span className={brokerClass(command.state)}>{command.state}</span>
              <span className="text-slate-500">try {command.attempts}</span>
              <span className="text-right text-slate-500">{formatDate(command.updated_at)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function OperationalMetric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.055] bg-slate-950/15 p-3">
      <p className="flex items-center gap-2 text-[9px] text-slate-600">
        <Icon className="h-3.5 w-3.5 text-cyan-300" />
        {label}
      </p>
      <p className="mt-2 text-[10px] leading-5 break-all text-slate-300">{value}</p>
    </div>
  );
}
