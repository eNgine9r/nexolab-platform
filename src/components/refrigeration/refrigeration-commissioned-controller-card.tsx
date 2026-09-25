"use client";

import Link from "next/link";
import { CheckCircle2, RadioTower } from "lucide-react";

import type { CommissionedControllerAssociation } from "@/features/equipment/commissioned-controller-association";

export function RefrigerationCommissionedControllerCard({
  association,
}: {
  association: CommissionedControllerAssociation;
}) {
  const { session, profile } = association;
  return (
    <section
      className="rounded-2xl border border-emerald-300/15 bg-emerald-400/[0.04] p-5"
      data-testid="commissioned-controller-association"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl border border-emerald-300/15 bg-emerald-400/10">
            <RadioTower className="h-5 w-5 text-emerald-200" />
          </span>
          <div>
            <p className="text-[9px] tracking-[0.16em] text-emerald-300 uppercase">Контролер вітрини</p>
            <h2 className="mt-1 text-base font-semibold text-white">{profile.displayName}</h2>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300/20 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-medium text-emerald-100">
          <CheckCircle2 className="h-3.5 w-3.5" /> Перевірено · моніторинг вимкнено
        </span>
      </div>

      <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <Info label="Node" value={session.nodeId ?? "—"} />
        <Info label="Bus" value={session.busId ?? "—"} />
        <Info label="Modbus Unit" value={session.unitId === null ? "—" : String(session.unitId)} />
        <Info label="Profile" value={profile.version} />
      </dl>

      <p className="mt-4 rounded-xl border border-cyan-300/10 bg-cyan-400/[0.035] p-3 text-xs leading-5 text-slate-300">
        Контролер додано до реєстру після bounded read-only перевірки. Production polling і live KPI ще не
        активовані; значення контролера тут не підміняються mock-даними.
      </p>
      <Link
        href={`/equipment/onboarding/${encodeURIComponent(session.id)}`}
        className="mt-4 inline-flex text-xs font-semibold text-cyan-200 hover:text-cyan-100"
      >
        Відкрити картку підключення →
      </Link>
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-[#06142a]/60 px-3 py-2">
      <dt className="text-[9px] tracking-[0.12em] text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 font-medium break-all text-slate-200">{value}</dd>
    </div>
  );
}
