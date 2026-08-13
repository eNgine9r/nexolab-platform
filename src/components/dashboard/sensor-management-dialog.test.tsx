import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Xjp60dSensorManagement } from "@/hooks/use-xjp60d-sensor-management";

import { SensorManagementDialog } from "./sensor-management-dialog";

describe("SensorManagementDialog acquisition state", () => {
  it("distinguishes an active target awaiting its first scheduler attempt", () => {
    const management: Xjp60dSensorManagement = {
      configuration: {
        node_id: "edge-01",
        active_points: ["126-04"],
        discovery_units: [126],
        last_discovery: null,
        target_diagnostics: [
          {
            target_id: "xjp60d:126-04",
            channel_id: "126-04",
            state: "initializing",
            recovery_state: "initializing",
            last_attempt_at: null,
            last_success_at: null,
            last_error: null,
            consecutive_failures: 0,
            cooldown: false,
            cooldown_remaining_seconds: 0,
            next_due_in_seconds: 0.5,
            outcomes: {
              attempts: 0,
              successes: 0,
              communication_failures: 0,
            },
          },
        ],
      },
      activeChannelIds: ["126-04"],
      isLoading: false,
      isDiscovering: false,
      isSaving: false,
      error: null,
      refresh: vi.fn(),
      discover: vi.fn(),
      save: vi.fn(),
    };

    render(
      <SensorManagementDialog open canManage management={management} onClose={vi.fn()} onSaved={vi.fn()} />,
    );

    expect(screen.getByText("126-04")).toBeInTheDocument();
    expect(screen.getByText(/Ініціалізація — очікується перша спроба/)).toBeInTheDocument();
    expect(screen.getByText(/0 спроб · 0 успішних · 0 послідовних помилок/)).toBeInTheDocument();
  });
});
