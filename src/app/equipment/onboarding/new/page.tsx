import { Suspense } from "react";

import { CommissioningWizardScreen } from "@/components/equipment/commissioning-wizard-screen";

export default function NewEquipmentOnboardingPage() {
  return (
    <Suspense
      fallback={
        <main className="grid min-h-screen place-items-center bg-[#06142a] text-sm text-slate-400">
          Підготовка чернетки…
        </main>
      }
    >
      <CommissioningWizardScreen commissioningId={null} />
    </Suspense>
  );
}
