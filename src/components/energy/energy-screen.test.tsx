import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommissionedEnergyMeter } from "@/features/energy/energy-commissioned-meters";

const state = vi.hoisted(() => ({ telemetry: vi.fn(), meters: [] as CommissionedEnergyMeter[] }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/hooks/use-dashboard-security", () => ({
  useDashboardSecurity: () => ({
    mode: "live",
    state: "ready",
    membership: { organizationId: "org-a", permissions: ["telemetry.read"] },
    session: { identity: { id: "operator" } },
    selectOrganization: vi.fn(),
    signOut: vi.fn(),
  }),
}));
vi.mock("@/features/energy/use-commissioned-energy-meters", () => ({
  useCommissionedEnergyMeters: () => ({ status: "ready", meters: state.meters }),
}));
vi.mock("@/hooks/use-energy-telemetry", () => ({
  ENERGY_NODE_ID: "edge-01",
  useEnergyTelemetry: state.telemetry,
}));
vi.mock("@/features/energy/use-energy-consumption", () => ({
  useEnergyConsumption: () => ({ enabled: false, load: vi.fn() }),
}));
vi.mock("@/features/energy/use-energy-export", () => ({ useEnergyExport: () => ({}) }));
vi.mock("@/components/dashboard/sidebar", () => ({ Sidebar: () => null }));
vi.mock("@/components/dashboard/topbar", () => ({ Topbar: () => null }));
vi.mock("@/components/energy/energy-workspace", () => ({
  EnergyWorkspace: ({
    nodeId,
    includeLegacy,
    meters,
  }: {
    nodeId: string;
    includeLegacy: boolean;
    meters: CommissionedEnergyMeter[];
  }) => (
    <div data-testid="node-workspace">
      {nodeId}|{String(includeLegacy)}|{meters.map((meter) => meter.label).join(",")}
    </div>
  ),
}));

import { EnergyScreen } from "./energy-screen";

describe("Energy node selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.telemetry.mockReturnValue({});
    state.meters = ["edge-01", "edge-02"].map((node, index) => ({
      nodeId: node,
      busId: "commissioning-0123456789abcdef",
      unitId: 1,
      equipmentId: "SDM120M:commissioning-0123456789abcdef:1",
      label: `Meter ${index + 1}`,
      modelLabel: "SDM",
      family: "sdm120",
    }));
  });
  it("switches the authenticated node and excludes primary legacy cards from other nodes", () => {
    render(<EnergyScreen />);
    expect(screen.getByTestId("node-workspace")).toHaveTextContent("edge-01|true|Meter 1");
    fireEvent.change(screen.getByRole("combobox", { name: "Вузол моніторингу" }), {
      target: { value: "edge-02" },
    });
    expect(screen.getByTestId("node-workspace")).toHaveTextContent("edge-02|false|Meter 2");
    expect(state.telemetry).toHaveBeenLastCalledWith(
      expect.objectContaining({ nodeId: "edge-02", commissionedMeters: [state.meters[1]] }),
    );
    expect(screen.getByText(/Одночасне порівняння приладів з різних вузлів поки недоступне/)).toBeVisible();
    expect(screen.getByText(/покази старше 30 секунд позначаються застарілими/)).toBeVisible();
  });
});
