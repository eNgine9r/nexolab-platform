import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  CommissioningRepository,
  CommissioningSession,
} from "@/features/equipment/commissioning-repository";

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

function repository(): CommissioningRepository {
  return {
    async listProfiles() {
      return [];
    },
    async getProfile() {
      throw new Error("not used");
    },
    async listSessions() {
      return [persistedSession];
    },
    async getSession() {
      return persistedSession;
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
});
