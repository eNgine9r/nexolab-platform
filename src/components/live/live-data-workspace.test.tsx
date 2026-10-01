import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readLiveSelectionPreference, writeLiveSelectionPreference } from "@/features/live/selection-preferences";
import type { LiveTelemetryModel } from "@/hooks/use-live-telemetry";

const state = vi.hoisted(() => ({
  params: new URLSearchParams(),
  ready: false,
  reconciled: null as string[] | null,
  calls: [] as Array<{ organizationId: string; initialSelectedKeys: string[] }>,
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => state.params }));
vi.mock("@/hooks/use-live-telemetry", () => ({
  useLiveTelemetry: (options: { organizationId: string; initialSelectedKeys: string[] }) => {
    state.calls.push(options);
    const [keys, setKeys] = useState(options.initialSelectedKeys);
    return {
      selectedKeys: state.reconciled ?? keys,
      setSelectedKeys: setKeys,
      selectionReady: state.ready,
    };
  },
}));
vi.mock("./live-telemetry-explorer", () => ({
  LiveTelemetryExplorer: ({ telemetry }: { telemetry: LiveTelemetryModel }) => (
    <div>
      <output data-testid="selection">{telemetry.selectedKeys.join(",")}</output>
      <button onClick={() => telemetry.setSelectedKeys(["chosen-channel"])}>Choose</button>
      <button onClick={() => telemetry.setSelectedKeys([])}>Clear</button>
    </div>
  ),
}));

import { LiveDataWorkspace } from "./live-data-workspace";

beforeEach(() => {
  localStorage.clear();
  state.params = new URLSearchParams();
  state.ready = false;
  state.reconciled = null;
  state.calls = [];
});
afterEach(() => vi.restoreAllMocks());

describe("Live comparison memory at the workspace boundary", () => {
  it("restores a bare entry without writing before inventory readiness", () => {
    writeLiveSelectionPreference("org-a", ["remembered"]);
    const spy = vi.spyOn(Storage.prototype, "setItem");
    const view = render(<LiveDataWorkspace organizationId="org-a" />);
    expect(screen.getByTestId("selection")).toHaveTextContent("remembered");
    expect(state.calls.at(-1)?.initialSelectedKeys).toEqual(["remembered"]);
    expect(spy).not.toHaveBeenCalled();
    state.ready = true;
    view.rerender(<LiveDataWorkspace organizationId="org-a" />);
    expect(readLiveSelectionPreference("org-a")).toEqual(["remembered"]);
    expect(spy).not.toHaveBeenCalled();
  });

  it("gives explicit URL comparison priority over memory", () => {
    writeLiveSelectionPreference("org-a", ["remembered"]);
    state.params = new URLSearchParams("compare=url-channel&range=24h");
    state.ready = true;
    render(<LiveDataWorkspace organizationId="org-a" />);
    expect(screen.getByTestId("selection")).toHaveTextContent("url-channel");
    expect(readLiveSelectionPreference("org-a")).toEqual(["url-channel"]);
  });

  it("does not fall back to memory for an explicit empty comparison", () => {
    writeLiveSelectionPreference("org-a", ["remembered"]);
    state.params = new URLSearchParams("compare=");
    render(<LiveDataWorkspace organizationId="org-a" />);
    expect(state.calls.at(-1)?.initialSelectedKeys).toEqual([""]);
  });

  it("does not erase remembered keys on an incomplete or failed startup", () => {
    writeLiveSelectionPreference("org-a", ["remembered"]);
    state.reconciled = [];
    const view = render(<LiveDataWorkspace organizationId="org-a" />);
    expect(readLiveSelectionPreference("org-a")).toEqual(["remembered"]);
    state.ready = true;
    view.rerender(<LiveDataWorkspace organizationId="org-a" />);
    expect(readLiveSelectionPreference("org-a")).toEqual([]);
  });

  it("persists deliberate clear and restores it on reentry", () => {
    writeLiveSelectionPreference("org-a", ["remembered"]);
    state.ready = true;
    const view = render(<LiveDataWorkspace organizationId="org-a" />);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(readLiveSelectionPreference("org-a")).toEqual([]);
    view.unmount();
    render(<LiveDataWorkspace organizationId="org-a" />);
    expect(screen.getByTestId("selection")).toBeEmptyDOMElement();
  });

  it("resets the hook scope when organization changes", () => {
    writeLiveSelectionPreference("org-a", ["a"]);
    writeLiveSelectionPreference("org-b", ["b"]);
    state.ready = true;
    const view = render(<LiveDataWorkspace organizationId="org-a" />);
    view.rerender(<LiveDataWorkspace organizationId="org-b" />);
    expect(screen.getByTestId("selection")).toHaveTextContent("b");
    expect(state.calls.at(-1)?.organizationId).toBe("org-b");
    expect(readLiveSelectionPreference("org-a")).toEqual(["a"]);
    expect(readLiveSelectionPreference("org-b")).toEqual(["b"]);
  });

  it("keeps in-memory choice usable when persistence throws", () => {
    state.ready = true;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    render(<LiveDataWorkspace organizationId="org-a" />);
    fireEvent.click(screen.getByRole("button", { name: "Choose" }));
    expect(screen.getByTestId("selection")).toHaveTextContent("chosen-channel");
  });
});
