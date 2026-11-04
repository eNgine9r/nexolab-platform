import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type {
  CommissioningRepository,
  CommissioningSession,
  CommissioningSessionWrite,
  SupportedDeviceProfile,
} from "@/features/equipment/commissioning-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import { QuickDeviceSetup } from "./quick-device-setup";

const profile = {
  id: "dixell-xjp60d",
  version: "v1",
  displayName: "Dixell XJP60D",
  deviceClass: "temperature-controller",
  manufacturer: "Dixell",
  models: ["XJP60D"],
  activationSupported: true,
} as SupportedDeviceProfile;
const draft = {
  deviceClass: profile.deviceClass,
  manufacturer: "Dixell",
  model: "XJP60D",
  profileId: profile.id,
  nodeId: "edge-01",
  busId: "rs485-main",
  stableTransportIdentifier: "/dev/serial/by-id/usb-test",
  unitId: 7,
  ipAddress: null,
  targetEquipmentKey: null,
};
const ready = {
  ...draft,
  id: "session-1",
  version: 1,
  targetEquipmentKey: "equipment-1",
  lifecycle: "ready_for_preflight",
} as CommissioningSession;

function setup(passed = true) {
  const create = vi.fn().mockResolvedValue({ id: "equipment-1" });
  const runPreflight = vi.fn().mockResolvedValue({ result: passed ? "passed" : "failed" });
  const runActivation = vi.fn().mockResolvedValue({ state: "active" });
  const repository = {
    createSession: vi.fn().mockResolvedValue(ready),
    runPreflight,
    runActivation,
    getSession: vi
      .fn()
      .mockResolvedValueOnce({ ...ready, version: 2, lifecycle: passed ? "verified" : "ready_for_preflight" })
      .mockResolvedValue({ ...ready, version: 3, lifecycle: "active" }),
  } as unknown as CommissioningRepository;
  const props = {
    repository,
    equipmentRepository: { create } as unknown as RefrigerationEquipmentRepository,
    profiles: [profile],
    inventory: {
      schemaVersion: 1 as const,
      nodeId: "edge-01",
      connections: [
        {
          busId: draft.busId,
          stableTransportIdentifier: draft.stableTransportIdentifier,
          ownership: "production_bus" as const,
          present: true,
          availableForPreflight: true,
          serial: null,
        },
      ],
    },
    inventoryError: null,
    equipment: [],
    draft,
    onDraft: vi.fn(),
    onInventory: vi.fn(),
    onSaved: vi.fn(),
    onAdvanced: vi.fn(),
    canManage: true,
  };
  const view = render(<QuickDeviceSetup {...props} />);
  return { create, repository, runPreflight, runActivation, props, ...view };
}

describe("quick device setup", () => {
  it("adds a named standalone instrument without creating a refrigeration passport", async () => {
    const { create, repository } = setup();
    create.mockRejectedValue(new Error("Refrigeration service must not be needed"));
    fireEvent.change(screen.getByLabelText("Назва приладу"), { target: { value: "Dixell 2 — стенд" } });
    fireEvent.click(screen.getByRole("button", { name: "Додати прилад" }));
    expect(await screen.findByText("Прилад додано. Моніторинг увімкнено.")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    expect(repository.createSession).toHaveBeenCalledWith(
      expect.objectContaining({ displayName: "Dixell 2 — стенд", targetEquipmentKey: null }),
      expect.any(String),
    );
    expect(screen.queryByText("Прив’язати до наявного обладнання")).not.toBeInTheDocument();
  });

  it("scans a configured adapter in auto mode and keeps the full result list when selecting a device", async () => {
    const { props, rerender } = setup();
    const searchAddress = vi.fn().mockImplementation(async ({ unitId }) => ({
      state: "completed",
      candidates: [3, 7].includes(unitId) ? [unitId] : [],
      exceptionAddresses: [],
      errorCode: null,
    }));
    const scanRepository = { ...props.repository, searchAddress };
    function Harness() {
      const [current, setCurrent] = useState<CommissioningSessionWrite>({
        ...draft,
        profileId: null as string | null,
        unitId: null as number | null,
      });
      return (
        <QuickDeviceSetup
          {...props}
          repository={scanRepository}
          profiles={[{ ...profile, version: "dixell-xjp60d-fc03-v1" }]}
          inventory={{
            ...props.inventory,
            connections: [{ ...props.inventory.connections[0], availableForReadSearch: true }],
          }}
          draft={current}
          onDraft={setCurrent}
        />
      );
    }
    rerender(<Harness />);
    expect(screen.getByLabelText("Модель приладу")).toHaveValue("");
    expect(
      screen.queryByText(/Автоматичний пошук для цього підключення недоступний/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Знайти прилади" }));
    await screen.findByText(/Пошук завершено/);
    expect(searchAddress).toHaveBeenCalledTimes(247);
    expect(screen.getByRole("status")).toHaveTextContent("Знайдено адрес із приладами: 2");
    fireEvent.click(screen.getByRole("button", { name: "Вибрати адресу 7" }));
    expect(screen.getByLabelText("Адреса приладу")).toHaveValue(7);
    expect(screen.getByRole("status")).toHaveTextContent("Знайдено адрес із приладами: 2");
  });

  it("saves the entered name and checks/activates with a single Add action", async () => {
    const { create, runPreflight, runActivation } = setup();
    expect(screen.getByLabelText("Назва приладу")).toHaveValue("Dixell XJP60D · 7");
    fireEvent.change(screen.getByLabelText("Назва приладу"), { target: { value: "Dixell — стенд" } });
    fireEvent.click(screen.getByRole("button", { name: "Додати прилад" }));
    expect(await screen.findByText("Прилад додано. Моніторинг увімкнено.")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    expect(runPreflight).toHaveBeenCalledTimes(1);
    expect(runActivation).toHaveBeenCalledTimes(1);
  });

  it("keeps a failed read honest and reuses the saved records on retry", async () => {
    const { create, repository, runActivation } = setup(false);
    fireEvent.change(screen.getByLabelText("Назва приладу"), { target: { value: "Тестовий контролер" } });
    fireEvent.click(screen.getByRole("button", { name: "Додати прилад" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("не відповідає");
    expect(runActivation).not.toHaveBeenCalled();
    expect(screen.queryByText("Прилад додано. Моніторинг увімкнено.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторити перевірку" }));
    await waitFor(() => expect(repository.runPreflight).toHaveBeenCalledTimes(2));
    expect(create).not.toHaveBeenCalled();
    expect(repository.createSession).toHaveBeenCalledTimes(1);
  });

  it("offers another device without recreating the completed session", async () => {
    const { props, repository } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Додати прилад" }));
    await screen.findByText("Прилад додано. Моніторинг увімкнено.");
    fireEvent.click(screen.getByRole("button", { name: "Додати ще один" }));
    expect(props.onDraft).toHaveBeenCalledWith(
      expect.objectContaining({ unitId: null, targetEquipmentKey: null }),
    );
    expect(repository.createSession).toHaveBeenCalledTimes(1);
  });

  it("offers advanced settings without starting any hardware operation", () => {
    const { props, repository } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Розширені налаштування" }));
    expect(props.onAdvanced).toHaveBeenCalledTimes(1);
    expect(repository.runPreflight).not.toHaveBeenCalled();
  });
});
