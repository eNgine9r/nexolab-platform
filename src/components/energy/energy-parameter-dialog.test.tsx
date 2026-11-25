import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EnergySeriesSelection } from "@/features/energy/energy-series-selection";

import { EnergyParameterDialog } from "./energy-parameter-dialog";

const previousShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const previousClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
});

afterEach(() => {
  cleanup();
  for (const [name, descriptor] of [
    ["showModal", previousShowModal],
    ["close", previousClose],
  ] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});

const selected: EnergySeriesSelection[] = [
  { unitId: 200, metric: "electrical.voltage" },
  { unitId: 1, metric: "electrical.current" },
];

describe("EnergyParameterDialog compact meter/metric filtering", () => {
  it("searches by meter and metric without dropping hidden selected pairs", () => {
    const onApply = vi.fn();
    const onClose = vi.fn();
    render(<EnergyParameterDialog selected={selected} onApply={onApply} onClose={onClose} />);

    const search = screen.getByRole("searchbox", { name: "Пошук лічильника або показника" });
    expect(screen.getByText(/5 із 5 лічильників · 2 серій обрано/)).toBeVisible();

    fireEvent.change(search, { target: { value: "W1" } });
    expect(screen.getByRole("checkbox", { name: "W1 · Напруга" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "SDM120M · Струм" })).not.toBeInTheDocument();
    expect(screen.getByText(/1 із 5 лічильників · 2 серій обрано/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Лише вибрані" }));
    expect(screen.getByRole("button", { name: "Лише вибрані" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: "SDM120M · Струм" })).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Застосувати" }));
    expect(onApply).toHaveBeenCalledTimes(1);
    const applied = onApply.mock.calls[0]?.[0] as EnergySeriesSelection[];
    expect(applied).toHaveLength(2);
    expect(applied).toEqual(expect.arrayContaining(selected));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("finds one metric across meters and never enables unsupported SDM temperature", () => {
    render(<EnergyParameterDialog selected={[]} onApply={vi.fn()} onClose={vi.fn()} />);
    const search = screen.getByRole("searchbox", { name: "Пошук лічильника або показника" });

    fireEvent.change(search, { target: { value: "Струм" } });
    expect(screen.getAllByRole("checkbox")).toHaveLength(5);
    expect(screen.getByRole("checkbox", { name: "W4 · Струм" })).toBeVisible();

    fireEvent.change(search, { target: { value: "температура" } });
    expect(screen.getByRole("checkbox", { name: "SDM120M · Температура лічильника" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Лише вибрані" }));
    expect(screen.getByText("За цими умовами показників немає")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Показати всі параметри" }));
    expect(search).toHaveValue("");
    expect(screen.getByRole("button", { name: "Лише вибрані" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("checkbox", { name: "SDM120M · Температура лічильника" })).toBeDisabled();
  });

  it("does not commit draft edits when closing after filtering", () => {
    const onApply = vi.fn();
    const onClose = vi.fn();
    render(<EnergyParameterDialog selected={selected} onApply={onApply} onClose={onClose} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Пошук лічильника або показника" }), {
      target: { value: "W1" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "W1 · Активна потужність" }));
    expect(screen.getByText(/3 серій обрано/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Закрити вибір параметрів" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
