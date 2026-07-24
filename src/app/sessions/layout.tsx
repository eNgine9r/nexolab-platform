import type { ReactNode } from "react";

import { SessionsShell } from "@/components/sessions/sessions-shell";

export default function SessionsLayout({ children }: { children: ReactNode }) {
  return <SessionsShell>{children}</SessionsShell>;
}
