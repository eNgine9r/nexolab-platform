import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Xjp60dSensorManagement } from "@/hooks/use-xjp60d-sensor-management";

import { SensorManagementDialog } from "./sensor-management-dialog";

describe("SensorManagementDialog monitoring enrollment", () => {
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
      monitoredChannelIds: ["126-04"],
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

  it("labels responsive unit 115 as KK2", () => {
    const management: Xjp60dSensorManagement = {
      configuration: {
        node_id: "edge-01",
        active_points: [],
        discovery_units: [115],
        last_discovery: {
          scanned_at: "2026-08-14T07:00:00Z",
          duration_ms: 120,
          controller_count: 1,
          reachable_controller_count: 1,
          available_points: [
            {
              channel_id: "115-04",
              unit_id: 115,
              channel: 4,
              quality: "valid",
              value: 4.8,
              unit: "degC",
              alarm: null,
              raw_status: 0,
            },
          ],
          unavailable_points: [],
          controller_errors: [],
        },
        target_diagnostics: [],
      },
      monitoredChannelIds: [],
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

    expect(screen.getByText("115-04")).toBeInTheDocument();
    expect(screen.getByText(/КК2 · вхід 4 · valid/)).toBeInTheDocument();
    expect(screen.getByText("4,8 °C")).toBeInTheDocument();
  });
});
