import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VersionScreen } from "./version-screen";

const ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111";

const security = vi.hoisted(() => ({
  value: {
    mode: "live",
    state: "ready",
    session: {
      authenticated: true,
      identity: {
        id: "engineer-id",
        provider: "nexolab-local",
        subject: "engineer",
        email: null,
        displayName: "Engineer",
      },
      memberships: [],
    },
    membership: {
      organizationId: "11111111-1111-1111-1111-111111111111",
      organizationSlug: "nexolab",
      organizationName: "NEXOLAB",
      roles: ["engineer"],
      permissions: ["dashboard.read"],
    },
    error: null,
    errorCode: null,
    diagnostics: null,
    retry: vi.fn(),
    selectOrganization: vi.fn(),
    signOut: vi.fn(),
  },
}));

const versionApi = vi.hoisted(() => ({
  read: vi.fn(),
  setAutomaticUpdates: vi.fn(),
  requestUpdateCheck: vi.fn(),
  requestAction: vi.fn(),
}));

const snapshot = () => ({
  current: {
    bundleId: "bundle-current",
    release: "2026.08.18",
    sourceCommit: "a".repeat(40),
    buildTimestamp: "2026-08-18T07:00:00Z",
    runtimeMode: "lan",
    platform: "linux-arm64",
    schemaHead: "head-1",
    deployedAt: "2026-08-18T07:00:00Z",
    health: "ready",
    previousBundleId: null,
    previousRelease: null,
    knownPackagedRelease: true,
    runtimeStateKnown: true,
  },
  catalog: [],
  history: [],
  activeOperation: null,
  rejectedPackages: [],
  updatePolicy: {
    automaticUpdatesEnabled: false,
    scheduleLocalTime: "02:00",
    updatedAt: null,
    updatedBy: null,
    errorCode: null,
  },
  updateCheck: null,
  offline: true,
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/system/version",
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/hooks/use-dashboard-security", () => ({ useDashboardSecurity: () => security.value }));
vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({ mode: "live", apiBaseUrl: "http://127.0.0.1:8082" }),
}));
vi.mock("@/features/security/auth-runtime", () => ({
  createRuntimeCredentialProvider: () => async () => ({
    accessToken: "local-access-token",
    organizationId: ORGANIZATION_ID,
  }),
}));
vi.mock("@/features/settings/version-management", () => ({
  VersionManagementClient: class {
    read = versionApi.read;
    setAutomaticUpdates = versionApi.setAutomaticUpdates;
    requestUpdateCheck = versionApi.requestUpdateCheck;
    requestAction = versionApi.requestAction;
  },
}));

describe("VersionScreen authorization boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    security.value.mode = "live";
    security.value.state = "ready";
    security.value.membership.permissions = ["dashboard.read"];
    versionApi.read.mockResolvedValue(snapshot());
    versionApi.setAutomaticUpdates.mockResolvedValue({
      ...snapshot().updatePolicy,
      automaticUpdatesEnabled: true,
      updatedAt: "2026-08-18T08:00:00Z",
      updatedBy: "engineer",
    });
    versionApi.requestUpdateCheck.mockResolvedValue({
      id: "check-1",
      actorSubject: "engineer",
      source: "manual",
      status: "queued",
      requestedAt: "2026-08-18T08:00:00Z",
      reason: null,
    });
  });

  it("does not initialize version management for a non-administrator", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<VersionScreen />);

    expect(screen.getByRole("heading", { name: "Доступ заборонено" })).toBeVisible();
    expect(screen.getByText(/project_versions\.manage/)).toBeVisible();
    expect(versionApi.read).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("does not expose host controls in demo mode", () => {
    security.value.mode = "demo";

    render(<VersionScreen />);

    expect(screen.getByRole("heading", { name: "Version management недоступний у demo mode" })).toBeVisible();
    expect(versionApi.read).not.toHaveBeenCalled();
  });

  it("renders the persisted automatic-update policy and manual check control", async () => {
    security.value.membership.permissions = ["dashboard.read", "project_versions.manage"];

    render(<VersionScreen />);

    expect(await screen.findByRole("heading", { name: "Автоматичні оновлення" })).toBeVisible();
    expect(screen.getByRole("switch", { name: "Автоматичні оновлення" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByText("Щодня о 02:00")).toBeVisible();
    expect(screen.getByRole("button", { name: "Перевірити оновлення зараз" })).toBeEnabled();
  });

  it("persists the automatic-update toggle through the version API", async () => {
    security.value.membership.permissions = ["dashboard.read", "project_versions.manage"];

    render(<VersionScreen />);

    const toggle = await screen.findByRole("switch", { name: "Автоматичні оновлення" });
    fireEvent.click(toggle);

    await waitFor(() => expect(versionApi.setAutomaticUpdates).toHaveBeenCalledWith(true));
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("Увімкнено")).toBeVisible();
  });

  it("queues a manual update check without enabling automatic updates", async () => {
    security.value.membership.permissions = ["dashboard.read", "project_versions.manage"];

    render(<VersionScreen />);

    const checkButton = await screen.findByRole("button", { name: "Перевірити оновлення зараз" });
    fireEvent.click(checkButton);

    await waitFor(() => expect(versionApi.requestUpdateCheck).toHaveBeenCalledTimes(1));
    expect(versionApi.setAutomaticUpdates).not.toHaveBeenCalled();
    expect(await screen.findByText("Перевіряємо…")).toBeVisible();
  });

  it("shows a newer remote revision as blocked until a validated package exists", async () => {
    security.value.membership.permissions = ["dashboard.read", "project_versions.manage"];
    versionApi.read.mockResolvedValue({
      ...snapshot(),
      updateCheck: {
        status: "blocked",
        source: "manual",
        actor: "engineer",
        startedAt: "2026-08-18T08:00:00Z",
        completedAt: "2026-08-18T08:00:02Z",
        resultCode: "candidate_found",
        message: "New revision discovered",
        currentCommit: "a".repeat(40),
        targetCommit: "b".repeat(40),
        candidateAvailable: true,
        activationEligible: false,
        blockedReason: "validated_package_required",
      },
    });

    render(<VersionScreen />);

    expect(await screen.findByText("Знайдено новішу ревізію")).toBeVisible();
    expect(screen.getByText("для remote revision ще немає validated local package")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Оновити зараз" })).not.toBeInTheDocument();
  });
});
