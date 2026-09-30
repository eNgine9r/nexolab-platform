import type { ReactNode } from "react";
import { RefrigerationSecurityBoundary } from "@/components/refrigeration/refrigeration-security-boundary";

export default function RefrigerationLayout({ children }: { children: ReactNode }) {
  return <RefrigerationSecurityBoundary>{children}</RefrigerationSecurityBoundary>;
}
