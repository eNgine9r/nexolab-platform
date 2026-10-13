import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EnergyExportDialog } from "./energy-export-dialog";
import type { EnergyExportController } from "@/features/energy/use-energy-export";
import type { EnergyExportJob } from "@/features/energy/energy-export-client";

const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-01T09:00:00Z"));
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
  vi.useRealTimers();
  for (const [name, descriptor] of [
    ["showModal", originalShowModal],
    ["close", originalClose],
  ] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});
function model(): EnergyExportController {
  return {
    catalog: {
      retention_days: 365,
      items: [
        {
          node_id: "edge-01",
          equipment_id: "LE01MP-200",
          channel_id: "200-voltage",
          metric: "electrical.voltage",
          unit: "V",
          equipment_name: "Випробування W1",
          meter_label: "W1",
          parameter_name: "Напруга",
        },
        {
          node_id: "edge-01",
          equipment_id: "SDM120M-1",
          channel_id: "1-voltage",
          metric: "electrical.voltage",
          unit: "V",
          equipment_name: "Випробування SDM",
          meter_label: "SDM120M",
          parameter_name: "Напруга",
        },
      ],
    },
    catalogStatus: "ready",
    job: null,
    busy: false,
    error: null,
    refreshCatalog: vi.fn().mockResolvedValue(undefined),
    preview: vi.fn().mockResolvedValue(true),
    confirm: vi.fn().mockResolvedValue(true),
    cancel: vi.fn().mockResolvedValue(true),
    reset: vi.fn().mockResolvedValue(true),
    refreshJob: vi.fn().mockResolvedValue(true),
    download: vi.fn().mockResolvedValue(true),
  };
}
const defaults = [{ unitId: 200, metric: "electrical.voltage" as const }];
function custom(from: string, to: string) {
  fireEvent.click(screen.getByRole("button", { name: "Власний період" }));
  fireEvent.change(screen.getByLabelText("Початок · Europe/Kyiv"), { target: { value: from } });
  fireEvent.change(screen.getByLabelText("Завершення · Europe/Kyiv"), { target: { value: to } });
}
describe("Energy export dialog", () => {
  it("selects graph parameters, all meters, exact custom Kyiv times and supported formats", async () => {
    const controller = model();
    render(<EnergyExportDialog model={controller} defaults={defaults} onClose={vi.fn()} />);
    expect(screen.getByRole("option", { name: /10 секунд/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Вибрати всі доступні лічильники" }));
    custom("2026-10-13T10:00", "2026-10-13T11:00");
    fireEvent.change(screen.getByLabelText("Формат"), { target: { value: "csv" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Попередній перегляд" })));
    expect(controller.preview).toHaveBeenCalledWith(
      expect.objectContaining({
        from: "2026-10-13T07:00:00.000Z",
        to: "2026-10-13T08:00:00.000Z",
        format: "csv",
        step_seconds: 0,
      }),
    );
    expect(vi.mocked(controller.preview).mock.calls[0][0].series).toHaveLength(2);
  });
  it("rejects spring gaps and requires an autumn offset before preview", async () => {
    const controller = model();
    render(<EnergyExportDialog model={controller} defaults={defaults} onClose={vi.fn()} />);
    custom("2026-03-29T03:30", "2026-03-29T04:30");
    expect(screen.getByText(/Цей час не існує/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Попередній перегляд" })).toBeDisabled();
    custom("2026-10-25T03:30", "2026-10-25T04:30");
    expect(screen.getByRole("button", { name: "Попередній перегляд" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Початок · Europe/Kyiv · входження часу"), {
      target: { value: "2026-10-25T01:30:00.000Z" },
    });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Попередній перегляд" })));
    expect(controller.preview).toHaveBeenCalledWith(
      expect.objectContaining({ from: "2026-10-25T01:30:00.000Z", to: "2026-10-25T02:30:00.000Z" }),
    );
  });
  it("invalidates prepared counts when step or format changes", () => {
    const controller = model();
    const selected = controller.catalog!.items[0];
    controller.job = {
      job_id: "a".repeat(32),
      status: "preview_ready",
      phase: "preview",
      created_at: "2026-10-13T09:00:00Z",
      expires_at: "2026-10-13T10:00:00Z",
      options: {
        series: [selected],
        from: "2026-07-23T09:00:00Z",
        to: "2026-07-23T10:00:00Z",
        step_seconds: 0,
        statistics: ["avg"],
        format: "xlsx",
      },
      progress: { processed: 3, total: 3, unit: "source_events" },
      preview: {
        source_events: 3,
        output_rows: 3,
        estimated_bytes: 4000,
        available_steps: [0, 60, 300],
        actual_first_utc: "2026-07-23T09:00:00Z",
        actual_last_utc: "2026-07-23T09:01:00Z",
        snapshot_at: "2026-10-13T09:00:00Z",
        retention_days: 365,
        warnings: [],
      },
      artifact: null,
      error: null,
    } satisfies EnergyExportJob;
    render(<EnergyExportDialog model={controller} defaults={defaults} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Сформувати XLSX" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Крок даних у файлі"), { target: { value: "60" } });
    expect(screen.queryByRole("button", { name: "Сформувати XLSX" })).not.toBeInTheDocument();
    expect(screen.getByText(/Налаштування змінено/)).toBeVisible();
    expect(controller.confirm).not.toHaveBeenCalled();
  });
});
