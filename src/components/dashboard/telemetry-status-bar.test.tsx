import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TelemetryStatusBar } from "./telemetry-status-bar";

vi.mock("@/hooks/use-display-time-zone", () => ({
  useDisplayTimeZone: () => "Europe/Kyiv",
}));

describe("TelemetryStatusBar", () => {
  it("retains readable last-sample freshness in healthy live mode", () => {
    render(
      <TelemetryStatusBar
        mode="live"
        status="live"
        lastCapturedAt="2026-11-06T12:00:00Z"
        ageMs={12_000}
        rejectedFutureSamples={0}
        error={null}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("Live")).toBeVisible();
    expect(screen.getByText("Актуальність:")).toBeVisible();
    expect(screen.getByText("12 с тому")).toBeVisible();
    expect(screen.getByTestId("telemetry-last-captured-at")).toHaveAttribute(
      "datetime",
      "2026-11-06T12:00:00Z",
    );
    expect(screen.queryByRole("button", { name: "Повторити" })).not.toBeInTheDocument();
  });

  it("keeps error and retry explicit and actionable", () => {
    const onRetry = vi.fn();
    render(
      <TelemetryStatusBar
        mode="live"
        status="error"
        lastCapturedAt={null}
        ageMs={null}
        rejectedFutureSamples={2}
        error={new Error("API недоступний")}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("Error")).toBeVisible();
    expect(screen.getByText("API недоступний")).toBeVisible();
    expect(screen.getByText("даних ще немає")).toBeVisible();
    expect(screen.getByText("Відхилено майбутніх часових міток: 2")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Повторити" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("does not promote stale data to live status", () => {
    render(
      <TelemetryStatusBar
        mode="live"
        status="stale"
        lastCapturedAt="2026-11-06T11:00:00Z"
        ageMs={60_000}
        rejectedFutureSamples={0}
        error={null}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("Stale")).toBeVisible();
    expect(screen.getByText("1 хв тому")).toBeVisible();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
});
