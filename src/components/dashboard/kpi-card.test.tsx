import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KpiCard } from "./kpi-card";

describe("KpiCard", () => {
  it("renders the metric label, value and details", () => {
    render(
      <KpiCard
        index={0}
        item={{
          label: "Вузлів онлайн",
          value: "6 / 6",
          detail: "100% доступності",
          trend: "+0,4% за 7 днів",
          tone: "blue",
          icon: "network",
        }}
      />,
    );

    expect(screen.getByText("Вузлів онлайн")).toBeInTheDocument();
    expect(screen.getByText("6 / 6")).toBeInTheDocument();
    expect(screen.getByText("100% доступності")).toBeInTheDocument();
  });
});
