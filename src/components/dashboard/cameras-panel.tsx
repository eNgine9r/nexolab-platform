import Link from "next/link";
import { Camera, ArrowUpRight, VideoOff } from "lucide-react";

import { readCameraInventory } from "@/features/cameras/domain";

export function CamerasPanel() {
  const inventory = readCameraInventory();

  return (
    <div className="p-3 sm:p-4">
      {inventory.items.length === 0 ? (
        <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-cyan-300/20 bg-[#0b2749]/65 p-5 text-center">
          <div>
            <VideoOff className="mx-auto h-7 w-7 text-cyan-300" />
            <p className="mt-3 text-sm font-medium text-slate-100">Камери не налаштовані</p>
            <p className="mt-1 max-w-sm text-xs leading-5 text-slate-400">
              Декоративні сцени не показуються як LIVE. Потрібен перевірений локальний inventory і безпечний media contract.
            </p>
            <Link
              href="/cameras"
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs text-cyan-200 hover:border-cyan-300/30"
            >
              Відкрити стан камер
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {inventory.items.slice(0, 6).map((camera) => (
            <Link
              key={camera.id}
              href="/cameras"
              className="rounded-xl border border-white/[0.07] bg-[#0b2749] p-3 text-left hover:border-cyan-300/25"
            >
              <div className="flex items-center gap-2">
                <Camera className="h-3.5 w-3.5 text-cyan-300" />
                <span className="truncate text-xs font-medium text-slate-200">{camera.name}</span>
              </div>
              <p className="mt-2 text-[10px] text-slate-500">{camera.id} · {camera.state}</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
