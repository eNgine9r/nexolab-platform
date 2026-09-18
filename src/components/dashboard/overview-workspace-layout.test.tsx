import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverviewWorkspaceLayout } from "./overview-workspace-layout";

describe("OverviewWorkspaceLayout", () => {
  it("keeps temperature full width with attention and infrastructure stacked below", () => {
    render(
      <OverviewWorkspaceLayout
        primary={<div data-testid="graph-slot">Graph</div>}
        attention={<div data-testid="attention-slot">Attention</div>}
        supporting={<div data-testid="node-slot">Nodes</div>}
      />,
    );

    const commandGrid = screen.getByTestId("overview-command-grid");
    const primary = screen.getByTestId("overview-primary-workspace");
    const attention = screen.getByTestId("overview-attention-workspace");
    const secondary = screen.getByTestId("overview-secondary-grid");

    expect(commandGrid).toContainElement(primary);
    expect(commandGrid).toContainElement(attention);
    expect(primary.nextElementSibling).toBe(attention);
    expect(commandGrid.nextElementSibling).toBe(secondary);
    expect(commandGrid).toHaveClass("grid-cols-1");
    expect(primary).not.toHaveClass("xl:col-span-9");
    expect(attention).not.toHaveClass("xl:col-span-3");
    expect(screen.getByTestId("graph-slot")).toBeInTheDocument();
    expect(screen.getByTestId("attention-slot")).toBeInTheDocument();
    expect(screen.getByTestId("node-slot")).toBeInTheDocument();
  });
});
