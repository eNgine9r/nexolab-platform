import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SessionsListScreen } from "./sessions-list-screen";
import { SessionWizard } from "./session-wizard";
import { SessionWorkspace } from "./session-workspace";

const mock = vi.hoisted(() => ({
  organizationId: "org-b",
  createClient: vi.fn(),
  list: vi.fn(async () => ({ items: [], count: 0, limit: 200, offset: 0, next_offset: null })),
  inventory: vi.fn(),
  workspace: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/dashboard/platform-account-boundary", () => ({
  usePlatformAccount: () => ({ security: { membership: { organizationId: mock.organizationId } } }),
}));
vi.mock("@/lib/sessions/api-client", async (original) => ({
  ...(await original<object>()),
  createSessionApiClient: (options: unknown) => {
    mock.createClient(options);
    return { listSessions: mock.list };
  },
}));
vi.mock("@/hooks/use-live-dashboard-inventory", () => ({
  useLiveDashboardInventory: (options: unknown) => {
    mock.inventory(options);
    return { items: [], status: "ready", error: null, retry: vi.fn() };
  },
}));
vi.mock("./use-session-workspace", () => ({
  useSessionWorkspace: (...args: unknown[]) => {
    mock.workspace(...args);
    return { data: null, loading: true, error: null };
  },
}));
beforeEach(() => {
  mock.createClient.mockClear();
  mock.list.mockClear();
  mock.inventory.mockClear();
  mock.workspace.mockClear();
  vi.stubEnv("NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID", "configured-org");
});
describe("session domain uses the verified shell organization", () => {
  it("passes it to catalog requests", async () => {
    render(<SessionsListScreen />);
    await waitFor(() => expect(mock.createClient).toHaveBeenCalledWith({ organizationId: "org-b" }));
  });
  it("passes it to wizard inventory instead of the configured default", () => {
    render(<SessionWizard />);
    expect(mock.inventory).toHaveBeenCalledWith({ enabled: false, organizationId: "org-b" });
  });
  it("passes it to detail reads and mutations", () => {
    render(<SessionWorkspace sessionId="session-a" />);
    expect(mock.workspace).toHaveBeenCalledWith("session-a", "org-b");
  });
});
