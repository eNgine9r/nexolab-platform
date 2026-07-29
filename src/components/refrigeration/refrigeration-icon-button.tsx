import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type IconButtonTone = "default" | "accent" | "success" | "info" | "danger";
type IconButtonSize = "sm" | "md" | "lg";

type RefrigerationIconButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "children" | "title" | "aria-label"
> & {
  label: string;
  children: ReactNode;
  tone?: IconButtonTone;
  size?: IconButtonSize;
};

const toneClasses: Record<IconButtonTone, string> = {
  default:
    "border-white/10 bg-white/[0.035] text-slate-400 enabled:hover:border-white/20 enabled:hover:bg-white/[0.065] enabled:hover:text-white",
  accent:
    "border-cyan-300/25 bg-cyan-400/15 text-cyan-100 enabled:hover:border-cyan-300/40 enabled:hover:bg-cyan-400/20",
  success:
    "border-emerald-400/25 bg-emerald-500/15 text-emerald-200 enabled:hover:border-emerald-300/40 enabled:hover:bg-emerald-500/20",
  info: "border-blue-400/25 bg-blue-500/15 text-blue-200 enabled:hover:border-blue-300/40 enabled:hover:bg-blue-500/20",
  danger:
    "border-rose-400/20 bg-rose-500/10 text-rose-300 enabled:hover:border-rose-300/40 enabled:hover:bg-rose-500/15",
};

const sizeClasses: Record<IconButtonSize, string> = {
  sm: "h-8 w-8 rounded-lg",
  md: "h-10 w-10 rounded-xl",
  lg: "h-11 w-11 rounded-xl",
};

export const RefrigerationIconButton = forwardRef<
  HTMLButtonElement,
  RefrigerationIconButtonProps
>(function RefrigerationIconButton(
  { label, children, tone = "default", size = "md", className = "", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={`grid shrink-0 place-items-center border transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-35 ${sizeClasses[size]} ${toneClasses[tone]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
});
