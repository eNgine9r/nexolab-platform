import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DashboardLiveView } from "@/components/live-dashboards/dashboard-live-view";
import { resolveChartPointBudget } from "@/features/charts/density";
import { draftToWrite, dashboardItemIdentity, dashboardToDraft } from "@/features/live-dashboards/model";
import {
  captureViewSettings,
  rangeMatches,
  resolveViewSettings,
  viewportOverlapsWindow,
} from "@/features/live-dashboards/view-settings";
import type {
  LiveDashboard,
  LiveDashboardItem,
  LiveDashboardViewSettings,
} from "@/features/live-dashboards/types";
import type { LiveDashboardTelemetryModel } from "@/hooks/use-live-dashboard-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

vi.mock("@/components/charts/chart-renderer-host", () => ({ ChartRendererHost: () => null }));
vi.mock("@/features/live-dashboards/use-dashboard-alert-events", () => ({
  useDashboardAlertEvents: () => ({ status: "idle", alerts: [], message: null }),
}));

const T0 = Date.parse("2026-11-10T00:00:00Z");

function item(id: string, position: number, channelId: string): LiveDashboardItem {
  return {
    id,
    position,
    channel_ref_id: `ref-${id}`,
    channel_id: channelId,
    metric: "temperature.probe",
    native_unit: "°C",
    visualization: "line",
    color: "#22AAFF",
    display_unit: "°C",
  };
}

const a = item("a", 1, "T-1");
const b = item("b", 2, "T-2");

const savedView: LiveDashboardViewSettings = {
  schema_version: 1,
  hidden_items: [dashboardItemIdentity(b), "gone|metric"],
  range_kind: "6h",
  range_from: null,
  range_to: null,
  viewport_from: new Date(T0 + 1_000_000).toISOString(),
  viewport_to: new Date(T0 + 2_000_000).toISOString(),
  density: 1000,
};

function dashboard(view: LiveDashboardViewSettings | null): LiveDashboard {
  return {
    id: "d1",
    organization_id: "org",
    name: "Аналіз",
    description: null,
    owner_subject: "operator",
    refresh_seconds: 5,
    time_window: "24h",
    version: 3,
    status: "active",
    created_by: "operator",
    updated_by: "operator",
    created_at: new Date(T0).toISOString(),
    updated_at: new Date(T0).toISOString(),
    archived_by: null,
    archived_at: null,
    items: [a, b],
    view_settings: view,
  };
}

function sample(channel: string, index: number): TelemetrySample {
  return {
    event_id: `${channel}-${index}`,
    node_id: "edge-1",
    captured_at: new Date(T0 + index * 60_000).toISOString(),
    metric: "temperature.probe",
    value: 4 + index,
    unit: "degC",
    quality: "valid",
    source: "test",
    equipment_id: "K106",
    channel_id: channel,
    alarm: null,
    raw_value: 4,
    raw_status: null,
  };
}

function telemetry(kind: "24h" | "6h", overrides: Partial<LiveDashboardTelemetryModel> = {}) {
  const history = (channel: string) => Array.from({ length: 60 }, (_, index) => sample(channel, index));
  const range = {
    kind,
    from: new Date(T0).toISOString(),
    to: new Date(T0 + 3_600_000).toISOString(),
    label: kind,
  };
  return {
    status: "live",
    connectionState: "connected",
    series: [
      { item: a, latest: sample("T-1", 59), history: history("T-1") },
      { item: b, latest: sample("T-2", 59), history: history("T-2") },
    ],
    lastCapturedAt: null,
    historyRange: range,
    historyWindow: range,
    historyStatus: "ready",
    historyError: null,
    exportStatus: "idle",
    exportError: null,
    selectHistoryPreset: vi.fn(),
    applyCustomHistoryRange: vi.fn(),
    exportCsv: vi.fn(),
    error: null,
    retry: vi.fn(),
    now: T0 + 3_600_000,
    ...overrides,
  } as unknown as LiveDashboardTelemetryModel;
}

function view(model: LiveDashboardTelemetryModel, dash: LiveDashboard, onSaveView = vi.fn()) {
  return (
    <DashboardLiveView
      dashboard={dash}
      telemetry={model}
      density="auto"
      densityResolution={resolveChartPointBudget("auto", 2)}
      onDensityChange={vi.fn()}
      canManage
      onBack={vi.fn()}
      onEdit={vi.fn()}
      onSaveView={onSaveView}
    />
  );
}

describe("saved analysis view model (#1666)", () => {
  it("captures hidden series, range, viewport and density", () => {
    const captured = captureViewSettings({
      hiddenItemIdentities: [dashboardItemIdentity(b), dashboardItemIdentity(b)],
      historyRange: {
        kind: "custom",
        from: "2026-11-10T00:00:00.000Z",
        to: "2026-11-10T04:00:00.000Z",
        label: "x",
      },
      viewport: { fromMs: T0 + 1000, toMs: T0 + 2000 },
      density: 500,
    });
    expect(captured).toMatchObject({
      schema_version: 1,
      hidden_items: [dashboardItemIdentity(b)],
      range_kind: "custom",
      range_from: "2026-11-10T00:00:00.000Z",
      viewport_from: new Date(T0 + 1000).toISOString(),
      density: 500,
    });
    const preset = captureViewSettings({
      hiddenItemIdentities: [],
      historyRange: { kind: "24h", from: "x", to: "y", label: "24h" },
      viewport: null,
      density: "auto",
    });
    expect(preset).toMatchObject({
      range_kind: "24h",
      range_from: null,
      range_to: null,
      viewport_from: null,
    });
  });

  it("restores only what still exists and ignores unusable parts", () => {
    const restored = resolveViewSettings(savedView, [a, b]);
    expect(restored?.hiddenItemIdentities).toEqual([dashboardItemIdentity(b)]);
    expect(restored?.range).toEqual({ kind: "preset", preset: "6h" });
    expect(restored?.density).toBe(1000);
    expect(resolveViewSettings(savedView, [a])?.hiddenItemIdentities).toEqual([]);
    expect(resolveViewSettings({ ...savedView, schema_version: 2 }, [a, b])).toBeNull();
    expect(resolveViewSettings(null, [a])).toBeNull();
    const broken = resolveViewSettings(
      {
        ...savedView,
        range_kind: "custom",
        range_from: "nope",
        range_to: null,
        viewport_from: "x",
        viewport_to: "y",
      },
      [a, b],
    );
    expect(broken?.range).toBeNull();
    expect(broken?.viewport).toBeNull();
  });

  it("compares ranges and viewport overlap", () => {
    expect(rangeMatches({ kind: "preset", preset: "6h" }, { kind: "6h", from: "a", to: "b" })).toBe(true);
    expect(rangeMatches({ kind: "preset", preset: "6h" }, { kind: "24h", from: "a", to: "b" })).toBe(false);
    expect(rangeMatches({ kind: "custom", from: "a", to: "b" }, { kind: "custom", from: "a", to: "b" })).toBe(
      true,
    );
    expect(viewportOverlapsWindow({ fromMs: 5, toMs: 10 }, { fromMs: 0, toMs: 6 })).toBe(true);
    expect(viewportOverlapsWindow({ fromMs: 50, toMs: 60 }, { fromMs: 0, toMs: 6 })).toBe(false);
  });

  it("only writes view_settings when the draft carries it", () => {
    const base = dashboardToDraft(dashboard(savedView));
    expect("view_settings" in draftToWrite(base)).toBe(false);
    expect(draftToWrite({ ...base, view_settings: null }).view_settings).toBeNull();
    expect(draftToWrite({ ...base, view_settings: savedView }).view_settings).toEqual(savedView);
  });
});

describe("DashboardLiveView saved analysis view", () => {
  it("re-applies the saved range, then hides the saved series once the range has settled", async () => {
    const first = telemetry("24h");
    const dash = dashboard(savedView);
    const { rerender } = render(view(first, dash));
    await act(async () => {
      await Promise.resolve();
    });
    expect(first.selectHistoryPreset).toHaveBeenCalledWith("6h");

    // Range settled: both series visible before restore, one afterwards.
    rerender(view(telemetry("6h"), dash));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const table = screen.getByTestId("dashboard-interval-statistics");
    expect(within(table).getAllByTestId("dashboard-statistics-row")).toHaveLength(1);
  });

  it("shows no restore side effects without a saved view and offers to save one", async () => {
    const model = telemetry("24h");
    const onSaveView = vi.fn().mockResolvedValue(undefined);
    render(view(model, dashboard(null), onSaveView));
    await act(async () => {
      await Promise.resolve();
    });
    expect(model.selectHistoryPreset).not.toHaveBeenCalled();
    expect(screen.queryByText("Скинути збережений вигляд")).toBeNull();
    fireEvent.click(screen.getByText("Зберегти вигляд аналізу"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(onSaveView).toHaveBeenCalledTimes(1);
    const saved = onSaveView.mock.calls[0][0] as LiveDashboardViewSettings;
    expect(saved).toMatchObject({ schema_version: 1, hidden_items: [], range_kind: "24h", density: "auto" });
    expect(screen.getByTestId("saved-analysis-view-status")).toHaveTextContent("Вигляд збережено");
    expect(screen.getByText("Скинути збережений вигляд")).toBeInTheDocument();
  });

  it("clears the saved view with null and reports failures without losing the page", async () => {
    const onSaveView = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("conflict"));
    render(view(telemetry("6h"), dashboard(savedView), onSaveView));
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(screen.getByText("Скинути збережений вигляд"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(onSaveView).toHaveBeenCalledWith(null);
    expect(screen.getByTestId("saved-analysis-view-status")).toHaveTextContent("скинуто");
    fireEvent.click(screen.getByText("Зберегти вигляд аналізу"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId("saved-analysis-view-status")).toHaveTextContent("Не вдалося зберегти");
  });
});
