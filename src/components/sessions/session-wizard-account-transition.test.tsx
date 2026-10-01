import { SessionClientError } from "@/lib/sessions/runtime-config";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SessionWizard } from "./session-wizard";

const mock = vi.hoisted(() => ({
  push: vi.fn(),
  create: vi.fn(),
  binding: vi.fn(),
  limits: vi.fn(),
  begin: vi.fn(),
  release: vi.fn(),
  persistent: false,
  inventoryAvailable: true,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mock.push }) }));
vi.mock("@/components/dashboard/platform-account-boundary", () => ({
  usePlatformAccount: () => ({
    security: {
      membership: mock.persistent ? { organizationId: "org-a" } : null,
      session: mock.persistent ? { identity: { id: "operator-a" } } : null,
    },
    beginOperation: mock.begin,
  }),
}));
vi.mock("@/hooks/use-live-dashboard-inventory", () => ({
  useLiveDashboardInventory: () => ({ items: [], status: "ready", error: null, retry: vi.fn() }),
}));
vi.mock("@/features/test-sessions/telemetry-selection", () => ({
  buildSessionTelemetrySelectionModel: () => ({}),
  resolveSelectedSessionBindings: () =>
    mock.inventoryAvailable
      ? [
          {
            node_id: "edge-01",
            equipment_id: "K106",
            channel_id: "106-03",
            metric: "temperature.probe",
            unit: "degC",
          },
        ]
      : [],
}));
vi.mock("./wizard-steps", () => ({
  GeneralStep: ({
    form,
    update,
  }: {
    form: { sessionNumber: string };
    update: (key: "sessionNumber", value: string) => void;
  }) => (
    <input
      aria-label="Номер випробування"
      value={form.sessionNumber}
      onChange={(event) => update("sessionNumber", event.target.value)}
    />
  ),
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
  createSessionCredentialProvider: () => () => ({ accessToken: "verified", organizationId: "org-a" }),
  createSessionApiClient: () => ({
    listProductionBindingOptions: async () => [],
    createSession: mock.create,
    addBinding: mock.binding,
    addLimitSet: mock.limits,
  }),
}));
beforeEach(() => {
  localStorage.clear();
  mock.persistent = false;
  mock.inventoryAvailable = true;
  mock.push.mockClear();
  mock.begin.mockReset().mockReturnValue(mock.release);
  mock.release.mockReset();
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
    expect(mock.begin).toHaveBeenCalledOnce();
    const signal = mock[stage].mock.calls[0]!.at(-1) as AbortSignal;
    unmount();
    await act(async () => {
      finish({ session: { id: "old-org-draft" } });
    });
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(true);
    expect(mock.push).not.toHaveBeenCalled();
    expect(mock.release).toHaveBeenCalledOnce();
    if (stage === "create") expect(mock.binding).not.toHaveBeenCalled();
    if (stage !== "limits") expect(mock.limits).not.toHaveBeenCalled();
  },
);

it.each(["create", "binding", "limits"] as const)(
  "resumes %s after ordinary page navigation with the original operation keys",
  async (stage) => {
    mock.persistent = true;
    let finish!: (value: unknown) => void;
    mock[stage].mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const first = render(<SessionWizard />);
    for (let step = 0; step < 7; step++) {
      const next = screen.getByRole("button", { name: "Далі" });
      await waitFor(() => expect(next).toBeEnabled());
      fireEvent.click(next);
    }
    fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
    await waitFor(() => expect(mock[stage]).toHaveBeenCalledOnce());
    const firstKey = mock[stage].mock.calls[0]!.at(-2);
    const originalCreatePayload = mock.create.mock.calls[0]![0];
    first.unmount();
    await act(async () => finish({ session: { id: "old-org-draft" } }));
    mock.inventoryAvailable = false;
    const second = render(<SessionWizard />);
    expect(screen.getByText(/Відновлено незавершену форму/)).toBeVisible();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Створити реальний draft|Повторити без дублювання/ }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Створити реальний draft|Повторити без дублювання/ }));
    await waitFor(() => expect(mock.push).toHaveBeenCalledWith("/sessions/old-org-draft"));
    expect(mock[stage].mock.calls[1]!.at(-2)).toBe(firstKey);
    if (stage === "create") {
      expect(mock.create.mock.calls[1]![0].session_number).toBe(originalCreatePayload.session_number);
    } else expect(mock.create).toHaveBeenCalledOnce();
    expect(localStorage.getItem("nexolab.sessionWizardDraft.v1:operator-a:org-a")).toBeNull();
    second.unmount();
  },
);

it.each([409, 422])(
  "returns a definitively rejected creation (%s) to an editable form, including after reopening",
  async (status) => {
    mock.persistent = true;
    mock.create.mockRejectedValueOnce(
      new SessionClientError("duplicate", status, status === 409 ? "session_number_conflict" : "http"),
    );
    const first = render(<SessionWizard />);
    for (let step = 0; step < 7; step++) {
      const next = screen.getByRole("button", { name: "Далі" });
      await waitFor(() => expect(next).toBeEnabled());
      fireEvent.click(next);
    }
    fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
    await screen.findByText(/Такий номер випробування вже існує|Сервер відхилив створення/);
    const oldKey = mock.create.mock.calls[0]!.at(-2);
    expect(screen.getByLabelText("Номер випробування")).toBeEnabled();
    first.unmount();
    render(<SessionWizard />);
    fireEvent.change(screen.getByLabelText("Номер випробування"), { target: { value: "CORRECTED-UNIQUE" } });
    for (let step = 0; step < 7; step++) {
      const next = screen.getByRole("button", { name: "Далі" });
      await waitFor(() => expect(next).toBeEnabled());
      fireEvent.click(next);
    }
    fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
    await waitFor(() => expect(mock.push).toHaveBeenCalledWith("/sessions/old-org-draft"));
    expect(mock.create.mock.calls[1]![0].session_number).toBe("CORRECTED-UNIQUE");
    expect(mock.create.mock.calls[1]!.at(-2)).not.toBe(oldKey);
  },
);
it("keeps the original operation frozen after an uncertain creation failure", async () => {
  mock.persistent = true;
  mock.create
    .mockRejectedValueOnce(new SessionClientError("network", undefined, "network"))
    .mockRejectedValueOnce(new SessionClientError("validation-rejected", 422, "http"));
  render(<SessionWizard />);
  for (let step = 0; step < 7; step++) {
    const next = screen.getByRole("button", { name: "Далі" });
    await waitFor(() => expect(next).toBeEnabled());
    fireEvent.click(next);
  }
  fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
  await screen.findByText("network");
  expect(screen.getByRole("button", { name: "Назад" })).toBeDisabled();
  const oldKey = mock.create.mock.calls[0]!.at(-2);
  fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
  await screen.findByText("validation-rejected");
  expect(screen.getByRole("button", { name: "Назад" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Створити реальний draft" }));
  await waitFor(() => expect(mock.push).toHaveBeenCalledWith("/sessions/old-org-draft"));
  expect(mock.create.mock.calls[1]!.at(-2)).toBe(oldKey);
  expect(mock.create.mock.calls[2]!.at(-2)).toBe(oldKey);
});
