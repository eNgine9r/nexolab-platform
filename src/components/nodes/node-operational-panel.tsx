import { Activity, Clock3, Database, RadioTower, ServerCog, TriangleAlert } from "lucide-react";

import type { NodeAvailability, NodeOperationalState } from "@/lib/nodes/types";

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

function formatAge(value: number | null): string {
  if (value === null) return "—";
  if (value < 60) return `${Math.round(value)} с`;
  if (value < 3600) return `${Math.floor(value / 60)} хв ${Math.round(value % 60)} с`;
  return `${Math.floor(value / 3600)} год ${Math.floor((value % 3600) / 60)} хв`;
}

export function NodeOperationalPanel({ state }: { state: NodeOperationalState | null }) {
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
