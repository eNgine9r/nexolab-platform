import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReportOutputScreen } from "./report-output-screen";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/hooks/use-dashboard-security", () => ({
  useDashboardSecurity: () => ({ mode: "demo", state: "configuration", error: null }),
}));

describe("Report route localization", () => {
  it("explains the live-data requirement in Ukrainian without pretending demo reports exist", () => {
    render(<ReportOutputScreen reportId="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" />);

    expect(screen.getByText("NEXOLAB · доступ до звітів")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Деталі звіту недоступні" })).toBeVisible();
    expect(screen.getByText("Готові звіти доступні лише в робочому режимі з локальним API.")).toBeVisible();
  });
});
