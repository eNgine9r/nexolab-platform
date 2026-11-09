import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  CommissioningRepository,
  CommissioningSession,
} from "@/features/equipment/commissioning-repository";
import type { EquipmentRegistryAsset } from "@/features/equipment/asset-registry";

import { EquipmentConnectionsWorkspace } from "./equipment-connections-workspace";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/equipment/equipment-discovery-inbox", () => ({
  EquipmentDiscoveryInbox: () => <section>LAN Discovery Inbox</section>,
}));

const persistedSession: CommissioningSession = {
  id: "commissioning-1",
  lifecycle: "unsupported",
  deviceClass: "temperature-controller",
  manufacturer: "Unknown",
  model: "Mystery",
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
  createdBy: "operator",
  updatedBy: "operator",
  createdAt: "2026-09-01T12:00:00Z",
  updatedAt: "2026-09-01T12:00:00Z",
  cancelledAt: null,
};

function repository(session: CommissioningSession = persistedSession): CommissioningRepository {
  return {
    async listProfiles() {
      return [];
    },
    async getProfile() {
      throw new Error("not used");
    },
    async listConnections() {
      return { schemaVersion: 1, nodeId: "edge-01", connections: [] };
    },
    async listSessions() {
      return [session];
    },
    async getSession() {
      return session;
    },
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
    async getActivationPlan() {
      throw new Error("not used");
    },
    async getLatestActivation() {
      throw new Error("not used");
    },
    async runActivation() {
      throw new Error("not used");
    },
  };
}

describe("EquipmentConnectionsWorkspace", () => {
  it("surfaces persistent and unsupported drafts with discovery under Connections", async () => {
    render(
      <EquipmentConnectionsWorkspace
        repository={repository()}
        discoveryRepository={null}
        canManage
        assets={[]}
      />,
    );

    expect(screen.getByRole("link", { name: /Підключити пристрій/ })).toHaveAttribute(
      "href",
      "/equipment/onboarding/new",
    );
    expect(await screen.findByText("Unknown Mystery")).toBeInTheDocument();
    expect(screen.getAllByText("Unsupported / Profile required").length).toBeGreaterThan(0);
    expect(screen.getByText("LAN Discovery Inbox")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Unknown Mystery/ })).toHaveAttribute(
      "href",
      "/equipment/onboarding/commissioning-1",
    );
  });

  it("does not expose a mutation CTA without equipment.manage", async () => {
    render(
      <EquipmentConnectionsWorkspace
        repository={repository()}
        discoveryRepository={null}
        canManage={false}
        assets={[]}
      />,
    );

    expect(await screen.findByText("Unknown Mystery")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Підключити пристрій/ })).not.toBeInTheDocument();
    expect(screen.getByText("Потрібен дозвіл equipment.manage")).toBeInTheDocument();
  });

  it("shows the refrigeration equipment name for a saved target ID", async () => {
    const targetedSession = { ...persistedSession, targetEquipmentKey: "equipment-cool-jet" };
    const refrigerationAsset = {
      key: "refrigeration:equipment-cool-jet",
      id: "equipment-cool-jet",
      category: "refrigeration-equipment",
      displayName: "Cool jet",
    } as EquipmentRegistryAsset;

    render(
      <EquipmentConnectionsWorkspace
        repository={repository(targetedSession)}
        discoveryRepository={null}
        canManage
        assets={[refrigerationAsset]}
      />,
    );

    expect(await screen.findByText(/Прив’язка: Cool jet/)).toBeInTheDocument();
    expect(screen.queryByText(/Прив’язка: equipment-cool-jet/)).not.toBeInTheDocument();
  });

  it("renders canonical active read-only monitoring with the saved equipment binding", async () => {
    const activeSession: CommissioningSession = {
      ...persistedSession,
      lifecycle: "active",
      manufacturer: "Embraco",
      model: "Sync",
      profileId: "embraco-sync",
      profileVersion: "embraco-sync-fc03-v1.00.04",
      transportKind: "modbus_rtu",
      nodeId: "edge-01",
      busId: "rs485-embraco",
      stableTransportIdentifier: "/dev/serial/by-id/usb-embraco",
      unitId: 2,
      targetEquipmentKey: "equipment-cool-jet",
      unsupportedReason: null,
      version: 2,
    };
    const refrigerationAsset = {
      key: "refrigeration:equipment-cool-jet",
      id: "equipment-cool-jet",
      category: "refrigeration-equipment",
      displayName: "Cool jet",
    } as EquipmentRegistryAsset;

    render(
      <EquipmentConnectionsWorkspace
        repository={repository(activeSession)}
        discoveryRepository={null}
        canManage
        assets={[refrigerationAsset]}
      />,
    );

    expect(await screen.findByText("Embraco Sync")).toBeInTheDocument();
    expect(screen.getByText("Read-only моніторинг активний")).toBeInTheDocument();
    expect(screen.getByText(/Прив’язка: Cool jet/)).toBeInTheDocument();
    expect(screen.getByText("1", { selector: "p" })).toBeInTheDocument();
  });

  it("hides previous organization sessions while the next repository loads", async () => {
    const firstRepository = repository();
    const secondRepository: CommissioningRepository = {
      ...repository(),
      listSessions: () => new Promise<CommissioningSession[]>(() => undefined),
    };
    const { rerender } = render(
      <EquipmentConnectionsWorkspace
        repository={firstRepository}
        discoveryRepository={null}
        canManage
        assets={[]}
      />,
    );
    expect(await screen.findByText("Unknown Mystery")).toBeInTheDocument();

    rerender(
      <EquipmentConnectionsWorkspace
        repository={secondRepository}
        discoveryRepository={null}
        canManage
        assets={[]}
      />,
    );

    expect(screen.queryByText("Unknown Mystery")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Завантаження чернеток");
  });

  it("filters saved sessions by bus, Unit ID, equipment and persisted lifecycle without new API requests", async () => {
    const active = {
      ...persistedSession,
      id: "active-2",
      manufacturer: "Embraco",
      model: "Sync",
      lifecycle: "active" as const,
      busId: "rs485-embraco",
      unitId: 2,
      targetEquipmentKey: "equipment-cool-jet",
      blockedReason: null,
      unsupportedReason: null,
    };
    const draft = {
      ...persistedSession,
      id: "draft-1",
      manufacturer: "Dixell",
      model: "XJP60D",
      lifecycle: "draft" as const,
      busId: "rs485-test",
      unitId: 10,
      blockedReason: null,
      unsupportedReason: null,
    };
    const rolledBack = {
      ...persistedSession,
      id: "rollback-1",
      manufacturer: "F&F",
      model: "LE-01MP",
      lifecycle: "rolled_back" as const,
      blockedReason: null,
      unsupportedReason: null,
    };
    const listSessions = vi.fn(async () => [persistedSession, active, draft, rolledBack]);
    const asset = {
      key: "refrigeration:equipment-cool-jet",
      id: "equipment-cool-jet",
      category: "refrigeration-equipment",
      displayName: "Cool jet",
    } as EquipmentRegistryAsset;
    render(
      <EquipmentConnectionsWorkspace
        repository={{ ...repository(), listSessions }}
        discoveryRepository={null}
        canManage
        assets={[asset]}
      />,
    );

    expect(await screen.findByText("Dixell XJP60D")).toBeVisible();
    expect(screen.getByText("Показано 4 із 4 збережених сесій")).toBeVisible();
    expect(screen.getByText("Шина: rs485-embraco")).toBeVisible();
    expect(screen.getByText("Unit ID: 2")).toBeVisible();

    const search = screen.getByRole("searchbox", { name: "Пошук підключень" });
    fireEvent.change(search, { target: { value: "Unit ID 2" } });
    expect(screen.getByText("Embraco Sync")).toBeVisible();
    expect(screen.queryByText("Dixell XJP60D")).not.toBeInTheDocument();
    expect(screen.getByText("Показано 1 із 4 збережених сесій")).toBeVisible();

    fireEvent.change(search, { target: { value: "Cool jet" } });
    expect(screen.getByText("Embraco Sync")).toBeVisible();
    fireEvent.change(search, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /Потрібна увага/ }));
    expect(screen.getByText("Unknown Mystery")).toBeVisible();
    expect(screen.getByText("F&F LE-01MP")).toBeVisible();
    expect(screen.queryByText("Embraco Sync")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Активні/ }));
    expect(screen.getByText("Embraco Sync")).toBeVisible();
    expect(screen.queryByText("Unknown Mystery")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /У процесі/ }));
    expect(screen.getByText("Dixell XJP60D")).toBeVisible();
    expect(screen.queryByText("F&F LE-01MP")).not.toBeInTheDocument();
    expect(listSessions).toHaveBeenCalledTimes(1);
  });

  it("distinguishes filtered empty state from the actual absence of saved sessions", async () => {
    render(
      <EquipmentConnectionsWorkspace
        repository={repository()}
        discoveryRepository={null}
        canManage
        assets={[]}
      />,
    );
    expect(await screen.findByText("Unknown Mystery")).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Пошук підключень" }), {
      target: { value: "does-not-exist" },
    });
    expect(screen.getByText("За заданими умовами підключень немає")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Скинути фільтри" }));
    expect(screen.getByText("Unknown Mystery")).toBeVisible();
    expect(screen.queryByText("За заданими умовами підключень немає")).not.toBeInTheDocument();
  });

  it("does not display misleading zero active sessions during loading or repository failures", async () => {
    const pending: CommissioningRepository = {
      ...repository(),
      listSessions: () => new Promise<CommissioningSession[]>(() => undefined),
    };
    const { rerender } = render(
      <EquipmentConnectionsWorkspace
        repository={pending}
        discoveryRepository={null}
        canManage={false}
        assets={[]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Завантаження чернеток");
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByRole("searchbox", { name: "Пошук підключень" })).not.toBeInTheDocument();

    rerender(
      <EquipmentConnectionsWorkspace
        repository={{
          ...repository(),
          listSessions: async () => {
            throw new Error("Локальна база недоступна");
          },
        }}
        discoveryRepository={null}
        canManage={false}
        assets={[]}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Локальна база недоступна");
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByRole("searchbox", { name: "Пошук підключень" })).not.toBeInTheDocument();
  });
});
