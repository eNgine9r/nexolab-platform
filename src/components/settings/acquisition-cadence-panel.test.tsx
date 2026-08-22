import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AcquisitionCadenceController } from "@/features/acquisition/use-acquisition-cadence";

import { AcquisitionCadencePanel } from "./acquisition-cadence-panel";

function controller(overrides: Partial<AcquisitionCadenceController> = {}): AcquisitionCadenceController {
  return {
    configuration: {
      schemaVersion: 1,
      registryRevision: 7,
      updatedAt: "2026-08-22T17:00:00+00:00",
      presetsSeconds: [10, 30, 60],
      customMinSeconds: 10,
      maximumSeconds: 3600,
      familyDefaults: [
        { busId: "rs485-kk2", deviceFamily: "xjp60d", intervalSeconds: 10 },
        { busId: "rs485-kk1", deviceFamily: "le01mp", intervalSeconds: 30 },
      ],
      deviceOverrides: [{ deviceId: "xjp60d-106", intervalSeconds: 60 }],
      effectiveDevices: [
        {
          deviceId: "xjp60d-106",
          busId: "rs485-kk2",
          deviceFamily: "xjp60d",
          lifecycle: "active",
          effectiveIntervalSeconds: 60,
          cadenceSource: "device_override",
        },
        {
          deviceId: "le01mp-200",
          busId: "rs485-kk1",
          deviceFamily: "le01mp",
          lifecycle: "active",
          effectiveIntervalSeconds: 30,
          cadenceSource: "family_default",
        },
      ],
      capacity: {
        safe: true,
        maximumAllowedUtilizationPercent: 75,
        safetyMarginPercent: 25,
        buses: [
          {
            busId: "rs485-kk2",
            safe: true,
            activeDeviceCount: 1,
            activeTargetCount: 2,
            estimatedUtilizationPercent: 14.5,
            maximumAllowedUtilizationPercent: 75,
            recommendedMinimumIntervalSeconds: null,
            requestBudgetSource: "measured_p95",
          },
        ],
      },
    },
    isLoading: false,
    isSaving: false,
    error: null,
    refresh: vi.fn(async () => undefined),
    setFamilyDefault: vi.fn(async () => true),
    setDeviceOverride: vi.fn(async () => true),
    ...overrides,
  };
}

describe("AcquisitionCadencePanel", () => {
  it("separates physical polling from presentation and mutates family defaults", () => {
    const value = controller();
    render(<AcquisitionCadencePanel controller={value} canManage />);

    expect(screen.getByRole("heading", { name: "Фізичний інтервал опитування" })).toBeVisible();
    expect(screen.getByText(/Refresh графіків.*не змінюють фізичне опитування/)).toBeVisible();
    expect(screen.getByText("Registry revision: 7")).toBeVisible();

    const xjpCard = screen.getByText("Dixell XJP60D", { exact: true }).closest("article");
    expect(xjpCard).not.toBeNull();
    fireEvent.click(within(xjpCard as HTMLElement).getByRole("button", { name: "30 с" }));
    fireEvent.click(within(xjpCard as HTMLElement).getByRole("button", { name: "Застосувати" }));

    expect(value.setFamilyDefault).toHaveBeenCalledWith("rs485-kk2", "xjp60d", 30);
  });

  it("rejects a custom value below the server product floor before mutation", () => {
    const value = controller();
    render(<AcquisitionCadencePanel controller={value} canManage />);

    const xjpCard = screen.getByText("Dixell XJP60D", { exact: true }).closest("article");
    expect(xjpCard).not.toBeNull();
    fireEvent.click(within(xjpCard as HTMLElement).getByRole("button", { name: "Custom" }));
    fireEvent.change(within(xjpCard as HTMLElement).getByLabelText("Інтервал, секунд"), {
      target: { value: "9" },
    });

    expect(within(xjpCard as HTMLElement).getByRole("alert")).toHaveTextContent(
      "Мінімальний інтервал — 10 секунд.",
    );
    expect(within(xjpCard as HTMLElement).getByRole("button", { name: "Застосувати" })).toBeDisabled();
    expect(value.setFamilyDefault).not.toHaveBeenCalled();
  });

  it("returns a physical device override to inherited cadence", () => {
    const value = controller();
    render(<AcquisitionCadencePanel controller={value} canManage />);

    const deviceCard = screen.getByText("xjp60d-106", { exact: true }).closest("article");
    expect(deviceCard).not.toBeNull();
    expect(within(deviceCard as HTMLElement).getByText("Override 60 с")).toBeVisible();
    fireEvent.click(within(deviceCard as HTMLElement).getByRole("button", { name: "Успадкувати 10 с" }));

    expect(value.setDeviceOverride).toHaveBeenCalledWith("xjp60d-106", null);
  });

  it("shows server-authoritative capacity rejection without a bypass", () => {
    render(
      <AcquisitionCadencePanel
        canManage
        controller={controller({
          error: {
            code: "acquisition_capacity_exceeded",
            message: "Requested acquisition cadence exceeds RS-485 capacity: rs485-kk2",
            capacity: {
              safe: false,
              maximumAllowedUtilizationPercent: 75,
              safetyMarginPercent: 25,
              buses: [
                {
                  busId: "rs485-kk2",
                  safe: false,
                  activeDeviceCount: 15,
                  activeTargetCount: 30,
                  estimatedUtilizationPercent: 92.4,
                  maximumAllowedUtilizationPercent: 75,
                  recommendedMinimumIntervalSeconds: 30,
                  requestBudgetSource: "serial_timeout_fallback",
                },
              ],
            },
          },
        })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Запитаний інтервал небезпечний для активної RS-485 шини",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("рекомендовано не швидше 30 с");
    expect(screen.queryByRole("button", { name: /force|примус/i })).not.toBeInTheDocument();
  });

  it("renders read-only state when equipment.manage is absent", () => {
    render(<AcquisitionCadencePanel controller={controller()} canManage={false} />);

    expect(screen.getByText(/Доступ лише для перегляду/)).toBeVisible();
    expect(
      screen
        .getAllByRole("button", { name: "Застосувати" })
        .every((button) => button.hasAttribute("disabled")),
    ).toBe(true);
  });
});
