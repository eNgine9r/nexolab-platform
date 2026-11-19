import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverviewWorkspaceLayout } from "./overview-workspace-layout";

describe("OverviewWorkspaceLayout", () => {
  it("places the temperature chart beside a compact alerts and infrastructure column", () => {
    render(
      <OverviewWorkspaceLayout
        primary={<div data-testid="graph-slot">Graph</div>}
        attention={<div data-testid="attention-slot">Attention</div>}
        supporting={<div data-testid="node-slot">Nodes</div>}
      />,
    );

    const commandGrid = screen.getByTestId("overview-command-grid");
    const primary = screen.getByTestId("overview-primary-workspace");
    const insights = screen.getByTestId("overview-insights-column");
    const attention = screen.getByTestId("overview-attention-workspace");
    const supporting = screen.getByTestId("overview-secondary-grid");

    expect(commandGrid).toContainElement(primary);
    expect(commandGrid).toContainElement(insights);
    expect(insights).toContainElement(attention);
    expect(insights).toContainElement(supporting);
    expect(primary).toHaveClass("xl:col-span-8");
    expect(insights).toHaveClass("xl:col-span-4");
    expect(commandGrid).toHaveClass("grid-cols-1");
    expect(screen.getByTestId("graph-slot")).toBeInTheDocument();
    expect(screen.getByTestId("attention-slot")).toBeInTheDocument();
    expect(screen.getByTestId("node-slot")).toBeInTheDocument();
  });

  it("retains permitted infrastructure if alarms are unavailable", () => {
    render(
      <OverviewWorkspaceLayout
        primary={<div>Temperature</div>}
        attention={null}
        supporting={<div>Nodes</div>}
      />,
    );
    expect(screen.queryByTestId("overview-attention-workspace")).not.toBeInTheDocument();
    expect(screen.getByTestId("overview-secondary-grid")).toHaveTextContent("Nodes");
  });

  it("omits the insights column when permissions disallow both sections", () => {
    render(<OverviewWorkspaceLayout primary={<div>Temperature</div>} attention={null} supporting={null} />);
    expect(screen.queryByTestId("overview-insights-column")).not.toBeInTheDocument();
    expect(screen.getByTestId("overview-primary-workspace")).toBeInTheDocument();
  });
});
