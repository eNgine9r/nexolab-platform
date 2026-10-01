import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { Activity } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatOperationalTimestamp } from "@/features/display-time/format";
import { notifySettingsPreferencesChanged } from "@/features/display-time/store";
import {
  createDefaultSettingsPreferences,
  SETTINGS_PREFERENCES_STORAGE_KEY,
} from "@/features/settings/preferences";
import { useSettingsPreferences } from "./use-settings-preferences";
import { useDisplayTimeZone } from "./use-display-time-zone";

function Clock() {
  const timeZone = useDisplayTimeZone();
  return <output>{formatOperationalTimestamp("2026-07-01T10:20:30Z", timeZone)}</output>;
}

function save(timeDisplay: "utc" | "local") {
  localStorage.setItem(
    SETTINGS_PREFERENCES_STORAGE_KEY,
    JSON.stringify({ ...createDefaultSettingsPreferences(), timeDisplay }),
  );
}

describe("display timezone subscription", () => {
  beforeEach(() => {
    localStorage.clear();
    const actual = new Intl.DateTimeFormat().resolvedOptions();
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
      ...actual,
      timeZone: "Europe/Kyiv",
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("updates active consumers when Settings saves or resets in the same tab", async () => {
    const { result } = renderHook(useSettingsPreferences);
    render(<Clock />);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(screen.getByRole("status")).toHaveTextContent("13:20:30 (Europe/Kyiv)");
    act(() => result.current.updatePreference("timeDisplay", "utc"));
    expect(screen.getByRole("status")).toHaveTextContent("10:20:30 (UTC)");
    act(() => result.current.reset());
    expect(screen.getByRole("status")).toHaveTextContent("13:20:30 (Europe/Kyiv)");
  });

  it("does not claim a preference changed when browser persistence fails", async () => {
    const { result } = renderHook(useSettingsPreferences);
    render(<Clock />);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    act(() => result.current.updatePreference("timeDisplay", "utc"));
    expect(result.current.preferences.timeDisplay).toBe("local");
    expect(result.current.recovered).toBe(true);
    expect(result.current.recoveryReason).toMatch(/зберегти/);
    expect(screen.getByRole("status")).toHaveTextContent("Europe/Kyiv");
  });

  it("retains UTC when reset persistence fails", async () => {
    save("utc");
    const { result } = renderHook(useSettingsPreferences);
    render(<Clock />);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => result.current.reset());
    expect(result.current.preferences.timeDisplay).toBe("utc");
    expect(result.current.recoveryReason).toMatch(/зберегти скидання/);
    expect(screen.getByRole("status")).toHaveTextContent("10:20:30 (UTC)");
  });

  it("rejects an edit when stored preferences cannot be read even if writing would succeed", async () => {
    const { result } = renderHook(useSettingsPreferences);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    const write = vi.spyOn(Storage.prototype, "setItem");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => result.current.updatePreference("timeDisplay", "utc"));
    expect(write).not.toHaveBeenCalled();
    expect(result.current.preferences.timeDisplay).toBe("local");
    expect(result.current.recovered).toBe(true);
  });

  it("updates on cross-tab storage events and ignores unrelated keys", () => {
    render(<Clock />);
    save("utc");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "unrelated" })));
    expect(screen.getByRole("status")).toHaveTextContent("Europe/Kyiv");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: SETTINGS_PREFERENCES_STORAGE_KEY })));
    expect(screen.getByRole("status")).toHaveTextContent("UTC");
    localStorage.clear();
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: null })));
    expect(screen.getByRole("status")).toHaveTextContent("Europe/Kyiv");
  });

  it("reads current persisted settings when a retained page becomes visible", async () => {
    const { rerender } = render(
      <Activity mode="visible">
        <Clock />
      </Activity>,
    );
    await act(async () =>
      rerender(
        <Activity mode="hidden">
          <Clock />
        </Activity>,
      ),
    );
    save("utc");
    act(() => notifySettingsPreferencesChanged());
    await act(async () =>
      rerender(
        <Activity mode="visible">
          <Clock />
        </Activity>,
      ),
    );
    expect(screen.getByRole("status")).toHaveTextContent("10:20:30 (UTC)");
  });

  it("hydrates the deterministic UTC server snapshot then applies browser-local time", async () => {
    const container = document.createElement("div");
    container.innerHTML = renderToString(<Clock />);
    expect(container.textContent).toContain("10:20:30 (UTC)");
    const error = vi.spyOn(console, "error");
    render(<Clock />, { container, hydrate: true });
    await waitFor(() => expect(container.textContent).toContain("13:20:30 (Europe/Kyiv)"));
    expect(error).not.toHaveBeenCalled();
  });

  it("falls back to local time when preferences are malformed or storage is unavailable", () => {
    localStorage.setItem(SETTINGS_PREFERENCES_STORAGE_KEY, "broken");
    const { result } = renderHook(useDisplayTimeZone);
    expect(result.current).toBe("Europe/Kyiv");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    act(() => notifySettingsPreferencesChanged());
    expect(result.current).toBe("Europe/Kyiv");
  });
});
