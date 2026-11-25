import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportPage, TestReport } from "@/lib/reports/types";
import { ReportsWorkspace } from "./reports-workspace";

const mock = vi.hoisted(() => ({
  listReports: vi.fn(),
  loadContext: vi.fn(async () => ({ requested: null, sessions: [], error: null })),
}));

vi.mock("@/hooks/use-display-time-zone", () => ({
  useDisplayTimeZone: () => "Europe/Kyiv",
}));
vi.mock("@/features/security/supabase-auth", () => ({
  createRuntimeCredentialProvider: () => async () => ({ organizationId: "org-a" }),
}));
vi.mock("@/features/security/security-session", () => ({
  createAuthenticatedFetch: () => fetch,
  HttpSecuritySessionClient: class {
    getSession() {
      return Promise.resolve({ ok: false });
    }
  },
  hasPermission: () => false,
}));
vi.mock("@/lib/reports/runtime-config", () => ({
  getReportsApiBaseUrl: () => "http://127.0.0.1:8084",
}));
vi.mock("@/lib/reports/api-client", () => ({
  createReportApiClient: () => ({
    listReports: mock.listReports,
  }),
  createReportIdempotencyKey: () => "test-key",
}));
vi.mock("@/lib/reports/session-navigation", () => ({
  NO_REPORT_SESSION_TARGET: { kind: "none" },
  loadReportSessionContext: mock.loadContext,
}));
vi.mock("@/lib/sessions/api-client", () => ({
  createSessionApiClient: () => ({}),
}));
vi.mock("@/components/reports/report-telemetry-selector", () => ({
  ReportTelemetrySelector: () => null,
}));

const example = {
  id: "report-101",
  organization_id: "org-a",
  session_id: "session-101",
  session_summary: {
    session_number: "NX-101",
    title: "Температурне випробування промислової холодильної вітрини",
    test_object: "Вітрина з довгою назвою",
  },
  config_snapshot_id: "snapshot-101",
  version: 2,
  session_state: "completed",
  source_started_at: "2026-11-09T07:00:00.000Z",
  source_ended_at: "2026-11-09T08:00:00.000Z",
  source_sha256: "a".repeat(64),
  manifest_sha256: "b".repeat(64),
  generator_version: "v1",
  generated_by: "operator",
  generated_at: "2026-11-09T08:30:00.000Z",
  created_at: "2026-11-09T08:30:00.000Z",
  artifacts: [],
} satisfies TestReport;

const archived: TestReport = {
  ...example,
  id: "report-102",
  session_id: "session-102",
  session_summary: {
    session_number: "NX-102",
    title: "Тест пакувальної камери",
    test_object: "Камера B",
  },
  session_state: "archived",
  version: 1,
};

function page(items: TestReport[]): ReportPage {
  return { items, count: items.length, limit: 200, offset: 0, next_offset: null };
}

beforeEach(() => {
  mock.listReports.mockReset().mockResolvedValue(page([example, archived]));
  mock.loadContext.mockClear();
});

describe("Reports operator workspace", () => {
  it("shows localized status and truthful loaded-selection counters", async () => {
    render(<ReportsWorkspace />);
    const selected = await screen.findByRole("button", { name: /NX-101/ });
    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /NX-102/ })).toHaveTextContent("Архів");
    expect(selected).toHaveTextContent("Завершена");
    expect(screen.getByLabelText("Версій: 2")).toBeVisible();
    expect(screen.getByLabelText("Сесій: 2")).toBeVisible();
    expect(screen.getByText("Завантажена вибірка · до 200 версій, не загальна статистика")).toBeVisible();
    expect(mock.listReports).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 200 }),
      expect.any(AbortSignal),
    );
  });

  it("searches persisted session identity without extra API calls and allows reset", async () => {
    render(<ReportsWorkspace />);
    await screen.findByRole("button", { name: /NX-101/ });
    fireEvent.change(screen.getByRole("searchbox", { name: "Пошук звітів" }), {
      target: { value: "камера b" },
    });
    const result = screen.getByRole("button", { name: /NX-102/ });
    expect(result).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /NX-101/ })).not.toBeInTheDocument();
    expect(mock.listReports).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("searchbox", { name: "Пошук звітів" }), {
      target: { value: "неіснуючий об’єкт" },
    });
    expect(screen.getByText("За запитом звітів не знайдено")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Скинути пошук" }));
    expect(screen.getByRole("button", { name: /NX-101/ })).toBeVisible();
  });

  it("hides old report rows and counters during refresh and API error", async () => {
    render(<ReportsWorkspace />);
    await screen.findByRole("button", { name: /NX-101/ });
    mock.listReports.mockRejectedValueOnce(new Error("API offline"));
    fireEvent.click(screen.getByRole("button", { name: "Оновити звіти" }));
    expect(screen.queryByRole("button", { name: /NX-101/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Версій: недоступно")).toBeVisible();
    await screen.findByText("API звітів недоступний");
    expect(screen.getByText("API offline")).toBeVisible();
    expect(screen.queryByRole("button", { name: /NX-102/ })).not.toBeInTheDocument();
  });
});
