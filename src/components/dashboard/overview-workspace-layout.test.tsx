import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverviewWorkspaceLayout } from "./overview-workspace-layout";

describe("OverviewWorkspaceLayout", () => {
  it("renders the graph first and secondary panels in the responsive grid below", () => {
    render(
      <OverviewWorkspaceLayout
        primary={<div data-testid="graph-slot">Graph</div>}
        secondaryStart={<div data-testid="node-slot">Nodes</div>}
        secondaryEnd={<div data-testid="alarms-slot">Alarms</div>}
      />,
    );

    const primary = screen.getByTestId("overview-primary-workspace");
    const secondary = screen.getByTestId("overview-secondary-grid");

    expect(primary.nextElementSibling).toBe(secondary);
    expect(primary).toHaveClass("mt-3", "min-w-0");
    expect(secondary).toHaveClass("mt-3", "grid", "min-w-0", "grid-cols-1", "gap-3", "xl:grid-cols-2");
    expect(secondary.children).toHaveLength(2);
    expect(screen.getByTestId("graph-slot")).toBeInTheDocument();
    expect(screen.getByTestId("node-slot")).toBeInTheDocument();
    expect(screen.getByTestId("alarms-slot")).toBeInTheDocument();
  });
});
