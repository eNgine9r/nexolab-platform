import { Suspense } from "react";

import { LiveScreen } from "@/components/live/live-screen";

export default function LivePage() {
  return (
    <Suspense
      fallback={
        <main className="grid min-h-screen place-items-center bg-[#06142a] text-sm text-slate-400">
          Підготовка Live Data workspace…
        </main>
      }
    >
      <LiveScreen />
    </Suspense>
  );
}
