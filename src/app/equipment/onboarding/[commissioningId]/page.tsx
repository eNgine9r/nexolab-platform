import { Suspense } from "react";

import { CommissioningWizardScreen } from "@/components/equipment/commissioning-wizard-screen";

export default async function EquipmentOnboardingPage({
  params,
}: {
  params: Promise<{ commissioningId: string }>;
}) {
  const { commissioningId } = await params;
  return (
    <Suspense
      fallback={
        <main className="grid min-h-screen place-items-center bg-[#06142a] text-sm text-slate-400">
          Відкриття чернетки…
        </main>
      }
    >
      <CommissioningWizardScreen commissioningId={commissioningId} />
    </Suspense>
  );
}
