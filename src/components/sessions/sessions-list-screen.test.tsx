import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LaboratorySession, SessionPage } from "@/lib/sessions/types";
import { SessionsListScreen } from "./sessions-list-screen";

const mock = vi.hoisted(() => ({
  organizationId: "org-a",
  list: vi.fn(),
  create: vi.fn(),
}));

vi.mock("@/components/dashboard/platform-account-boundary", () => ({
  usePlatformAccount: () => ({
    security: { membership: { organizationId: mock.organizationId } },
  }),
}));
vi.mock("@/hooks/use-display-time-zone", () => ({
  useDisplayTimeZone: () => "Europe/Kyiv",
}));
vi.mock("@/lib/sessions/api-client", () => ({
  createSessionApiClient: (options: unknown) => {
    mock.create(options);
    return { listSessions: mock.list };
  },
}));

const session = {
  id: "session-a",
  organization_id: "org-a",
  session_number: "LAB-2026-0042",
  state: "running",
  title: "Температурне випробування промислової холодильної вітрини з дуже довгою назвою",
  test_object: "Вітрина з довгою назвою об’єкта та серійним маркуванням",
  model: "NEXOLAB-X",
  customer: "Замовник із дуже довгою назвою юридичної особи",
  serial_number: "SN-00042",
  standard: "ISO 23953-2:2023",
  active_config_snapshot_id: null,
  active_limit_version: null,
  updated_at: "2026-11-10T09:10:00.000Z",
} as LaboratorySession;

function page(items: LaboratorySession[], next_offset: number | null = null): SessionPage {
  return { items, count: items.length, limit: 200, offset: 0, next_offset };
}

beforeEach(() => {
  mock.organizationId = "org-a";
  mock.list.mockReset().mockResolvedValue(page([session]));
  mock.create.mockClear();
});

describe("Sessions operator list", () => {
  it("shows readable source-backed identity and selection-scoped summaries", async () => {
    render(<SessionsListScreen />);
    await screen.findByText(session.title);
    expect(screen.getByText("Поточна вибірка · до 200 записів, не загальна статистика")).toBeVisible();
    expect(screen.getByText(session.test_object + " · NEXOLAB-X")).toBeVisible();
    expect(screen.getByText(session.customer!)).toBeVisible();
    expect(screen.getByText("ISO 23953-2:2023")).toBeVisible();
    expect(screen.getByRole("link", { name: /LAB-2026-0042/ })).toHaveAttribute(
      "href",
      "/sessions/session-a",
    );
    expect(mock.create).toHaveBeenCalledWith({ organizationId: "org-a" });
  });

  it("never renders an old organization's rows or numeric counts during a scope switch", async () => {
    const pending: { resolve?: (value: SessionPage) => void } = {};
    const { rerender } = render(<SessionsListScreen />);
    await screen.findByText(session.title);
    mock.organizationId = "org-b";
    mock.list.mockImplementationOnce(
      () =>
        new Promise<SessionPage>((resolve) => {
          pending.resolve = resolve;
        }),
    );
    rerender(<SessionsListScreen />);
    expect(screen.queryByText(session.title)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Завантаження реальних сесій");
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    await waitFor(() => expect(mock.list).toHaveBeenCalledTimes(2));
    await act(async () => {
      pending.resolve?.(
        page([{ ...session, id: "session-b", title: "Нова сесія організації Б", organization_id: "org-b" }]),
      );
    });
    await screen.findByText("Нова сесія організації Б");
    expect(screen.queryByText(session.title)).not.toBeInTheDocument();
    expect(mock.create).toHaveBeenLastCalledWith({ organizationId: "org-b" });
  });

  it("supports cancelled filtering and restoring the full selection", async () => {
    render(<SessionsListScreen />);
    await screen.findByText(session.title);
    fireEvent.click(screen.getByRole("button", { name: "Скасовані" }));
    await waitFor(() =>
      expect(mock.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "cancelled", nodeId: "edge-01", limit: 200 }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Скинути фільтри" }));
    await waitFor(() =>
      expect(mock.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: undefined }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("reports an API error without displaying old sessions or false zero totals", async () => {
    mock.list.mockRejectedValueOnce(new Error("API offline"));
    render(<SessionsListScreen />);
    await screen.findByText("API випробувань недоступний");
    expect(screen.getByText("API offline")).toBeVisible();
    expect(screen.queryByText(session.title)).not.toBeInTheDocument();
    expect(screen.getByText("У вибірці")).toBeVisible();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Повторити" }));
    await screen.findByText(session.title);
  });
});
