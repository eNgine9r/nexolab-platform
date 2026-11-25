import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KpiCard } from "./kpi-card";

describe("KpiCard", () => {
  it("renders the metric label, value and details", () => {
    render(
      <KpiCard
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
  it("retains complete secondary labels with readable text sizes", () => {
    render(
      <KpiCard
        item={{
          label: "Довгий підпис лабораторного показника",
          value: "—",
          detail: "Немає актуальних даних",
          trend: "З'єднання втрачено",
          tone: "amber",
          icon: "temperature",
          badge: "offline",
          badgeTone: "offline",
        }}
      />,
    );

    const label = screen.getByText("Довгий підпис лабораторного показника");
    expect(label).toHaveClass("text-[11px]");
    expect(label).not.toHaveClass("truncate");
    expect(screen.getByText("Немає актуальних даних")).toBeVisible();
    expect(screen.getByText("З'єднання втрачено")).toBeVisible();
    expect(screen.getByText("offline")).toBeVisible();
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("keeps live freshness visible without relying on color alone", () => {
    render(
      <KpiCard
        item={{
          label: "Вузлів онлайн",
          value: "6 / 6",
          detail: "100% доступності",
          trend: "Свіжі дані",
          tone: "green",
          icon: "network",
          badge: "live",
          badgeTone: "live",
        }}
      />,
    );

    expect(screen.getByText("LIVE")).toBeVisible();
  });
  it("keeps the Overview cards calm without duplicating the global live/demo indicator", () => {
    render(
      <KpiCard
        variant="overview"
        item={{
          label: "Вузлів онлайн",
          value: "6 / 6",
          detail: "100% доступності",
          trend: "За останню годину",
          tone: "green",
          icon: "network",
          badge: "demo",
          badgeTone: "demo",
        }}
      />,
    );

    expect(screen.getByText("6 / 6")).toBeVisible();
    expect(screen.getByText("100% доступності")).toBeVisible();
    expect(screen.queryByText("demo")).not.toBeInTheDocument();
  });

  it("keeps unsafe data quality explicit in the compact Overview card", () => {
    render(
      <KpiCard
        variant="overview"
        item={{
          label: "Датчики",
          value: "—",
          detail: "Дані застаріли",
          trend: "",
          tone: "amber",
          icon: "signal",
          badge: "stale",
          badgeTone: "stale",
        }}
      />,
    );

    expect(screen.getByText("stale")).toBeVisible();
    expect(screen.getByText("Дані застаріли")).toBeVisible();
  });
});
