import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LiveTelemetryModel } from "@/hooks/use-live-telemetry";

import { LiveTelemetryExplorer } from "./live-telemetry-explorer";

vi.mock("next/navigation", () => ({
  usePathname: () => "/live",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("workspace=explorer"),
}));

vi.mock("@/components/live/live-chart-panel", () => ({
  LiveChartPanel: ({
    resetDomain,
    onResetView,
    onXDomainChange,
  }: {
    resetDomain: { fromMs: number; toMs: number };
    onResetView: () => void;
    onXDomainChange: (domain: { fromMs: number; toMs: number }) => void;
  }) => (
    <div data-testid="mock-live-chart">
      <button type="button" data-testid="mock-reset-view" onClick={onResetView}>
        reset
      </button>
      <button
        type="button"
        data-testid="mock-manual-zoom"
        onClick={() =>
          onXDomainChange({
            fromMs: resetDomain.fromMs + 60_000,
            toMs: resetDomain.toMs - 60_000,
          })
        }
      >
        manual zoom
      </button>
    </div>
  ),
}));

function model(): LiveTelemetryModel {
  const sample = {
    event_id: "event-1",
    node_id: "edge-01",
    captured_at: new Date().toISOString(),
    metric: "temperature.probe",
    value: 4.25,
    unit: "degC",
    quality: "valid" as const,
    source: "unit-test",
    equipment_id: "K106",
    channel_id: "106-03",
    alarm: null,
    raw_value: 43,
    raw_status: null,
  };

  return {
    mode: "live",
    status: "live",
    connectionState: "connected",
    samples: [sample],
    freshSamples: [sample],
    lastCapturedAt: sample.captured_at,
    selectedKeys: [],
    setSelectedKeys: vi.fn(),
    historyRange: "1h",
    setHistoryRange: vi.fn(),
    historyWindow: null,
    historySamples: [],
    historyStatus: "idle",
    historySnapshotAt: null,
    historyError: null,
    rejectedFutureSamples: 0,
    error: null,
    retry: vi.fn(),
    retryHistory: vi.fn(),
  };
}

function modelWithChart(): LiveTelemetryModel {
  const telemetry = model();
  const sample = telemetry.samples[0];
  const to = new Date(sample.captured_at);
  const from = new Date(to.getTime() - 60 * 60_000);
  const selectedKey = [sample.node_id, sample.equipment_id, sample.channel_id, sample.metric, sample.unit]
    .map((part) => encodeURIComponent(part))
    .join("|");

  return {
    ...telemetry,
    selectedKeys: [selectedKey],
    historyWindow: { from, to },
    historySamples: [sample],
    historyStatus: "ready",
    historySnapshotAt: to.toISOString(),
  };
}

function appearsBefore(left: Element, right: Element): boolean {
  return Boolean(left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("LiveTelemetryExplorer graph-first composition", () => {
  it("places the canonical chart before filters and inventory in reading and focus order", () => {
    render(<LiveTelemetryExplorer telemetry={model()} />);

    const chart = screen.getByTestId("live-primary-chart");
    const filters = screen.getByTestId("live-filter-panel");
    const inventory = screen.getByTestId("live-inventory-panel");

    expect(appearsBefore(chart, filters)).toBe(true);
    expect(appearsBefore(filters, inventory)).toBe(true);

    const liveRange = within(chart).getByRole("button", { name: "Live" });
    const search = screen.getByPlaceholderText("node, equipment, channel, metric, source...");
    const compare = screen.getByRole("checkbox", { name: /Порівнювати/ });

    expect(appearsBefore(liveRange, search)).toBe(true);
    expect(appearsBefore(search, compare)).toBe(true);
    expect(within(chart).getByText("Жодного каналу не обрано")).toBeVisible();
    expect(within(chart).getByText("Оберіть канали нижче у Latest values")).toBeVisible();
    expect(inventory.querySelector(".overflow-x-auto")).not.toBeNull();
  });
});

describe("LiveTelemetryExplorer viewport semantics", () => {
  it("keeps reset in Live Follow while manual zoom still pauses the view", () => {
    const telemetry = modelWithChart();
    const setHistoryRange = telemetry.setHistoryRange as ReturnType<typeof vi.fn>;
    render(<LiveTelemetryExplorer telemetry={telemetry} />);

    expect(screen.getByText("Live Follow", { exact: true })).toBeVisible();
    fireEvent.click(screen.getByTestId("mock-reset-view"));
    expect(screen.getByText("Live Follow", { exact: true })).toBeVisible();
    expect(setHistoryRange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("mock-manual-zoom"));
    expect(screen.getByText("Paused view", { exact: true })).toBeVisible();

    fireEvent.click(screen.getByTestId("mock-reset-view"));
    expect(screen.getByText("Live Follow", { exact: true })).toBeVisible();
    expect(setHistoryRange).not.toHaveBeenCalled();
  });
});
