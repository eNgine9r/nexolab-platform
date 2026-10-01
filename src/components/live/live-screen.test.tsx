import { LIVE_SELECTION_LIMIT } from "@/features/live/live-telemetry";
import { LIVE_DASHBOARD_MAX_ITEMS } from "@/features/live-dashboards/types";
import { useState, type ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardSecurityModel } from "@/hooks/use-dashboard-security";
import { LiveScreen } from "./live-screen";

const mock = vi.hoisted(() => ({
  params: new URLSearchParams(),
  replace: vi.fn(),
  security: null as DashboardSecurityModel | null,
  targetOrganization: "org-b",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mock.replace }),
  useSearchParams: () => mock.params,
  usePathname: () => "/live",
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/hooks/use-dashboard-security", () => ({ useDashboardSecurity: () => mock.security }));
vi.mock("@/components/dashboard/sidebar", () => ({ Sidebar: () => null }));
vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ onOrganizationChange }: { onOrganizationChange: (id: string) => void }) => (
    <button onClick={() => onOrganizationChange(mock.targetOrganization)}>Change test organization</button>
  ),
}));
function Workspace({ organizationId, kind }: { organizationId: string; kind: string }) {
  const [draft, setDraft] = useState("");
  return (
    <div data-testid={kind} data-organization={organizationId}>
      <input aria-label="Workspace draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
    </div>
  );
}
vi.mock("@/components/live/live-data-workspace", () => ({
  LiveDataWorkspace: (props: { organizationId: string }) => <Workspace {...props} kind="explorer" />,
}));
vi.mock("@/components/live-dashboards/live-dashboard-workspace", () => ({
  LiveDashboardWorkspace: (props: { organizationId: string }) => <Workspace {...props} kind="dashboards" />,
}));
function ready(organizationId = "org-a"): DashboardSecurityModel {
  const memberships = ["org-a", "org-b"].map((id) => ({
    organizationId: id,
    organizationSlug: id,
    organizationName: id,
    roles: ["viewer" as const],
    permissions: ["telemetry.read" as const, "dashboard.read" as const],
  }));
  return {
    mode: "live",
    state: "ready",
    session: {
      authenticated: true,
      identity: {
        id: "operator",
        provider: "local",
        subject: "operator",
        email: null,
        displayName: "Operator",
      },
      memberships,
    },
    membership: memberships.find((item) => item.organizationId === organizationId)!,
    error: null,
    errorCode: null,
    diagnostics: null,
    selectOrganization: vi.fn(),
    signOut: vi.fn(async () => {}),
    retry: vi.fn(),
  };
}
beforeEach(() => {
  mock.params = new URLSearchParams();
  mock.replace.mockClear();
  mock.security = ready();
});
describe("Live monitoring entry", () => {
  it.each(["", "workspace=unknown", "workspace=explorer"])('opens monitoring for "%s"', (query) => {
    mock.params = new URLSearchParams(query);
    render(<LiveScreen />);
    expect(screen.getByTestId("explorer")).toBeInTheDocument();
    expect(screen.queryByTestId("dashboards")).not.toBeInTheDocument();
  });
  it("keeps the explicit saved-dashboard library route", () => {
    mock.params = new URLSearchParams("workspace=dashboards");
    render(<LiveScreen />);
    expect(screen.getByTestId("dashboards")).toBeInTheDocument();
  });
  it("preserves comparison and range context when switching workspaces", () => {
    mock.params = new URLSearchParams("compare=channel-a&compare=channel-b&range=24h&search=probe");
    render(<LiveScreen />);
    fireEvent.click(screen.getByRole("button", { name: "Saved Dashboards" }));
    const url = new URL(mock.replace.mock.calls[0][0], "http://localhost");
    expect(url.searchParams.getAll("compare")).toEqual(["channel-a", "channel-b"]);
    expect(url.searchParams.get("range")).toBe("24h");
    expect(url.searchParams.get("search")).toBe("probe");
    expect(url.searchParams.get("workspace")).toBe("dashboards");
  });
  it("explains both existing limits and preserves context through the guided transition", () => {
    mock.params = new URLSearchParams("compare=channel-a&compare=channel-b&range=24h&search=probe");
    render(<LiveScreen />);
    const guidance = screen.getByTestId("live-workspace-guidance");
    expect(guidance).toHaveTextContent(`до ${LIVE_SELECTION_LIMIT} точок`);
    expect(guidance).toHaveTextContent(`до ${LIVE_DASHBOARD_MAX_ITEMS} точок`);
    fireEvent.click(screen.getByRole("button", { name: "Відкрити збережені панелі" }));
    const url = new URL(mock.replace.mock.calls[0][0], "http://localhost");
    expect(url.searchParams.getAll("compare")).toEqual(["channel-a", "channel-b"]);
    expect(url.searchParams.get("range")).toBe("24h");
    expect(url.searchParams.get("search")).toBe("probe");
    expect(url.searchParams.get("workspace")).toBe("dashboards");
  });
  it("keeps saved-panel guidance and action behind the existing read permission", () => {
    const security = ready();
    mock.security = {
      ...security,
      membership: { ...security.membership!, permissions: ["telemetry.read"] },
    };
    render(<LiveScreen />);
    const guidance = screen.getByTestId("live-workspace-guidance");
    expect(guidance).toHaveTextContent(`до ${LIVE_SELECTION_LIMIT} точок`);
    expect(guidance).not.toHaveTextContent("Збережені панелі");
    expect(screen.queryByRole("button", { name: "Відкрити збережені панелі" })).not.toBeInTheDocument();
    expect(screen.getByTestId("explorer")).toBeInTheDocument();
  });
  it("follows URL changes and history without keeping a stale selected tab", () => {
    mock.params = new URLSearchParams("workspace=dashboards");
    const { rerender } = render(<LiveScreen />);
    mock.params = new URLSearchParams("workspace=explorer");
    rerender(<LiveScreen />);
    expect(screen.getByTestId("explorer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Live Data" })).toHaveAttribute("aria-current", "page");
  });
  it.each(["explorer", "dashboards"])("resets %s state on organization changes", (kind) => {
    mock.params = new URLSearchParams(`workspace=${kind}`);
    const { rerender } = render(<LiveScreen />);
    fireEvent.change(screen.getByLabelText("Workspace draft"), { target: { value: "org-a draft" } });
    mock.security = ready("org-b");
    rerender(<LiveScreen />);
    expect(screen.getByTestId(kind)).toHaveAttribute("data-organization", "org-b");
    expect(screen.getByLabelText("Workspace draft")).toHaveValue("");
  });
  it.each(["explorer", "dashboards"])(
    "clears URL context before mounting the new organization's %s",
    (kind) => {
      mock.params = new URLSearchParams(
        `workspace=${kind}&compare=old-channel&search=old-probe&node=old-node&range=24h`,
      );
      const select = vi.fn(() => {
        mock.security = ready("org-b");
      });
      mock.security!.selectOrganization = select;
      const { rerender } = render(<LiveScreen />);
      fireEvent.change(screen.getByLabelText("Workspace draft"), { target: { value: "old draft" } });
      fireEvent.click(screen.getByRole("button", { name: "Change test organization" }));
      expect(mock.replace).toHaveBeenCalledWith(`/live?workspace=${kind}`, { scroll: false });
      expect(select).not.toHaveBeenCalled();
      expect(screen.queryByTestId(kind)).not.toBeInTheDocument();
      mock.params = new URLSearchParams(`workspace=${kind}`);
      rerender(<LiveScreen />);
      expect(select).toHaveBeenCalledWith("org-b");
      rerender(<LiveScreen />);
      expect(screen.getByTestId(kind)).toHaveAttribute("data-organization", "org-b");
      expect(screen.getByLabelText("Workspace draft")).toHaveValue("");
    },
  );
  it("does not mount a workspace before authentication", () => {
    mock.security = { ...ready(), state: "unauthenticated", session: null, membership: null };
    render(<LiveScreen />);
    expect(screen.queryByTestId("explorer")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dashboards")).not.toBeInTheDocument();
  });
});
