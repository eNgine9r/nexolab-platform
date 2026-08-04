import { Suspense } from "react";

import { EquipmentLayoutsScreen } from "@/components/equipment-layouts/equipment-layouts-screen";

export default function EquipmentLayoutsPage() {
  return (
    <Suspense
      fallback={
        <main className="grid min-h-screen place-items-center bg-[#06142a] text-sm text-slate-400">
          Підготовка каталогу схем обладнання…
        </main>
      }
    >
      <EquipmentLayoutsScreen />
    </Suspense>
  );
}
