import type { ReactNode } from "react";

interface OverviewWorkspaceLayoutProps {
  primary: ReactNode;
  attention: ReactNode;
  supporting: ReactNode;
}

export function OverviewWorkspaceLayout({ primary, attention, supporting }: OverviewWorkspaceLayoutProps) {
  return (
    <section
      className="mt-4 grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-12"
      data-testid="overview-command-grid"
      aria-label="Основний стан системи"
    >
      <div className="min-w-0 xl:col-span-8" data-testid="overview-primary-workspace">
        {primary}
      </div>
      {attention || supporting ? (
        <div className="grid min-w-0 gap-4 xl:col-span-4" data-testid="overview-insights-column">
          {attention ? (
            <aside className="min-w-0" data-testid="overview-attention-workspace" aria-label="Потребує уваги">
              {attention}
            </aside>
          ) : null}
          {supporting ? (
            <section
              className="min-w-0"
              data-testid="overview-secondary-grid"
              aria-label="Стан інфраструктури"
            >
              {supporting}
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
