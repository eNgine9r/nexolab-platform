import { describe, expect, it, vi } from "vitest";

import {
  SESSION_HISTORY_PAGE_LIMIT,
  SESSION_HISTORY_TAIL_OVERLAP_MS,
  loadSessionHistory,
  type SessionHistoryItem,
} from "./session-history-loader";

const T0 = Date.parse("2026-11-22T00:00:00Z");

function item(index: number): SessionHistoryItem {
  return { event_id: `e-${index}`, captured_at: new Date(T0 + index * 10_000).toISOString() };
}

describe("session history loader (#1649)", () => {
  it("paginates until the server reports no next page (no silent 1000-row truncation)", async () => {
    const all = Array.from({ length: 2_500 }, (_, index) => item(index));
    const fetchPage = vi.fn(async ({ offset, limit }: { offset: number; limit: number }) => ({
      items: all.slice(offset, offset + limit),
      next_offset: offset + limit < all.length ? offset + limit : null,
    }));
    const result = await loadSessionHistory({
      fetchPage,
      windowFrom: new Date(T0 - 1),
      windowTo: new Date(T0 + 1e9),
    });
    expect(fetchPage).toHaveBeenCalledTimes(3);
    expect(fetchPage.mock.calls[0][0].limit).toBe(SESSION_HISTORY_PAGE_LIMIT);
    expect(result.items).toHaveLength(2_500);
    expect(result.truncated).toBe(false);
    expect(result.items[0].event_id).toBe("e-0");
  });

  it("reports truncation instead of pretending completeness when the page cap is hit", async () => {
    const fetchPage = vi.fn(async ({ offset }: { offset: number }) => ({
      items: [item(offset)],
      next_offset: offset + 1,
    }));
    const result = await loadSessionHistory({
      fetchPage,
      windowFrom: new Date(T0 - 1),
      windowTo: new Date(T0 + 1e9),
      maxPages: 3,
    });
    expect(result.truncated).toBe(true);
    expect(result.items).toHaveLength(3);
  });

  it("fetches only the tail after the newest cached sample and merges by event id", async () => {
    const existing = [item(0), item(1), item(2)];
    const fetchPage = vi.fn(async (query: { from: Date; to: Date; offset: number; limit: number }) => ({
      items: query.offset === 0 ? [item(2), item(3)] : [],
      next_offset: null,
    }));
    const result = await loadSessionHistory({
      fetchPage,
      windowFrom: new Date(T0 - 1),
      windowTo: new Date(T0 + 1e9),
      existing,
    });
    const query = fetchPage.mock.calls[0][0] as unknown as { from: Date };
    expect(query.from.getTime()).toBe(Math.max(T0 - 1, T0 + 20_000 - SESSION_HISTORY_TAIL_OVERLAP_MS));
    expect(result.items.map((entry) => entry.event_id)).toEqual(["e-0", "e-1", "e-2", "e-3"]);
  });

  it("drops cached samples that left the rolling window", async () => {
    const fetchPage = vi.fn(async () => ({ items: [], next_offset: null }));
    const result = await loadSessionHistory({
      fetchPage,
      windowFrom: new Date(T0 + 15_000),
      windowTo: new Date(T0 + 1e9),
      existing: [item(0), item(1), item(2)],
    });
    expect(result.items.map((entry) => entry.event_id)).toEqual(["e-2"]);
  });

  it("rejects a pagination cursor that does not advance", async () => {
    const fetchPage = vi.fn(async () => ({ items: [item(0)], next_offset: 0 }));
    await expect(
      loadSessionHistory({
        fetchPage,
        windowFrom: new Date(T0 - 1),
        windowTo: new Date(T0 + 1e9),
      }),
    ).rejects.toThrow(/did not advance/);
  });
});
