import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CommissionedControllerAssociation } from "@/features/equipment/commissioned-controller-association";
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

function danfossAssociation(): CommissionedControllerAssociation {
  return {
    profile: {
      id: "danfoss-ak-cc25-pro",
      version: "danfoss-ak-cc25-pro-sw1.3x-fc03-v1",
      deviceFamily: "akcc25",
      deviceClass: "temperature-controller",
      manufacturer: "Danfoss",
      models: ["AK-CC25 Pro"],
      displayName: "Danfoss AK-CC25 Pro",
      transportKind: "modbus_rtu",
      capabilityStatus: "repository_supported_hardware_evidenced",
      evidenceNote: "Real Unit 35 FC03 evidence",
      readOnly: true,
      activationSupported: false,
    },
    session: {
      id: "commissioning-danfoss-35",
      lifecycle: "verified",
      deviceClass: "temperature-controller",
      manufacturer: "Danfoss",
      model: "AK-CC25 Pro",
      profileId: "danfoss-ak-cc25-pro",
      profileVersion: "danfoss-ak-cc25-pro-sw1.3x-fc03-v1",
      transportKind: "modbus_rtu",
      nodeId: "nexolab-edge-01",
      busId: "commissioning-a10q2si7",
      stableTransportIdentifier: "/dev/serial/by-id/usb-FTDI_A10Q2SI7-if00-port0",
      unitId: 35,
      ipAddress: null,
      targetEquipmentKey: "showcase-106-01",
      blockedReason: null,
      unsupportedReason: null,
      version: 3,
      createdBy: "engineer",
      updatedBy: "engineer",
      createdAt: "2026-09-24T10:00:00Z",
      updatedAt: "2026-09-24T10:05:00Z",
      cancelledAt: null,
    },
  };
}

function boundController(): RefrigerationControllerModel {
  const controller = failedController();
  controller.latestError = null;
  controller.binding = {
    id: "binding-1",
    equipmentId: "showcase-106-01",
    nodeId: "nexolab-edge-01",
    controllerFamily: "embraco",
    controllerEquipmentId: "EMBRACO-2",
    unitId: 2,
    profileVersion: "embraco-sync-fc03-v1.00.04",
    boundAt: "2026-09-01T12:00:00Z",
    verifiedFromTelemetry: true,
  };
  return controller;
}

describe("refrigeration controller binding failure states", () => {
  it.each([
    ["overview", RefrigerationControllerOverview],
    ["detail", RefrigerationControllerDetail],
  ])("fails closed in the %s instead of offering commissioning", (_name, Component) => {
    render(<Component controller={failedController()} equipmentId="showcase-106-01" canCommission />);

    expect(screen.getByRole("alert")).toHaveTextContent("Не вдалося отримати прив’язку контролера.");
    expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
  });
  it.each([
    ["overview", RefrigerationControllerOverview],
    ["detail", RefrigerationControllerDetail],
  ])("hides commissioning in the %s when permission or lifecycle denies it", (_name, Component) => {
    const controller = failedController();
    controller.latestError = null;

    render(<Component controller={controller} equipmentId="showcase-106-01" canCommission={false} />);

    expect(screen.getByText("○ Контролер не підключено")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
  });

  it.each([
    ["overview", RefrigerationControllerOverview],
    ["detail", RefrigerationControllerDetail],
  ])(
    "shows a verified discovery-only Danfoss association in the %s without claiming live monitoring",
    (_name, Component) => {
      const controller = failedController();
      controller.latestError = null;

      render(
        <Component
          controller={controller}
          equipmentId="showcase-106-01"
          canCommission
          commissionedAssociation={danfossAssociation()}
        />,
      );

      expect(screen.getByText("Danfoss AK-CC25 Pro")).toBeInTheDocument();
      expect(screen.getByText("Перевірено · моніторинг вимкнено")).toBeInTheDocument();
      expect(screen.getByText(/Production polling і live KPI ще не активовані/)).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
    },
  );

  it.each([
    ["overview", RefrigerationControllerOverview, "refrigeration-controller-overview"],
    ["detail", RefrigerationControllerDetail, "refrigeration-controller-detail"],
  ])(
    "keeps an active Embraco binding authoritative over discovery-only association in the %s",
    (_name, Component, testId) => {
      render(
        <Component
          controller={boundController()}
          equipmentId="showcase-106-01"
          canCommission
          commissionedAssociation={danfossAssociation()}
        />,
      );

      expect(screen.queryByTestId("commissioned-controller-association")).not.toBeInTheDocument();
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    },
  );
});
