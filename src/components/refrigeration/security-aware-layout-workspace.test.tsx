import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getRefrigerationEquipment } from "@/data/refrigeration";
import type { DashboardSecurityModel } from "@/hooks/use-dashboard-security";
import { getSecurityCredentials, setSecurityCredentials } from "@/features/security/security-session";
import { SecurityAwareRefrigerationLayoutWorkspace } from "./security-aware-layout-workspace";

const mock = vi.hoisted(() => ({
  security: null as DashboardSecurityModel | null,
  runtime: vi.fn(),
  getSession: vi.fn(),
}));
vi.mock("./refrigeration-security-boundary", () => ({
  useRefrigerationAccount: () => (mock.security ? { security: mock.security } : null),
}));
vi.mock("@/features/refrigeration/layout-repository-runtime", () => ({
  createRefrigerationLayoutRuntime: (input: { organizationId?: string }) => {
    mock.runtime(input);
    return {
      mode: "live",
      organizationId: input.organizationId ?? "org-default",
      repository: {},
      sessionClient: { getSession: mock.getSession },
      actorId: "operator",
      error: null,
    };
  },
}));
vi.mock("./refrigeration-layout-workspace", () => ({
  RefrigerationLayoutWorkspace: (props: {
    mode: string;
    canEditDraft: boolean;
    canPublish: boolean;
    canRestore: boolean;
  }) => (
    <div
      data-testid="layout"
      data-mode={props.mode}
      data-edit={props.canEditDraft}
      data-publish={props.canPublish}
      data-restore={props.canRestore}
    />
  ),
}));
vi.mock("./camera-scoped-layout-editor", () => ({
  CameraScopedLayoutEditor: (props: { organizationId: string; mode: string }) => (
    <div data-testid="camera-layout" data-organization={props.organizationId} data-mode={props.mode} />
  ),
}));

function security(canManage = false): DashboardSecurityModel {
  const memberships = [
    {
      organizationId: "org-default",
      organizationSlug: "default",
      organizationName: "Default",
      roles: ["administrator" as const],
      permissions: ["layout.draft.edit" as const, "layout.publish" as const, "layout.restore" as const],
    },
    {
      organizationId: "org-selected",
      organizationSlug: "selected",
      organizationName: "Selected",
      roles: [canManage ? ("administrator" as const) : ("viewer" as const)],
      permissions: canManage
        ? ["layout.draft.edit" as const, "layout.publish" as const, "layout.restore" as const]
        : [],
    },
  ];
  return {
    mode: "live",
    state: "ready",
    session: {
      authenticated: true,
      identity: { id: "user", provider: "local", subject: "user", displayName: "Verified", email: null },
      memberships,
    },
    membership: memberships[1],
    error: null,
    errorCode: null,
    diagnostics: null,
    selectOrganization: vi.fn(),
    signOut: vi.fn(async () => {}),
    retry: vi.fn(),
  };
}
function fixture() {
  const equipment = getRefrigerationEquipment("showcase-106-01");
  if (!equipment) throw new Error("Missing fixture");
  return equipment;
}
function workspace(extra = {}) {
  return (
    <SecurityAwareRefrigerationLayoutWorkspace
      equipment={fixture()}
      visibleSensors={[]}
      selectedId={null}
      mode="edit"
      onModeChange={vi.fn()}
      onSelect={vi.fn()}
      {...extra}
    />
  );
}
beforeEach(() => {
  mock.runtime.mockClear();
  mock.security = security();
  mock.getSession.mockReset();
  mock.getSession.mockResolvedValue({ ok: true, value: mock.security.session });
  setSecurityCredentials({ accessToken: "test-credential", organizationId: "org-selected" });
});
describe("Scheme shares the verified selected membership", () => {
  it("uses selected viewer scope without reloading session or changing credentials", () => {
    render(workspace());
    expect(mock.runtime).toHaveBeenCalledWith(expect.objectContaining({ organizationId: "org-selected" }));
    expect(mock.getSession).not.toHaveBeenCalled();
    expect(getSecurityCredentials().organizationId).toBe("org-selected");
    expect(screen.getByTestId("layout")).toHaveAttribute("data-mode", "view");
    expect(screen.getByTestId("layout")).toHaveAttribute("data-edit", "false");
    expect(screen.getByText("Selected")).toBeInTheDocument();
  });
  it("derives edit, publish and restore rights from the selected organization", () => {
    mock.security = security(true);
    render(workspace());
    const layout = screen.getByTestId("layout");
    expect(layout).toHaveAttribute("data-mode", "edit");
    for (const attribute of ["data-edit", "data-publish", "data-restore"])
      expect(layout).toHaveAttribute(attribute, "true");
    expect(mock.getSession).not.toHaveBeenCalled();
  });
  it("allows an operator draft edit without granting equipment management or publication", () => {
    mock.security = security(true);
    const membership = mock.security.membership!;
    membership.roles = ["operator"];
    membership.permissions = ["layout.draft.edit"];
    render(workspace());
    const layout = screen.getByTestId("layout");
    expect(layout).toHaveAttribute("data-mode", "edit");
    expect(layout).toHaveAttribute("data-edit", "true");
    expect(layout).toHaveAttribute("data-publish", "false");
    expect(layout).toHaveAttribute("data-restore", "false");
    expect(membership.permissions).not.toContain("equipment.manage");
  });
  it("passes the same selected scope to the camera sensor selector", () => {
    render(workspace({ lifecycleRepository: {} }));
    expect(screen.getByTestId("camera-layout")).toHaveAttribute("data-organization", "org-selected");
    expect(screen.getByTestId("camera-layout")).toHaveAttribute("data-mode", "view");
  });
});
