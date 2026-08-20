import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  filterOverviewTemperatureDiagnostics,
  useOverviewTemperatureVisibility,
} from "./use-overview-temperature-visibility";

const ORGANIZATION_ID = "33333333-3333-3333-3333-333333333333";
const STORAGE_KEY = `nexolab.overview.temperature-visible.${ORGANIZATION_ID}`;

describe("filterOverviewTemperatureDiagnostics", () => {
  it("omits initialization diagnostics for channels hidden from the Overview chart", () => {
    const diagnostics = [
      { channel_id: "104-03", poll_attempted: true },
      { channel_id: "108-01", poll_attempted: false },
    ];

    expect(filterOverviewTemperatureDiagnostics(diagnostics, ["104-03"])).toEqual([diagnostics[0]]);
  });
});

describe("useOverviewTemperatureVisibility", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows all monitored channels by default without changing monitoring state", async () => {
    const { result } = renderHook(() =>
      useOverviewTemperatureVisibility({
        enabled: true,
        organizationId: ORGANIZATION_ID,
        monitoredChannelIds: ["108-01", "104-03"],
      }),
    );

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.visibleChannelIds).toEqual(["104-03", "108-01"]);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("persists only display visibility and filters it to monitored channels", async () => {
    const { result } = renderHook(() =>
      useOverviewTemperatureVisibility({
        enabled: true,
        organizationId: ORGANIZATION_ID,
        monitoredChannelIds: ["104-03", "108-01"],
      }),
    );

    await waitFor(() => expect(result.current.loaded).toBe(true));
    act(() => result.current.setVisibleChannelIds(["108-01", "129-02"]));

    expect(result.current.visibleChannelIds).toEqual(["108-01"]);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
      schemaVersion: 1,
      channelIds: ["108-01"],
    });
  });

  it("preserves an explicit empty Overview selection", async () => {
    const { result } = renderHook(() =>
      useOverviewTemperatureVisibility({
        enabled: true,
        organizationId: ORGANIZATION_ID,
        monitoredChannelIds: ["104-03"],
      }),
    );

    await waitFor(() => expect(result.current.loaded).toBe(true));
    act(() => result.current.setVisibleChannelIds([]));
    expect(result.current.visibleChannelIds).toEqual([]);

    act(() => result.current.showAll());
    expect(result.current.visibleChannelIds).toEqual(["104-03"]);
  });
});
