import { describe, expect, it, vi } from "vitest";

import { readLiveSelectionPreference, writeLiveSelectionPreference } from "./selection-preferences";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    values,
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value);
    }),
  };
}

describe("organization-scoped Live selection preference", () => {
  it("keeps only channel keys, preserves order and isolates organizations", () => {
    const storage = memoryStorage();
    expect(writeLiveSelectionPreference("org-a", ["channel-b", "channel-a"], storage)).toBe(true);
    expect(writeLiveSelectionPreference("org-b", ["channel-c"], storage)).toBe(true);
    expect(readLiveSelectionPreference("org-a", storage)).toEqual(["channel-b", "channel-a"]);
    expect(readLiveSelectionPreference("org-b", storage)).toEqual(["channel-c"]);
    expect(readLiveSelectionPreference("org-c", storage)).toEqual([]);
    expect(JSON.parse(storage.setItem.mock.calls[0]![1])).toEqual({
      version: 1,
      keys: ["channel-b", "channel-a"],
    });
  });

  it("retains an intentional empty selection", () => {
    const storage = memoryStorage();
    writeLiveSelectionPreference("org-a", ["channel-a"], storage);
    writeLiveSelectionPreference("org-a", [], storage);
    expect(readLiveSelectionPreference("org-a", storage)).toEqual([]);
    expect(JSON.parse(storage.setItem.mock.calls.at(-1)![1])).toEqual({ version: 1, keys: [] });
  });

  it("deduplicates writes and applies the existing eight-channel limit", () => {
    const storage = memoryStorage();
    const keys = Array.from({ length: 10 }, (_, index) => `channel-${index}`);
    writeLiveSelectionPreference("org-a", ["", keys[0]!, ...keys], storage);
    expect(readLiveSelectionPreference("org-a", storage)).toEqual(keys.slice(0, 8));
    writeLiveSelectionPreference("org-a", keys.slice(0, 8), storage);
    expect(storage.setItem).toHaveBeenCalledTimes(1);
  });

  it.each([
    "not-json",
    "null",
    JSON.stringify({ version: 2, keys: ["channel-a"] }),
    JSON.stringify({ version: 1, keys: "channel-a" }),
    JSON.stringify({ version: 1, keys: [null] }),
    JSON.stringify({ version: 1, keys: [""] }),
    JSON.stringify({ version: 1, keys: ["a", "a"] }),
    JSON.stringify({ version: 1, keys: Array.from({ length: 9 }, (_, index) => String(index)) }),
    JSON.stringify({ version: 1, keys: ["x".repeat(2049)] }),
    "x".repeat(20_001),
  ])("ignores malformed or excessive stored data", (raw) => {
    const storage = { getItem: () => raw, setItem: vi.fn() };
    expect(readLiveSelectionPreference("org-a", storage)).toEqual([]);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("keeps storage denial and unavailable storage non-fatal", () => {
    const storage = {
      getItem: () => {
        throw new Error("Storage denied");
      },
      setItem: vi.fn(),
    };
    expect(readLiveSelectionPreference("org-a", storage)).toEqual([]);
    expect(writeLiveSelectionPreference("org-a", ["a"], storage)).toBe(false);
    expect(writeLiveSelectionPreference("org-a", ["a"], null)).toBe(false);
    expect(readLiveSelectionPreference("org-a", null)).toEqual([]);
  });

  it("does not use a global preference when organization is missing", () => {
    const storage = memoryStorage();
    expect(writeLiveSelectionPreference(" ", ["a"], storage)).toBe(false);
    expect(readLiveSelectionPreference("", storage)).toEqual([]);
    expect(storage.setItem).not.toHaveBeenCalled();
  });
});
