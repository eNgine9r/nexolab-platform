import { describe, expect, it, vi } from "vitest";

import { createReconnectBackfillObserver } from "./reconnect-backfill";

describe("createReconnectBackfillObserver", () => {
  it("requests a history backfill only after a recovered outage", () => {
    const onReconnected = vi.fn();
    const observe = createReconnectBackfillObserver(onReconnected);
    observe("connecting");
    observe("connected");
    expect(onReconnected).not.toHaveBeenCalled();
    observe("reconnecting");
    observe("connected");
    expect(onReconnected).toHaveBeenCalledTimes(1);
    observe("connected");
    expect(onReconnected).toHaveBeenCalledTimes(1);
    observe("offline");
    observe("connecting");
    observe("connected");
    expect(onReconnected).toHaveBeenCalledTimes(2);
  });
});
