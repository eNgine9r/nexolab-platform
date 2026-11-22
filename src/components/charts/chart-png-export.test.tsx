import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EChartsRendererAdapter } from "@/features/charts/echarts-adapter";

import { chartPngFilename, downloadChartPng } from "./chart-png-export";
import { ChartShell } from "./chart-shell";

describe("chart PNG export (#1658)", () => {
  it("builds a unique, sortable, filesystem-safe filename", () => {
    expect(chartPngFilename("Графік Dashboard · °C / %", new Date("2026-11-22T05:30:01.234Z"))).toBe(
      "nexolab-графік-dashboard-c-20261122T053001Z.png",
    );
    expect(chartPngFilename("***", new Date("2026-11-22T05:30:01.234Z"))).toBe(
      "nexolab-chart-20261122T053001Z.png",
    );
  });

  it("downloads the data URL produced by the mounted renderer", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const adapter = { exportImage: () => "data:image/png;base64,AAAA" };
    expect(downloadChartPng(adapter, "Live Data K106", document, new Date("2026-11-22T05:30:01Z"))).toBe(
      true,
    );
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector("a[download]")).toBeNull();
    click.mockRestore();
  });

  it("does nothing when the renderer cannot export", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    expect(downloadChartPng({ exportImage: () => null }, "x")).toBe(false);
    expect(downloadChartPng({}, "x")).toBe(false);
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });

  it("returns null from an adapter that was never initialised or is disposed", () => {
    expect(new EChartsRendererAdapter().exportImage()).toBeNull();
  });

  it("shows the Save PNG button only when an export handler is supplied", () => {
    const common = {
      title: "Графік",
      context: "°C",
      selectedRange: "24h",
      series: [],
      inspection: null,
      locale: "uk" as const,
      onToggleSeries: () => undefined,
      onSoloSeries: () => undefined,
      onResetZoom: () => undefined,
    };
    const { rerender } = render(<ChartShell {...common}>plot</ChartShell>);
    expect(screen.queryByTestId("chart-export-png")).toBeNull();
    const onExportImage = vi.fn();
    rerender(
      <ChartShell {...common} onExportImage={onExportImage}>
        plot
      </ChartShell>,
    );
    fireEvent.click(screen.getByTestId("chart-export-png"));
    expect(onExportImage).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("chart-export-png")).toHaveTextContent("Зберегти PNG");
  });
});
