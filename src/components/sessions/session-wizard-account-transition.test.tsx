import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SessionWizard } from "./session-wizard";

const mock = vi.hoisted(() => ({
  push: vi.fn(),
  create: vi.fn(),
  binding: vi.fn(),
  limits: vi.fn(),
  lock: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mock.push }) }));
vi.mock("@/components/dashboard/platform-account-boundary", () => ({
  usePlatformAccount: () => ({ security: { membership: null }, setOperationPending: mock.lock }),
}));
vi.mock("@/hooks/use-live-dashboard-inventory", () => ({
  useLiveDashboardInventory: () => ({ items: [], status: "ready", error: null, retry: vi.fn() }),
}));
vi.mock("@/features/test-sessions/telemetry-selection", () => ({
  buildSessionTelemetrySelectionModel: () => ({}),
  resolveSelectedSessionBindings: () => [
    {
      node_id: "edge-01",
      equipment_id: "K106",
      channel_id: "106-03",
      metric: "temperature.probe",
      unit: "degC",
    },
  ],
}));
vi.mock("./wizard-steps", () => ({
  GeneralStep: () => null,
  ObjectStep: () => null,
  MethodStep: () => null,
  EquipmentStep: () => null,
  SamplingStep: () => null,
  LimitsStep: () => null,
  StagesStep: () => null,
  ReviewStep: () => null,
}));
vi.mock("./wizard-model", async (original) => {
  const actual = await original<typeof import("./wizard-model")>();
  return {
    ...actual,
    isWizardStepValid: () => true,
    createInitialWizardForm: () => ({
      ...actual.createInitialWizardForm(),
      selectedTelemetryKeys: ["probe"],
    }),
  };
});
vi.mock("@/lib/sessions/api-client", async (original) => ({
  ...(await original<object>()),
  createSessionApiClient: () => ({
    listProductionBindingOptions: async () => [],
    createSession: mock.create,
    addBinding: mock.binding,
    addLimitSet: mock.limits,
  }),
}));
beforeEach(() => {
  mock.push.mockClear();
  mock.lock.mockClear();
  mock.create.mockReset().mockResolvedValue({ session: { id: "old-org-draft" } });
  mock.binding.mockReset().mockResolvedValue({});
  mock.limits.mockReset().mockResolvedValue({});
});
afterEach(() => vi.unstubAllEnvs());

it.each(["create", "binding", "limits"] as const)(
  "cancels %s and suppresses further work/navigation when its account workspace unmounts",
  async (stage) => {
    let finish!: (value: unknown) => void;
    mock[stage].mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { unmount } = render(<SessionWizard />);
    for (let step = 0; step < 7; step++) {
      const next = screen.getByRole("button", { name: "Далі" });
      await waitFor(() => expect(next).toBeEnabled());
      fireEvent.click(next);
    }
    fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
    await waitFor(() => expect(mock[stage]).toHaveBeenCalledOnce());
    expect(mock.lock).toHaveBeenCalledWith(true);
    const signal = mock[stage].mock.calls[0]!.at(-1) as AbortSignal;
    unmount();
    await act(async () => {
      finish({ session: { id: "old-org-draft" } });
    });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(true);
    expect(mock.push).not.toHaveBeenCalled();
    expect(mock.lock).toHaveBeenLastCalledWith(false);
    if (stage === "create") expect(mock.binding).not.toHaveBeenCalled();
    if (stage !== "limits") expect(mock.limits).not.toHaveBeenCalled();
  },
);
