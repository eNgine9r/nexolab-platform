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
    let scheduledRevoke: (() => void) | null = null;
    const scheduleRevoke = vi.fn((callback: () => void, delayMs: number) => {
      expect(delayMs).toBe(1_000);
      scheduledRevoke = callback;
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      expect(this.isConnected).toBe(true);
      expect(this.href).toBe("blob:nexolab-csv");
      expect(this.download).toBe("saved-dashboard.csv");
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
    expect(scheduledRevoke).not.toBeNull();

    scheduledRevoke?.();

    expect(revokeObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:nexolab-csv");
  });
});
