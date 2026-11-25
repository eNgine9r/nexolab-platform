import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MonitoringReadModel } from "@/hooks/use-monitoring-read-model";
import type { AlertInstance } from "@/lib/alerts/types";

import { AlarmsPanel } from "./alarms-panel";

const mocks = vi.hoisted(() => ({
  useAlerts: vi.fn(),
  retry: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/features/overview/use-overview-alerts-read-model", () => ({
  useOverviewAlertsReadModel: mocks.useAlerts,
}));

beforeEach(() => {
  vi.useFakeTimers();
  mocks.retry.mockReset();
  mocks.useAlerts.mockReset();
  mocks.useAlerts.mockReturnValue(readModel({ value: [alertFixture()] }));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AlarmsPanel", () => {
  it("uses the organization-scoped model and preserves explicit five-second polling", () => {
    render(<AlarmsPanel mode="live" organizationId="org-a" />);

    expect(mocks.useAlerts).toHaveBeenCalledWith({ enabled: true, organizationId: "org-a" });
    act(() => vi.advanceTimersByTime(5_000));
    expect(mocks.retry).toHaveBeenCalledTimes(1);
  });

  it("labels an empty event journal without claiming all telemetry is healthy", () => {
    mocks.useAlerts.mockReturnValue(readModel({ value: [], status: "ready" }));

    render(<AlarmsPanel mode="live" organizationId="org-a" />);

    expect(screen.getByText("Відкритих подій немає")).toBeVisible();
    expect(
      screen.getByText(
        "У журналі немає активних або підтверджених подій. Відхилення телеметрії показані окремо.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("Усе спокійно")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Повторити" })).not.toBeInTheDocument();
  });

  it("does not show a green all-clear when refreshing a cached empty journal fails", () => {
    mocks.useAlerts.mockReturnValue(
      readModel({ value: [], error: new Error("Alerts API unavailable"), status: "error" }),
    );

    render(<AlarmsPanel mode="live" organizationId="org-a" />);

    expect(screen.getByText("Стан подій не підтверджено")).toBeVisible();
    expect(
      screen.getByText("Не вдалося оновити журнал тривог; останній отриманий список був порожнім."),
    ).toBeVisible();
    expect(screen.queryByText("Відкритих подій немає")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторити" }));
    expect(mocks.retry).toHaveBeenCalledTimes(1);
  });

  it("does not claim the event journal is clear when its cached result is stale", () => {
    mocks.useAlerts.mockReturnValue(readModel({ value: [], status: "stale", freshness: "stale" }));

    render(<AlarmsPanel mode="live" organizationId="org-a" />);

    expect(screen.getByText("Стан подій не підтверджено")).toBeVisible();
    expect(screen.queryByText("Відкритих подій немає")).not.toBeInTheDocument();
  });

  it("keeps the last valid alert visible after a refresh error", () => {
    mocks.useAlerts.mockReturnValue(
      readModel({ value: [alertFixture()], error: new Error("Alerts API unavailable"), status: "error" }),
    );

    render(<AlarmsPanel mode="live" organizationId="org-a" />);

    expect(screen.getByText("chamber-1 · channel-1 · temperature")).toBeVisible();
    expect(screen.getByText("Оновлення не вдалося; показано останній валідний snapshot.")).toBeVisible();
  });
});

function readModel(
  overrides: Partial<MonitoringReadModel<AlertInstance[]>> = {},
): MonitoringReadModel<AlertInstance[]> {
  return {
    value: null,
    status: "ready",
    error: null,
    freshness: "fresh",
    retry: mocks.retry,
    ...overrides,
  };
}

function alertFixture(): AlertInstance {
  return {
    id: "alert-1",
    organization_id: "org-a",
    rule_id: "rule-1",
    rule_version_id: "rule-version-1",
    resource_key: "edge-01:channel-1:temperature",
    node_id: "edge-01",
    equipment_id: "chamber-1",
    channel_id: "channel-1",
    metric: "temperature",
    state: "active",
    severity: "warning",
    trigger_value: 8.2,
    trigger_threshold: 8,
    clear_threshold: 7.5,
    maximum_deviation: 0.2,
    first_event_id: "event-1",
    last_event_id: "event-1",
    session_id: null,
    stage_id: null,
    binding_id: null,
    context: { unit: "°C" },
    triggered_at: "2026-08-13T08:00:00Z",
    acknowledged_at: null,
    resolved_at: null,
    closed_at: null,
    lock_version: 1,
    created_at: "2026-08-13T08:00:00Z",
    updated_at: "2026-08-13T08:00:00Z",
  };
}
