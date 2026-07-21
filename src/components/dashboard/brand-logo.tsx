import { Snowflake } from "lucide-react";

interface BrandLogoProps {
  compact?: boolean;
}

export function BrandLogo({ compact = false }: BrandLogoProps) {
  return (
    <div className="flex items-center gap-3" aria-label="NEXOLAB">
      <div className="relative grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-cyan-300/25 bg-[linear-gradient(145deg,rgba(0,119,255,.22),rgba(11,29,58,.95))] shadow-[0_0_26px_rgba(0,119,255,.16)]">
        <svg viewBox="0 0 44 44" className="h-9 w-9" aria-hidden="true">
          <path
            d="M7 10.5 18 6l17 3.5v25L18 38 7 33.5v-23Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            className="text-slate-100"
          />
          <path
            d="M18 6v32M26 8v28M18 17h17M18 26h17M7 23h11"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="text-cyan-300"
          />
          <path
            d="M35 14h4m-4 8h5m-5 8h4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="text-blue-400"
          />
          <circle cx="40" cy="14" r="1.7" className="fill-cyan-300" />
          <circle cx="41" cy="22" r="1.7" className="fill-blue-400" />
          <circle cx="40" cy="30" r="1.7" className="fill-lime-400" />
        </svg>
        <Snowflake className="absolute top-2 left-1.5 h-2.5 w-2.5 text-cyan-200" strokeWidth={2.2} />
      </div>
      {!compact && (
        <div>
          <div className="text-[21px] font-semibold tracking-[0.16em] text-white">
            NEXO<span className="text-blue-400">LAB</span>
          </div>
          <p className="mt-0.5 text-[8px] tracking-[0.17em] text-slate-400 uppercase">
            Cold Chain &amp; Smart Locker
          </p>
        </div>
      )}
    </div>
  );
}
