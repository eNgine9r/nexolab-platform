import { Box, Camera, Cpu, Snowflake } from "lucide-react";

const zones = [
  { label: "Кліматична камера", value: "4.2 °C", x: "11%", y: "18%", icon: Snowflake, tone: "green" },
  { label: "Холодильні вітрини", value: "2.1 °C", x: "66%", y: "13%", icon: Snowflake, tone: "green" },
  { label: "Центральний вузол", value: "Pi-06", x: "48%", y: "47%", icon: Cpu, tone: "blue" },
  { label: "Зона поштоматів", value: "5.1 °C", x: "9%", y: "70%", icon: Box, tone: "green" },
  { label: "Зона камер", value: "22.4 °C", x: "67%", y: "70%", icon: Camera, tone: "amber" },
] as const;

export function LabMap() {
  return (
    <div className="p-3 sm:p-4">
      <div className="relative min-h-[238px] overflow-hidden rounded-xl border border-blue-400/10 bg-[#061831]">
        <div className="lab-grid absolute inset-0 opacity-70" />
        <svg viewBox="0 0 640 290" className="absolute inset-0 h-full w-full opacity-45" aria-hidden="true">
          <g fill="none" stroke="#0077ff" strokeWidth="1.2">
            <path d="M28 28H248V112H315V31H606V142H545V261H329V213H187V263H28Z" />
            <path d="M98 28v84m80-84v84m137-81v111m94-111v84m83-84v111M28 142h159m0-30v101m142-71h216M98 213h89m142 0h216" />
            <path
              d="M210 112h105m-39 0v30m133-30h136m-53 30v71M187 178h142m-82-36v71"
              strokeDasharray="4 4"
            />
          </g>
          <g fill="#00c6e0" opacity=".35">
            {[52, 90, 142, 204, 272, 350, 430, 510, 582].map((x, index) => (
              <circle key={x} cx={x} cy={index % 2 === 0 ? 82 : 224} r="2.4" />
            ))}
          </g>
        </svg>
        <div className="absolute top-3 left-3 z-10 flex flex-col gap-1">
          {["+", "−", "◎"].map((item) => (
            <button
              key={item}
              className="grid h-7 w-7 place-items-center rounded-lg border border-white/[0.08] bg-[#0a2344]/90 text-[12px] text-slate-300 transition hover:border-blue-400/30 hover:text-white"
            >
              {item}
            </button>
          ))}
        </div>
        {zones.map((zone) => {
          const Icon = zone.icon;
          return (
            <button
              key={zone.label}
              className="absolute z-10 min-w-[122px] rounded-xl border border-blue-300/15 bg-[#0b2445]/90 p-2.5 text-left shadow-[0_8px_26px_rgba(0,0,0,.22)] backdrop-blur-sm transition hover:-translate-y-0.5 hover:border-cyan-300/30"
              style={{ left: zone.x, top: zone.y }}
            >
              <div className="flex items-center gap-1.5 text-[8px] text-slate-400">
                <Icon className="h-3 w-3 text-cyan-300" />
                {zone.label}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold text-slate-100">
                <span
                  className={`h-2 w-2 rounded-full ${zone.tone === "amber" ? "bg-amber-400" : zone.tone === "blue" ? "bg-blue-400" : "bg-emerald-400"}`}
                />
                {zone.value}
              </div>
            </button>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-4 text-[8px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-emerald-400" />
          Норма
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-amber-400" />
          Попередження
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-red-400" />
          Тривога
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-2 w-2 rounded-full bg-slate-500" />
          Offline
        </span>
      </div>
    </div>
  );
}
