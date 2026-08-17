import type { ReactNode } from "react";

interface OverviewWorkspaceLayoutProps {
  primary: ReactNode;
  secondaryStart: ReactNode;
  secondaryEnd: ReactNode;
}

export function OverviewWorkspaceLayout({
  primary,
  secondaryStart,
  secondaryEnd,
}: OverviewWorkspaceLayoutProps) {
  return (
    <>
      <section
        className="mt-3 min-w-0"
        data-testid="overview-primary-workspace"
        aria-label="Основний графік телеметрії"
      >
        {primary}
      </section>
      <section
        className="mt-3 grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2"
        data-testid="overview-secondary-grid"
        aria-label="Додатковий стан системи"
      >
        {secondaryStart}
        {secondaryEnd}
      </section>
    </>
  );
}
