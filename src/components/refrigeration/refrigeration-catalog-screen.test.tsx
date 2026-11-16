import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { refrigerationEquipment } from "@/data/refrigeration";
import type { EquipmentLifecycleRepository } from "@/features/refrigeration/equipment-lifecycle-repository";
import { InMemoryRefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";
import type { RefrigerationEquipmentRuntime } from "@/features/refrigeration/equipment-repository-runtime";

import { RefrigerationCatalogScreen } from "./refrigeration-catalog-screen";
import { CreateEquipmentDialog } from "./refrigeration-equipment-dialogs";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/dashboard/sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

vi.mock("@/components/dashboard/topbar", () => ({
  Topbar: ({ title }: { title: string }) => <div>{title}</div>,
}));

const lifecycleRepository: EquipmentLifecycleRepository = {
  async listNodes() {
    return [
      {
        nodeId: "kk2",
        displayName: "Кліматична камера КК2",
        state: "active",
        lastSeenAt: "2026-07-29T12:00:00.000Z",
      },
    ];
  },
  async listClimateChamberChannels() {
    return [];
  },
  async listImages() {
    return [];
  },
  async retireImage() {
    throw new Error("not used");
  },
  async listBindings() {
    return [];
  },
  async listAvailableSensors() {
    return [];
  },
  async replaceSensorConfiguration() {
    throw new Error("not used");
  },
  async bindSensor() {
    throw new Error("not used");
  },
  async unbindSensor() {
    throw new Error("not used");
  },
};

function runtime(): RefrigerationEquipmentRuntime {
  const equipmentRepository = new InMemoryRefrigerationEquipmentRepository(refrigerationEquipment);
  return {
    mode: "demo",
    repository: equipmentRepository,
    equipmentRepository,
    lifecycleRepository,
    sensorConfigurationRepository: lifecycleRepository,
    structuralSnapshotRepository: null,
    controllerBindingRepository: null,
    circuitConfigurationRepository: null,
    thermodynamicsRepository: null,
    telemetryAdapter: null,
    sessionClient: null,
    organizationId: null,
    error: null,
  };
}

describe("RefrigerationCatalogScreen", () => {
  it("filters equipment by search text", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);

    expect(await screen.findByText("Вітрина №106-01")).toBeInTheDocument();
    expect(screen.getByText("Холодильна камера №201")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Пошук обладнання"), {
      target: { value: "Compact 900" },
    });

    expect(screen.getByText("Вітрина №107-02")).toBeInTheDocument();
    expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument();
    expect(screen.queryByText("Холодильна камера №201")).not.toBeInTheDocument();
  });

  it("filters equipment by operational status", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.change(screen.getByLabelText("Фільтр за станом"), {
      target: { value: "warning" },
    });

    expect(screen.getByText("Вітрина №107-02")).toBeInTheDocument();
    expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument();
  });

  it("uses fresh summaries for filtering and expires them if refresh fails", async () => {
    vi.useFakeTimers();
    try {
      const now = new Date("2026-11-16T18:00:00Z");
      vi.setSystemTime(now);
      const item = {
        ...refrigerationEquipment[0]!,
        status: "offline" as const,
        assignedSensors: 2,
        onlineSensors: 2,
        averageTemperatureC: 4.5,
        sensorSummaryValidUntil: new Date(now.getTime() + 11_000).toISOString(),
      };
      const repository = new InMemoryRefrigerationEquipmentRepository([]);
      const load = vi.spyOn(repository, "list").mockResolvedValueOnce([item]);
      load.mockRejectedValue(new Error("disconnected"));
      render(<RefrigerationCatalogScreen runtime={{ ...runtime(), mode: "live", repository }} />);
      await act(async () => vi.advanceTimersByTimeAsync(0));
      const statusFilter = screen.getByLabelText("Фільтр за станом");
      fireEvent.change(statusFilter, { target: { value: "normal" } });
      expect(screen.getByText(item.name)).toBeVisible();
      expect(screen.getByText("2 із 2 онлайн")).toBeVisible();
      expect(screen.getByText("4,5 °C")).toBeVisible();

      await act(async () => vi.advanceTimersByTimeAsync(12_000));
      expect(load).toHaveBeenCalledTimes(2);
      expect(screen.queryByText(item.name)).not.toBeInTheDocument();
      fireEvent.change(statusFilter, { target: { value: "offline" } });
      expect(screen.getByText(item.name)).toBeVisible();
      expect(screen.getByText("0 із 2 онлайн")).toBeVisible();
      expect(screen.queryByText("4,5 °C")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders an explicit empty state when no equipment matches", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.change(screen.getByPlaceholderText("Пошук обладнання"), {
      target: { value: "does-not-exist" },
    });

    expect(screen.getByText("Обладнання не знайдено")).toBeInTheDocument();
  });

  it("adds one compact Embraco status row for a bound controller", async () => {
    const configured = runtime();
    const item = refrigerationEquipment[0];
    configured.controllerBindingRepository = {
      async get() {
        return null;
      },
      async listSummaries() {
        return [
          {
            equipmentId: item.id,
            controllerFamily: "embraco",
            controllerEquipmentId: "EMBRACO-2",
            unitId: 2,
            profileVersion: "embraco-sync-fc03-v1.00.04",
            controlState: 5,
            compressorSpeedRpm: 4500,
            lastSeenAt: new Date().toISOString(),
          },
        ];
      },
    };

    render(<RefrigerationCatalogScreen runtime={configured} />);

    const summary = await screen.findByTestId(`controller-summary-${item.id}`);
    expect(summary).toHaveTextContent("Embraco");
    expect(summary).toHaveTextContent("Pulldown");
    expect(summary).toHaveTextContent("4500 rpm");
    expect(summary).toHaveTextContent("Збережений стан Embraco");
    expect(summary).toHaveTextContent("Останній збережений запис:");
    expect(summary.querySelector("time")).toHaveAttribute("datetime");
    expect(screen.getAllByText("Середня").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Датчики").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Тривоги").length).toBeGreaterThan(0);
  });

  it("keeps long identity readable in compact cards without forcing a chamber", async () => {
    const longName = "Вітрина лабораторна XL з двома зонами температурного контролю і довгою назвою";
    const item = {
      ...refrigerationEquipment[0],
      name: longName,
      location: "Лабораторія з особливо довгим описом розташування та лінією випробувань",
      nodeId: null,
      code: "NX-VERY-LONG-EQUIPMENT-IDENTITY-2026-001",
    };
    const configured = runtime();
    const repository = new InMemoryRefrigerationEquipmentRepository([item]);
    configured.repository = repository;
    configured.equipmentRepository = repository;

    render(<RefrigerationCatalogScreen runtime={configured} />);
    const heading = await screen.findByRole("heading", { name: longName });
    expect(heading).not.toHaveClass("truncate");
    const card = heading.closest("article");
    expect(card).not.toBeNull();
    expect(card?.querySelector(".h-24")).toBeInTheDocument();
    expect(screen.queryByText("Камеру не вибрано")).not.toBeInTheDocument();
    expect(screen.getByText(item.code)).toBeVisible();
    expect(screen.getByRole("link", { name: `Відкрити ${longName}` })).toBeVisible();
    expect(screen.getByText("Датчики")).toHaveClass("text-[11px]");
  });

  it("distinguishes missing or invalid stored controller readings from live telemetry", async () => {
    const configured = runtime();
    const item = refrigerationEquipment[0];
    configured.controllerBindingRepository = {
      async get() {
        return null;
      },
      async listSummaries() {
        return [
          {
            equipmentId: item.id,
            controllerFamily: "embraco",
            controllerEquipmentId: "EMBRACO-2",
            unitId: 2,
            profileVersion: "embraco-sync-fc03-v1.00.04",
            controlState: 5,
            compressorSpeedRpm: 4500,
            lastSeenAt: null,
          },
        ];
      },
    };
    render(<RefrigerationCatalogScreen runtime={configured} />);
    const summary = await screen.findByTestId(`controller-summary-${item.id}`);
    expect(summary).toHaveTextContent("Збережені показники контролера відсутні");
    expect(summary).not.toHaveTextContent("4500 rpm");
    expect(summary).not.toHaveTextContent("Pulldown");
    expect(summary.querySelector("time")).not.toBeInTheDocument();
    expect(summary).not.toHaveTextContent("LIVE");
  });

  it("offers a preselected commissioning route when a controller is not bound", async () => {
    const item = refrigerationEquipment[0];
    render(<RefrigerationCatalogScreen runtime={runtime()} />);

    await screen.findByText(item.name);
    const links = screen.getAllByRole("link", { name: "Підключити контролер →" });
    expect(
      links.some((link) => link.getAttribute("href") === `/equipment/onboarding/new?target=${item.id}`),
    ).toBe(true);
  });

  it("does not offer commissioning when controller summaries are unavailable", async () => {
    const configured = runtime();
    configured.controllerBindingRepository = {
      async get() {
        return null;
      },
      async listSummaries() {
        throw new Error("Controller bindings unavailable");
      },
    };

    render(<RefrigerationCatalogScreen runtime={configured} />);

    expect((await screen.findAllByText("Стан контролера недоступний")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
  });

  it("does not offer commissioning for retired equipment", async () => {
    const retired = { ...refrigerationEquipment[0], lifecycleStatus: "retired" as const };
    const configured = runtime();
    const equipmentRepository = new InMemoryRefrigerationEquipmentRepository([retired]);
    configured.repository = equipmentRepository;
    configured.equipmentRepository = equipmentRepository;

    render(<RefrigerationCatalogScreen runtime={configured} />);

    await screen.findByText(retired.name);
    expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
  });

  it("does not offer commissioning while controller summaries are unresolved", async () => {
    const configured = runtime();
    configured.controllerBindingRepository = {
      async get() {
        return null;
      },
      listSummaries: () => new Promise(() => undefined),
    };

    render(<RefrigerationCatalogScreen runtime={configured} />);

    expect((await screen.findAllByText("Завантаження стану контролера…")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Підключити контролер →" })).not.toBeInTheDocument();
  });

  it("creates equipment with no climate chamber", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.click(screen.getByRole("button", { name: "Додати холодильне обладнання" }));
    expect(screen.getByLabelText(/^Кліматична камера/)).toHaveValue("");
    expect(screen.queryByLabelText(/^Кількість слотів датчиків/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^Назва/)).toBeEnabled();

    fireEvent.change(screen.getByLabelText(/^Назва/), {
      target: { value: "Вітрина №108-01" },
    });
    fireEvent.change(screen.getByLabelText(/^Код обладнання/), {
      target: { value: "CS-P1250-2026-108-01" },
    });
    fireEvent.change(screen.getByLabelText(/^Відображуване розташування/), {
      target: { value: "Лабораторія 1 · Зона C" },
    });
    fireEvent.change(screen.getByLabelText(/^Виробник/), {
      target: { value: "NEXOLAB" },
    });
    fireEvent.change(screen.getByLabelText(/^Модель/), {
      target: { value: "NX-1250" },
    });
    fireEvent.change(screen.getByLabelText(/^Серійний номер/), {
      target: { value: "NX-10801" },
    });
    fireEvent.change(screen.getByLabelText(/^Температурний клас/), {
      target: { value: "3M1 (0…+5 °C)" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Створити" }));

    expect(await screen.findByText("Вітрина №108-01")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("додано до каталогу");
    expect(screen.getByRole("link", { name: "Відкрити Вітрина №108-01" })).toBeInTheDocument();
  });

  it("creates an independent copy without requiring a chamber", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    const source = refrigerationEquipment[0];
    await screen.findByText(source.name);

    fireEvent.click(screen.getByRole("button", { name: `Копіювати ${source.name}` }));

    expect(screen.getByRole("heading", { name: "Копія холодильного обладнання" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Кліматична камера/)).toHaveValue("");
    expect(screen.getByLabelText(/^Назва/)).toBeEnabled();
    expect(screen.getByText(/датчики, фото, схеми, історія й аудит не копіюються/i)).toBeInTheDocument();

    expect(screen.getByLabelText(/^Назва/)).toHaveValue(`${source.name} — копія`);
    expect(screen.getByLabelText(/^Код обладнання/)).toHaveValue(`${source.code}-COPY`);
    expect(screen.getByLabelText(/^Серійний номер/)).toHaveValue("");

    fireEvent.change(screen.getByLabelText(/^Серійний номер/), {
      target: { value: "COPY-SN-001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Створити копію" }));

    expect(await screen.findByText(`${source.name} — копія`)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("створено як незалежну копію");
  });

  it("keeps entered passport fields when the catalog rerenders or saving fails", () => {
    const onSubmit = vi.fn(async () => undefined);
    const { rerender } = render(
      <CreateEquipmentDialog open busy={false} error={null} onClose={() => {}} onSubmit={onSubmit} />,
    );
    const name = screen.getByLabelText(/^Назва/);
    fireEvent.change(name, { target: { value: "Вітрина №108-01" } });

    rerender(<CreateEquipmentDialog open busy error={null} onClose={() => {}} onSubmit={onSubmit} />);
    rerender(
      <CreateEquipmentDialog
        open
        busy={false}
        error="Помилка збереження"
        onClose={() => {}}
        onSubmit={onSubmit}
      />,
    );
    expect(name).toHaveValue("Вітрина №108-01");
    expect(screen.getByText("Помилка збереження")).toBeVisible();
  });

  it("deletes equipment through the destructive confirmation dialog", async () => {
    render(<RefrigerationCatalogScreen runtime={runtime()} />);
    await screen.findByText("Вітрина №106-01");

    fireEvent.click(screen.getByRole("button", { name: "Видалити Вітрина №106-01" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Видалити" }));

    await waitFor(() => expect(screen.queryByText("Вітрина №106-01")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("видалено з каталогу");
  });
});
