import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LaboratorySession, SessionPage, SessionState } from "@/lib/sessions/types";

import { SessionsListScreen } from "./sessions-list-screen";

const mock = vi.hoisted(() => ({
  organizationId: "org-a",
  list: vi.fn(),
  createClient: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/dashboard/platform-account-boundary", () => ({
  usePlatformAccount: () => ({ security: { membership: { organizationId: mock.organizationId } } }),
}));
vi.mock("@/hooks/use-display-time-zone", () => ({
  useDisplayTimeZone: () => "Europe/Kyiv",
}));
vi.mock("@/lib/sessions/api-client", () => ({
  createSessionApiClient: (options: unknown) => {
    mock.createClient(options);
    return { listSessions: mock.list };
  },
}));

const session = (state: SessionState, id: string): LaboratorySession => ({
  id,
  organization_id: "org-a",
  session_number: `NXL-TEST-${id}`,
  node_id: "edge-01",
  state,
  title: "Випробування лабораторної вітрини з надзвичайно довгою офіційною назвою",
  customer: "Лабораторія холодильних випробувань",
  test_object: "Холодильна шафа з багатьма датчиками",
  model: "NX-1250",
  serial_number: `SERIAL-${id}`,
  standard: "ISO 23953-2:2023",
  method: null,
  operator_id: null,
  responsible_engineer_id: null,
  metadata_payload: {},
  current_stage_id: null,
  active_config_snapshot_id: null,
  active_limit_version: null,
  lock_version: 1,
  prepared_at: null,
  started_at: null,
  paused_at: null,
  completed_at: null,
  cancelled_at: null,
  archived_at: null,
  created_at: "2026-11-10T05:00:00.000Z",
  updated_at: "2026-11-10T06:00:00.000Z",
});

const page = (items: LaboratorySession[]): SessionPage => ({
  items,
  count: items.length,
  limit: 200,
  offset: 0,
  next_offset: null,
});

beforeEach(() => {
  mock.organizationId = "org-a";
  mock.list.mockReset();
  mock.createClient.mockReset();
});

describe("SessionsListScreen scoped and readable presentation", () => {
  it("keeps long session identity and shows counts only for the fetched selection", async () => {
    const running = session("running", "running");
    const cancelled = { ...session("cancelled", "cancelled"), title: "Скасоване випробування" };
    mock.list.mockImplementation(async (options: { state?: SessionState }) =>
      page(options.state ? [running, cancelled].filter((item) => item.state === options.state) : [running, cancelled]),
    );

    render(<SessionsListScreen />);
    const heading = await screen.findByRole("heading", { name: running.title });
    expect(heading).not.toHaveClass("truncate");
    expect(screen.getByText("Завантажено")).toBeVisible();
    expect(screen.getByText(/Лічильники стосуються лише поточної завантаженої вибірки/)).toBeVisible();
    expect(screen.getAllByText("ISO 23953-2:2023")).toHaveLength(2);
    expect(screen.getByRole("searchbox", { name: "Пошук лабораторних сесій" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Скасовані" }));
    await waitFor(() => expect(mock.list).toHaveBeenLastCalledWith(expect.objectContaining({ state: "cancelled" }), expect.any(AbortSignal)));
    expect(await screen.findByRole("heading", { name: "Скасоване випробування" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: running.title })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Скасовані" })).toHaveAttribute("aria-pressed", "true");
    expect(mock.createClient).toHaveBeenLastCalledWith({ organizationId: "org-a" });
  });

  it("does not expose fabricated zero counts on API failure", async () => {
    mock.list.mockRejectedValue(new Error("API сесій недоступний"));
    render(<SessionsListScreen />);
    expect(screen.getByText("Завантаження реальних сесій…")).toBeVisible();
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(await screen.findByText("API сесій недоступний")).toBeVisible();
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByRole("link", { name: /Відкрити сесію/ })).not.toBeInTheDocument();
  });

  it("hides the previous organization's results immediately and ignores a late aborted response", async () => {
    const requests: Array<{ resolve: (value: SessionPage) => void; signal: AbortSignal }> = [];
    mock.list.mockImplementation((_options: unknown, signal: AbortSignal) =>
      new Promise<SessionPage>((resolve) => {
        requests.push({ resolve, signal });
      }),
    );
    const { rerender } = render(<SessionsListScreen />);
    await waitFor(() => expect(requests).toHaveLength(1));
    const forA = { ...session("running", "a"), title: "Секрет org-a" };
    await act(async () => requests[0]!.resolve(page([forA])));
    expect(await screen.findByRole("heading", { name: forA.title })).toBeVisible();

    mock.organizationId = "org-b";
    rerender(<SessionsListScreen />);
    expect(screen.queryByText(forA.title)).not.toBeInTheDocument();
    expect(screen.getByText("Завантаження реальних сесій…")).toBeVisible();
    expect(screen.getAllByText("—")).toHaveLength(3);
    await waitFor(() => expect(requests).toHaveLength(2));

    await act(async () => requests[0]!.resolve(page([forA])));
    expect(screen.queryByText(forA.title)).not.toBeInTheDocument();
    const forB = { ...session("completed", "b"), organization_id: "org-b", title: "Випробування org-b" };
    await act(async () => requests[1]!.resolve(page([forB])));
    expect(await screen.findByRole("heading", { name: forB.title })).toBeVisible();
    expect(screen.queryByText(forA.title)).not.toBeInTheDocument();
    expect(mock.createClient).toHaveBeenLastCalledWith({ organizationId: "org-b" });
  });
});
