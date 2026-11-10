import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LiveInventoryPanel } from "./live-inventory-panel";

vi.mock("@/hooks/use-display-time-zone", () => ({
  useDisplayTimeZone: () => "Europe/Kyiv",
}));

vi.mock("@/lib/telemetry/dashboard-inventory", () => ({
  deriveTelemetryInventory: () => ({
    nodes: [
      {
        nodeId: "edge-01",
        state: "warning",
        equipmentCount: 2,
        channelCount: 8,
        validCount: 6,
        issueCount: 2,
        lastCapturedAt: "2026-11-06T12:00:00Z",
      },
    ],
    equipment: [
      {
        nodeId: "edge-01",
        equipmentId: "dixell-01",
        channelCount: 6,
        validCount: 4,
        issueCount: 2,
        lastCapturedAt: "2026-11-06T12:00:00Z",
      },
    ],
  }),
}));

describe("LiveInventoryPanel", () => {
  it("shows clear Ukrainian node, equipment and quality labels without dropping counts", () => {
    render(<LiveInventoryPanel samples={[]} status="live" />);

    expect(screen.getByText("edge-01")).toBeVisible();
    expect(screen.getByText("Потребує уваги")).toBeVisible();
    expect(screen.getByText(/2 приладів · 8 каналів/)).toBeVisible();
    expect(screen.getByText(/6 коректних/)).toBeVisible();
    expect(screen.getAllByText(/2 проблем/)).toHaveLength(2);
    expect(screen.getByText("dixell-01")).toBeVisible();
    expect(screen.getByText(/6 каналів/)).toBeVisible();
    expect(screen.getByText("Прилади за останніми даними API")).toBeVisible();
  });
});
