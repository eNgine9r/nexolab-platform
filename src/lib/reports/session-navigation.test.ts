import { describe, expect, it, vi } from "vitest";
import { loadReportSessionContext, parseReportSessionTarget, reportSessionHref } from "./session-navigation";
import type { LaboratorySession } from "@/lib/sessions/types";

const id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const session = {
  id,
  organization_id: "org-a",
  state: "completed",
  session_number: "NXL-OLD",
  title: "Older test",
  updated_at: "2026-07-01T00:00:00Z",
} as LaboratorySession;
const signal = new AbortController().signal;
function client(value = session) {
  return {
    getSession: vi.fn().mockResolvedValue(value),
    listSessions: vi.fn().mockResolvedValue({ items: [] }),
  };
}

describe("exact report session navigation", () => {
  it("keeps ordinary entry separate from explicit context", () => {
    expect(parseReportSessionTarget(undefined)).toEqual({ kind: "none" });
    expect(parseReportSessionTarget(id.toUpperCase())).toEqual({ kind: "session", id });
    expect(reportSessionHref(id)).toBe(`/reports?session=${id}`);
  });
  it.each(["", "session-1", "https://evil.example", id + "?other=1", [id], [id, id]])(
    "rejects malformed or repeated context %j",
    (value) => {
      expect(parseReportSessionTarget(value)).toEqual({ kind: "invalid" });
    },
  );
  it.each(["completed", "archived"] as const)(
    "resolves the exact older %s test without depending on list pagination",
    async (state) => {
      const api = client({ ...session, state });
      const result = await loadReportSessionContext({ kind: "session", id }, "org-a", api, signal);
      expect(result).toMatchObject({ sessions: [{ id, state }], requested: { id }, error: null });
      expect(api.getSession).toHaveBeenCalledWith(id, signal);
      expect(api.listSessions).not.toHaveBeenCalled();
    },
  );
  it.each([{ organization_id: "org-b" }, { state: "running" }, { state: "cancelled" }, { id: "other-id" }])(
    "does not substitute another test for unavailable context %j",
    async (patch) => {
      const api = client({ ...session, ...patch } as LaboratorySession);
      expect(await loadReportSessionContext({ kind: "session", id }, "org-a", api, signal)).toMatchObject({
        sessions: [],
        requested: null,
        error: expect.any(String),
      });
      expect(api.listSessions).not.toHaveBeenCalled();
    },
  );
  it("handles missing context without silently opening a default", async () => {
    const api = client();
    api.getSession.mockRejectedValue(new Error("404"));
    expect(await loadReportSessionContext({ kind: "session", id }, "org-a", api, signal)).toMatchObject({
      sessions: [],
      requested: null,
      error: expect.any(String),
    });
  });
  it("does not request malformed or unscoped targets", async () => {
    const api = client();
    await loadReportSessionContext({ kind: "invalid" }, "org-a", api, signal);
    await loadReportSessionContext({ kind: "session", id }, null, api, signal);
    expect(api.getSession).not.toHaveBeenCalled();
    expect(api.listSessions).not.toHaveBeenCalled();
  });
  it("retains newest-first default options only when no context was requested", async () => {
    const api = client();
    const newer = { ...session, id: "newer", updated_at: "2026-08-01T00:00:00Z" };
    api.listSessions.mockResolvedValueOnce({ items: [session] }).mockResolvedValueOnce({ items: [newer] });
    expect(
      (await loadReportSessionContext({ kind: "none" }, "org-a", api, signal)).sessions.map((s) => s.id),
    ).toEqual(["newer", id]);
    expect(api.getSession).not.toHaveBeenCalled();
  });
  it("preserves aborts instead of presenting an old request as unavailable", async () => {
    const controller = new AbortController();
    controller.abort();
    const api = client();
    api.getSession.mockRejectedValue(new Error("aborted"));
    await expect(
      loadReportSessionContext({ kind: "session", id }, "org-a", api, controller.signal),
    ).rejects.toThrow("aborted");
  });
});
