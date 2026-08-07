"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, LoaderCircle, Snowflake } from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { RefrigerationDetailScreen } from "@/components/refrigeration/refrigeration-detail-screen";
import type { RefrigerationEquipment } from "@/data/refrigeration";
import { createRefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";
import type { RefrigerationStructuralSnapshot } from "@/features/refrigeration/structural-snapshot-repository";

export function RefrigerationEquipmentRoute({
  equipmentId,
  initialEquipment,
}: {
  equipmentId: string;
  initialEquipment: RefrigerationEquipment | null;
}) {
  const runtime = useMemo(() => createRefrigerationEquipmentRuntime(), []);
  const [equipment, setEquipment] = useState<RefrigerationEquipment | null>(initialEquipment);
  const [snapshot, setSnapshot] = useState<RefrigerationStructuralSnapshot | null>(null);
  const [loading, setLoading] = useState(
    runtime.repository !== null && (runtime.mode === "live" || initialEquipment === null),
  );
  const [error, setError] = useState<string | null>(runtime.error);

  useEffect(() => {
    const structural = runtime.structuralSnapshotRepository;
    const repository = runtime.repository;
    if (!structural && !repository) return;

    let active = true;
    const snapshotRequest: Promise<RefrigerationStructuralSnapshot | null> = structural
      ? structural.get(equipmentId)
      : Promise.resolve(null);
    const equipmentRequest = repository?.get(equipmentId) ?? Promise.resolve(null);

    void Promise.all([equipmentRequest, snapshotRequest])
      .then(([loadedEquipment, loadedSnapshot]) => {
        if (!active) return;
        setEquipment(loadedSnapshot?.equipment ?? loadedEquipment);
        if (loadedSnapshot) setSnapshot(loadedSnapshot);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Обладнання не знайдено.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [equipmentId, runtime.repository, runtime.structuralSnapshotRepository]);

  if (equipment) {
    return <RefrigerationDetailScreen equipment={equipment} initialSnapshot={snapshot} />;
  }

  return <EquipmentRouteState loading={loading} error={error} />;
}

function EquipmentRouteState({ loading, error }: { loading: boolean; error: string | null }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Холодильне обладнання"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar title="Холодильне обладнання" onMenuOpen={() => setSidebarOpen(true)} />
        <main className="grid min-h-[calc(100vh-72px)] place-items-center p-4">
          <section className="w-full max-w-md rounded-2xl border border-white/[0.08] bg-[#091a31]/90 p-8 text-center">
            {loading ? (
              <>
                <LoaderCircle className="mx-auto h-7 w-7 animate-spin text-cyan-300" />
                <h1 className="mt-4 text-sm font-semibold text-white">Завантаження обладнання</h1>
                <p className="mt-2 text-xs text-slate-500">Отримуємо паспорт і схему.</p>
              </>
            ) : (
              <>
                <Snowflake className="mx-auto h-8 w-8 text-slate-600" />
                <h1 className="mt-4 text-sm font-semibold text-white">Обладнання недоступне</h1>
                <p role="alert" className="mt-2 text-xs leading-5 text-slate-500">
                  {error ?? "Запис видалено або він не належить поточній організації."}
                </p>
                <Link
                  href="/refrigeration"
                  className="mx-auto mt-5 inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300 transition hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
                >
                  <ArrowLeft className="h-4 w-4" />
                  До каталогу
                </Link>
              </>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
