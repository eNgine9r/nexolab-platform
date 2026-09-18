import type { ReactNode } from "react";

interface OverviewWorkspaceLayoutProps {
  primary: ReactNode;
  attention: ReactNode;
  supporting: ReactNode;
}

export function OverviewWorkspaceLayout({ primary, attention, supporting }: OverviewWorkspaceLayoutProps) {
  return (
    <>
      <section
        className="mt-3 grid min-w-0 grid-cols-1 items-start gap-3"
        data-testid="overview-command-grid"
        aria-label="Основний стан системи"
      >
        <div className="min-w-0" data-testid="overview-primary-workspace">
          {primary}
        </div>
        <aside
          className="min-w-0"
          data-testid="overview-attention-workspace"
          aria-label="Потребує уваги"
        >
          {attention}
        </aside>
      </section>
      <section
        className="mt-3 min-w-0"
        data-testid="overview-secondary-grid"
        aria-label="Стан інфраструктури"
      >
        {supporting}
      </section>
    </>
  );
}
