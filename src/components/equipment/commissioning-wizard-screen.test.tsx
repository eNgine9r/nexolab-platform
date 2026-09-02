import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CommissioningRepositoryError,
  type CommissioningActivationAttempt,
  type CommissioningActivationPlan,
  type CommissioningPreflightAttempt,
  type CommissioningRepository,
  type CommissioningSession,
} from "@/features/equipment/commissioning-repository";
import type { EquipmentRegistryRuntime } from "@/features/equipment/runtime";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

import { CommissioningWizardScreen } from "./commissioning-wizard-screen";

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
      organizationId: "organization-a",
      organizationSlug: "organization-a",
      organizationName: "Organization A",
      roles: ["engineer"],
      permissions: ["equipment.manage"],
    },
    error: null,
    errorCode: null,
    diagnostics: null,
    retry: vi.fn(),
    selectOrganization: vi.fn(),
    signOut: vi.fn(),
  },
}));

const runtimeFactory = vi.hoisted(() => ({ create: vi.fn() }));
const navigation = vi.hoisted(() => ({ replace: vi.fn(), searchParams: new URLSearchParams() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.searchParams,
}));
vi.mock("@/components/dashboard/sidebar", () => ({ Sidebar: () => <div data-testid="sidebar" /> }));
vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ title }: { title: string }) => <div>{title}</div>,
}));
vi.mock("@/hooks/use-dashboard-security", () => ({ useDashboardSecurity: () => security.value }));
vi.mock("@/features/equipment/runtime", () => ({
  createEquipmentRegistryRuntime: runtimeFactory.create,
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const persistedSession: CommissioningSession = {
  id: "commissioning-a",
  lifecycle: "draft",
  deviceClass: "temperature-controller",
  manufacturer: "Organization A",
  model: "Controller",
  profileId: null,
  profileVersion: null,
  transportKind: null,
  nodeId: null,
  busId: null,
  stableTransportIdentifier: null,
  unitId: null,
  ipAddress: null,
  targetEquipmentKey: null,
  blockedReason: null,
  unsupportedReason: "Unsupported / Profile required",
  version: 1,
  createdBy: "engineer",
  updatedBy: "engineer",
  createdAt: "2026-09-01T12:00:00Z",
  updatedAt: "2026-09-01T12:00:00Z",
  cancelledAt: null,
};

function activationPlan(session: CommissioningSession): CommissioningActivationPlan {
  return {
    schemaVersion: 1,
    sessionId: session.id,
    sessionVersion: session.version,
    preflightAttemptId: "preflight-1",
    preflightCompletedAt: "2026-09-02T08:00:01Z",
    preflightEvidenceLevel: "hardware_verified",
    deviceClass: session.deviceClass,
    manufacturer: session.manufacturer,
    model: session.model,
    profileId: "embraco-sync",
    profileVersion: "embraco-sync-fc03-v1.00.04",
    deviceFamily: "embraco",
    nodeId: "edge-01",
    busId: "rs485-main",
    stableTransportIdentifier: "/dev/serial/by-id/usb-test",
    unitId: 2,
    targetEquipmentKey: "equipment-1",
    telemetrySource: "embraco-sync",
    telemetryEquipmentId: "EMBRACO-2",
    pollingMode: "read_only_fc03",
    bindingKind: "refrigeration_controller",
    warnings: [],
    willNotPerform: ["Modbus FC05/06/15/16 writes", "controller parameter changes"],
  };
}

function commissioningRepository(
  getSession: CommissioningRepository["getSession"],
  overrides: Partial<CommissioningRepository> = {},
): CommissioningRepository {
  return {
    async listProfiles() {
      return [];
    },
    async getProfile() {
      throw new Error("not used");
    },
    async listSessions() {
      return [];
    },
    getSession,
    async createSession() {
      return persistedSession;
    },
    async updateSession() {
      return persistedSession;
    },
    async cancelSession() {
      return { ...persistedSession, lifecycle: "cancelled" };
    },
    getLatestPreflight() {
      return new Promise(() => undefined);
    },
    async runPreflight() {
      throw new Error("not used");
    },
    getActivationPlan() {
      return new Promise(() => undefined);
    },
    getLatestActivation() {
      return new Promise(() => undefined);
    },
    async runActivation() {
      throw new Error("not used");
    },
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function runtime(repository: CommissioningRepository | null, error: string | null = null) {
  return {
    mode: "live",
    equipmentRepository: repository
      ? ({ list: async () => [] } as unknown as RefrigerationEquipmentRepository)
      : null,
    climateCatalogRepository: null,
    discoveryRepository: null,
    commissioningRepository: repository,
    error,
  } satisfies EquipmentRegistryRuntime;
}

describe("CommissioningWizardScreen fail-closed loading boundaries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    security.value.membership.organizationId = "organization-a";
  });

  it("renders an unavailable state when the local commissioning runtime is missing", () => {
    runtimeFactory.create.mockReturnValue(runtime(null, "Local API URL is invalid"));

    render(<CommissioningWizardScreen commissioningId={null} />);

    expect(screen.getByRole("heading", { name: "Комісіонування недоступне" })).toBeInTheDocument();
    expect(screen.getByText("Local API URL is invalid")).toBeInTheDocument();
    expect(screen.queryByText("Завантаження чернетки…")).not.toBeInTheDocument();
  });

  it("hides the previous organization draft while the next repository loads", async () => {
    const firstRepository = commissioningRepository(async () => persistedSession);
    const secondRepository = commissioningRepository(
      () => new Promise<CommissioningSession>(() => undefined),
    );
    runtimeFactory.create.mockImplementation(({ organizationId }: { organizationId?: string }) =>
      runtime(organizationId === "organization-a" ? firstRepository : secondRepository),
    );
    const { rerender } = render(<CommissioningWizardScreen commissioningId="commissioning-a" />);
    expect(await screen.findByRole("heading", { name: "Organization A Controller" })).toBeInTheDocument();

    security.value.membership.organizationId = "organization-b";
    rerender(<CommissioningWizardScreen commissioningId="commissioning-a" />);

    expect(screen.queryByRole("heading", { name: "Organization A Controller" })).not.toBeInTheDocument();
    expect(screen.getByText("Завантаження чернетки…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Зберегти чернетку" })).not.toBeInTheDocument();
  });

  it("runs bounded preflight from a ready draft and renders persisted hardware evidence", async () => {
    const readySession: CommissioningSession = {
      ...persistedSession,
      lifecycle: "ready_for_preflight",
      profileId: "embraco-sync",
      profileVersion: "embraco-sync-fc03-v1.00.04",
      transportKind: "modbus_rtu",
      nodeId: "edge-01",
      busId: "rs485-main",
      stableTransportIdentifier: "/dev/serial/by-id/usb-test",
      unitId: 2,
      targetEquipmentKey: "equipment-1",
      unsupportedReason: null,
      version: 2,
    };
    const attempt: CommissioningPreflightAttempt = {
      id: "preflight-1",
      sessionId: readySession.id,
      sessionVersion: 2,
      state: "completed",
      result: "passed",
      code: "preflight_passed",
      evidenceLevel: "hardware_verified",
      evidence: {
        schemaVersion: 1,
        result: "passed",
        code: "preflight_passed",
        evidenceLevel: "hardware_verified",
        nodeId: "edge-01",
        busId: "rs485-main",
        stableTransportIdentifier: "/dev/serial/by-id/usb-test",
        unitId: 2,
        profileId: "embraco-sync",
        profileVersion: "embraco-sync-fc03-v1.00.04",
        readMethod: "modbus_rtu_fc03",
        functionCodes: [3],
        checks: [
          { key: "write_safety", state: "passed", detail: "Modbus writes = none; hardware writes = none" },
        ],
        observations: [{ key: "control_state", quality: "valid", semantic: "cooling" }],
        warnings: [],
        durationMs: 14,
        modbusWrites: "none",
        hardwareWrites: "none",
      },
      actorSubject: "engineer",
      startedAt: "2026-09-02T08:00:00Z",
      completedAt: "2026-09-02T08:00:01Z",
    };
    const verifiedSession: CommissioningSession = { ...readySession, lifecycle: "verified" };
    let verified = false;
    const runPreflight = vi.fn(async () => {
      verified = true;
      return attempt;
    });
    const repository = commissioningRepository(async () => (verified ? verifiedSession : readySession), {
      getLatestPreflight: () => new Promise(() => undefined),
      getActivationPlan: async () => {
        if (!verified) {
          throw new CommissioningRepositoryError("preflight required", "commissioning_preflight_stale", 409);
        }
        return activationPlan(verifiedSession);
      },
      runPreflight,
    });
    runtimeFactory.create.mockReturnValue(runtime(repository));

    render(<CommissioningWizardScreen commissioningId="commissioning-a" />);
    expect(await screen.findByRole("heading", { name: "Organization A Controller" })).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Запустити безпечну перевірку" });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    expect(await screen.findByText("hardware verified")).toBeInTheDocument();
    expect(screen.getAllByText("none").length).toBeGreaterThanOrEqual(2);
    expect(runPreflight).toHaveBeenCalledWith("commissioning-a", 2, expect.stringMatching(/^commissioning-/));
  });

  it("activates verified read-only monitoring and locks ordinary draft mutation", async () => {
    const verifiedSession: CommissioningSession = {
      ...persistedSession,
      lifecycle: "verified",
      profileId: "embraco-sync",
      profileVersion: "embraco-sync-fc03-v1.00.04",
      transportKind: "modbus_rtu",
      nodeId: "edge-01",
      busId: "rs485-main",
      stableTransportIdentifier: "/dev/serial/by-id/usb-test",
      unitId: 2,
      targetEquipmentKey: "equipment-1",
      unsupportedReason: null,
      version: 2,
    };
    const plan = activationPlan(verifiedSession);
    const activeSession: CommissioningSession = { ...verifiedSession, lifecycle: "active" };
    const activeAttempt: CommissioningActivationAttempt = {
      id: "activation-1",
      sessionId: verifiedSession.id,
      preflightAttemptId: plan.preflightAttemptId,
      sessionVersion: verifiedSession.version,
      state: "active",
      plan,
      evidence: { modbus_writes: "none", hardware_writes: "none" },
      actorSubject: "engineer",
      startedAt: "2026-09-02T08:01:00Z",
      completedAt: "2026-09-02T08:01:02Z",
    };
    let active = false;
    const runActivation = vi.fn(async () => {
      active = true;
      return activeAttempt;
    });
    const repository = commissioningRepository(async () => (active ? activeSession : verifiedSession), {
      getActivationPlan: async () => plan,
      getLatestActivation: async () => {
        if (!active)
          throw new CommissioningRepositoryError("not found", "commissioning_activation_not_found", 404);
        return activeAttempt;
      },
      runActivation,
    });
    runtimeFactory.create.mockReturnValue(runtime(repository));

    render(<CommissioningWizardScreen commissioningId="commissioning-a" />);
    const button = await screen.findByRole("button", { name: "Активувати read-only моніторинг" });
    expect(button).toBeEnabled();
    expect(screen.getByText((content) => content.includes("Modbus FC05"))).toBeInTheDocument();
    fireEvent.click(button);

    expect(await screen.findByText("Read-only monitoring active")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Зберегти чернетку" })).not.toBeInTheDocument();
    expect(runActivation).toHaveBeenCalledWith(
      "commissioning-a",
      2,
      expect.stringMatching(/^commissioning-/),
    );
  });

  it("discards an in-flight save after the organization repository changes", async () => {
    const pendingUpdate = deferred<CommissioningSession>();
    const organizationBSession = {
      ...persistedSession,
      id: "commissioning-b",
      manufacturer: "Organization B",
    };
    const firstRepository = commissioningRepository(async () => persistedSession, {
      updateSession: async () => pendingUpdate.promise,
    });
    const secondRepository = commissioningRepository(async () => organizationBSession);
    runtimeFactory.create.mockImplementation(({ organizationId }: { organizationId?: string }) =>
      runtime(organizationId === "organization-a" ? firstRepository : secondRepository),
    );
    const { rerender } = render(<CommissioningWizardScreen commissioningId="commissioning-a" />);
    expect(await screen.findByRole("heading", { name: "Organization A Controller" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Зберегти чернетку" }));

    security.value.membership.organizationId = "organization-b";
    rerender(<CommissioningWizardScreen commissioningId="commissioning-a" />);
    expect(await screen.findByRole("heading", { name: "Organization B Controller" })).toBeInTheDocument();

    await act(async () => pendingUpdate.resolve(persistedSession));

    expect(screen.getByRole("heading", { name: "Organization B Controller" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Organization A Controller" })).not.toBeInTheDocument();
  });
});
