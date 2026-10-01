import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useSessionWorkspace } from "./use-session-workspace";
const mock = vi.hoisted(() => ({ audit: vi.fn() }));
vi.mock("@/lib/sessions/api-client", async (original) => ({
  ...(await original<object>()),
  createSessionApiClient: () => ({
    getSession: vi.fn(async () => ({ id: "session-a", state: "completed", started_at: null })),
    getConfiguration: vi.fn(async () => ({})),
    listEvents: vi.fn(async () => ({ items: [] })),
    listStages: vi.fn(async () => []),
    listNotes: vi.fn(async () => ({ items: [] })),
    listAudit: mock.audit,
    latestTelemetry: vi.fn(async () => ({ items: [] })),
  }),
}));
beforeEach(() => {
  mock.audit.mockReset();
});
it("loads core session data without requesting forbidden audit diagnostics", async () => {
  mock.audit.mockRejectedValue(new Error("audit.read is required"));
  const { result } = renderHook(() => useSessionWorkspace("session-a", "org-a", undefined, false));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.data?.session.id).toBe("session-a");
  expect(result.current.data?.audit).toEqual([]);
  expect(result.current.error).toBeNull();
  expect(mock.audit).not.toHaveBeenCalled();
});
it("loads audit only when the verified account grants it and drops it after revocation", async () => {
  mock.audit.mockResolvedValue({ items: [{ id: "audit-a" }] });
  const { result, rerender } = renderHook(
    ({ allowed }) => useSessionWorkspace("session-a", "org-a", undefined, allowed),
    { initialProps: { allowed: true } },
  );
  await waitFor(() => expect(result.current.data?.audit).toEqual([{ id: "audit-a" }]));
  expect(mock.audit).toHaveBeenCalledOnce();
  rerender({ allowed: false });
  await waitFor(() => expect(result.current.data?.audit).toEqual([]));
  expect(mock.audit).toHaveBeenCalledOnce();
});
it("does not conceal genuine errors when audit access was granted", async () => {
  mock.audit.mockRejectedValue(new Error("audit request failed"));
  const { result } = renderHook(() => useSessionWorkspace("session-a", "org-a", undefined, true));
  await waitFor(() => expect(result.current.error?.message).toBe("audit request failed"));
  expect(result.current.data).toBeNull();
});
