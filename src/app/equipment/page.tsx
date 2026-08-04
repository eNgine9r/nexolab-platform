import { Suspense } from "react";

import { EquipmentRegistryScreen } from "@/components/equipment/equipment-registry-screen";

export default function EquipmentPage() {
  return (
    <Suspense
      fallback={
        <main
          role="status"
          aria-live="polite"
          className="grid min-h-screen place-items-center bg-[#06142a] text-sm text-slate-400"
        >
          Підготовка реєстру обладнання…
        </main>
      }
    >
      <EquipmentRegistryScreen />
    </Suspense>
  );
}
