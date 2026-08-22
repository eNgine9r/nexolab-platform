import { afterEach, describe, expect, it, vi } from "vitest";

import { triggerBrowserBlobDownload } from "./browser-download";

describe("triggerBrowserBlobDownload", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it("keeps the blob URL alive until after Chromium can commit the download", () => {
    const createObjectURL = vi.fn(() => "blob:nexolab-csv");
    const revokeObjectURL = vi.fn();
    const scheduledRevokes: Array<() => void> = [];
    const scheduleRevoke = vi.fn((callback: () => void, delayMs: number) => {
      expect(delayMs).toBe(1_000);
      scheduledRevokes.push(callback);
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
      const anchor = document.querySelector<HTMLAnchorElement>("a[download]");
      expect(anchor).not.toBeNull();
      expect(anchor?.isConnected).toBe(true);
      expect(anchor?.href).toBe("blob:nexolab-csv");
      expect(anchor?.download).toBe("saved-dashboard.csv");
    });
    const blob = new Blob(["timestamp_utc,value\n2026-08-22T08:00:00Z,4.2\n"], {
      type: "text/csv",
    });

    triggerBrowserBlobDownload(
      { blob, filename: "saved-dashboard.csv" },
      { document, createObjectURL, revokeObjectURL, scheduleRevoke },
    );

    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector("a[download]")).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    expect(scheduledRevokes).toHaveLength(1);

    scheduledRevokes[0]!();

    expect(revokeObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:nexolab-csv");
  });
});
