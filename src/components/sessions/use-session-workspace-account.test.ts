import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useSessionWorkspace } from "./use-session-workspace";

const mock = vi.hoisted(() => ({ execute: vi.fn(), begin: vi.fn(), release: vi.fn() }));
vi.mock("@/lib/sessions/api-client", async (original) => ({
  ...(await original<object>()),
  createSessionApiClient: () => ({
    transition: mock.execute,
    advanceStage: mock.execute,
    addNote: mock.execute,
  }),
}));
beforeEach(() => {
  vi.useFakeTimers();
  mock.execute.mockReset();
  mock.begin.mockReset().mockReturnValue(mock.release);
  mock.release.mockReset();
});
afterEach(() => vi.useRealTimers());
it.each(["transition", "advanceStage", "addNote"] as const)(
  "owns its account lease until %s settles",
  async (action) => {
    let finish!: (value: unknown) => void;
    mock.execute.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = renderHook(() => useSessionWorkspace("session-a", "org-a", mock.begin));
    let pending!: Promise<void>;
    act(() => {
      pending =
        action === "transition"
          ? result.current.transition("start")
          : action === "advanceStage"
            ? result.current.advanceStage({ stageType: "main_test", name: "Етап", plannedDurationMinutes: 5 })
            : result.current.addNote("Операторська примітка");
    });
    expect(mock.begin).toHaveBeenCalledOnce();
    expect(mock.release).not.toHaveBeenCalled();
    await act(async () => {
      finish({});
      await pending;
    });
    expect(mock.release).toHaveBeenCalledOnce();
  },
);
it("releases the lease when a workspace mutation fails", async () => {
  mock.execute.mockRejectedValueOnce(new Error("rejected"));
  const { result } = renderHook(() => useSessionWorkspace("session-a", "org-a", mock.begin));
  await act(async () => {
    await expect(result.current.addNote("Примітка")).rejects.toThrow("rejected");
  });
  expect(mock.begin).toHaveBeenCalledOnce();
  expect(mock.release).toHaveBeenCalledOnce();
  expect(result.current.mutating).toBe(false);
});
