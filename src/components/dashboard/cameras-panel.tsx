import { Camera, Maximize2 } from "lucide-react";

const cameras = [
  { id: "CAM-01", name: "Зона складу", variant: 1 },
  { id: "CAM-02", name: "Вхідні двері", variant: 2 },
  { id: "CAM-03", name: "Лабораторія 1", variant: 3 },
  { id: "CAM-04", name: "Лабораторія 2", variant: 4 },
  { id: "CAM-05", name: "Клімат. камера", variant: 5 },
  { id: "CAM-06", name: "Поштомат зона", variant: 6 },
];

export function CamerasPanel() {
  return (
    <div className="grid grid-cols-2 gap-2 p-3 sm:p-4">
      {cameras.map((camera) => (
        <button
          key={camera.id}
          className="group relative aspect-[1.75] overflow-hidden rounded-xl border border-white/[0.07] bg-[#0b2749] text-left"
        >
          <div className={`camera-scene absolute inset-0 camera-scene-${camera.variant}`} />
          <div className="absolute inset-0 bg-gradient-to-t from-[#041226]/95 via-transparent to-cyan-300/[0.04]" />
          <div className="absolute top-2 left-2 flex items-center gap-1 rounded-md bg-black/35 px-1.5 py-1 text-[7px] font-semibold text-emerald-300 backdrop-blur-sm">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            LIVE
          </div>
          <Maximize2 className="absolute top-2 right-2 h-3 w-3 text-white/0 transition group-hover:text-white/80" />
          <div className="absolute inset-x-0 bottom-0 flex items-center gap-1.5 px-2 py-1.5">
            <Camera className="h-2.5 w-2.5 text-cyan-300" />
            <span className="truncate text-[7px] font-medium text-slate-200">
              {camera.id} · {camera.name}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
