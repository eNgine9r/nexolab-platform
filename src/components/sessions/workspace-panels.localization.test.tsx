import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LaboratorySession } from "@/lib/sessions/types";
import { SessionHero, StageTimeline, WorkspaceError, WorkspaceLoading } from "./workspace-panels";

const session = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  session_number: "LAB-001",
  title: "Тестове випробування",
  test_object: "Холодильна вітрина",
  model: null,
  serial_number: null,
  state: "completed",
  node_id: "node-01",
  active_limit_version: 1,
  active_config_snapshot_id: null,
  started_at: null,
} as LaboratorySession;

describe("Sessions localization", () => {
  it("shows Ukrainian hero metrics and read-only/offline states without changing session data", () => {
    render(<SessionHero session={session} connectionState="offline" clock={0} readOnly />);

    expect(screen.getByText("Минуло часу")).toBeVisible();
    expect(screen.getByText("Вузол")).toBeVisible();
    expect(screen.getByText("Знімок конфігурації")).toBeVisible();
    expect(screen.getByText("Очікується")).toBeVisible();
    expect(screen.getByText("Лише перегляд")).toBeVisible();
    expect(screen.getByText(/Офлайн · кешовані дані/)).toBeVisible();
    expect(screen.getByText("LAB-001")).toBeVisible();
  });

  it("shows Ukrainian stage options while preserving protocol stage type values", () => {
    render(
      <StageTimeline
        stages={[]}
        currentStageId={null}
        readOnly={false}
        mutating={false}
        onAdvance={vi.fn()}
      />,
    );

    expect(screen.getByText("Хронологія етапів")).toBeVisible();
    const select = screen.getByRole("combobox");
    expect(screen.getByRole("option", { name: "Відтавання" })).toHaveValue("defrost");
    expect(screen.getByRole("option", { name: "Підготовка" })).toHaveValue("preparation");
    expect(select).toHaveValue("main_test");
  });

  it("shows a localized loading and error state with a working retry control", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<WorkspaceLoading />);
    expect(screen.getByText("Завантаження фактичних даних випробування…")).toBeVisible();

    rerender(<WorkspaceError message="Мережа недоступна" onRetry={onRetry} />);
    expect(screen.getByText("Сторінка випробування недоступна")).toBeVisible();
    screen.getByRole("button", { name: "Повторити" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
