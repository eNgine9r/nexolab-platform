import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RefrigerationControllerModel } from "@/features/refrigeration/use-refrigeration-controller";

import { RefrigerationControllerDetail } from "./refrigeration-controller-detail";
import { RefrigerationControllerOverview } from "./refrigeration-controller-overview";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

function failedController(): RefrigerationControllerModel {
  const from = new Date("2026-09-01T12:00:00Z");
  const to = new Date("2026-09-01T13:00:00Z");
  return {
    binding: null,
    bindingLoading: false,
    latest: null,
    latestError: "Не вдалося отримати прив’язку контролера.",
    history: new Map(),
    historyLoading: false,
    historyError: null,
    preset: "1h",
    range: { from, to },
    customRange: { from, to },
    setPreset: vi.fn(),
    setCustomRange: vi.fn(),
  };
}

describe("refrigeration controller binding failure states", () => {
  it.each([
    ["overview", RefrigerationControllerOverview],
    ["detail", RefrigerationControllerDetail],
  ])("fails closed in the %s instead of offering commissioning", (_name, Component) => {
    render(<Component controller={failedController()} equipmentId="showcase-106-01" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Не вдалося отримати прив’язку контролера.");
    expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
  });
});
