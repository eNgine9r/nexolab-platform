import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("jsdom environment contract", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves application URLs against the configured test origin", () => {
    window.history.replaceState({ source: "test" }, "", "/live?dashboard=operator#temperature");

    const currentUrl = new URL(window.location.href);
    const apiUrl = new URL("/api/v1/telemetry/latest?channel_id=106-03", currentUrl);

    expect(currentUrl.pathname).toBe("/live");
    expect(currentUrl.searchParams.get("dashboard")).toBe("operator");
    expect(currentUrl.hash).toBe("#temperature");
    expect(apiUrl.origin).toBe(currentUrl.origin);
    expect(apiUrl.pathname).toBe("/api/v1/telemetry/latest");
    expect(apiUrl.searchParams.get("channel_id")).toBe("106-03");
  });

  it("keeps local and session storage isolated and string-based", () => {
    window.localStorage.setItem("nexolab.settings", JSON.stringify({ density: "compact" }));
    window.sessionStorage.setItem("nexolab.returnTo", "/overview");

    expect(JSON.parse(window.localStorage.getItem("nexolab.settings") ?? "{}")).toEqual({
      density: "compact",
    });
    expect(window.sessionStorage.getItem("nexolab.returnTo")).toBe("/overview");
    expect(window.localStorage.getItem("nexolab.returnTo")).toBeNull();
  });

  it("tracks focus without inventing visual layout", () => {
    const input = document.createElement("input");
    input.name = "operator-note";
    input.style.width = "320px";
    document.body.append(input);

    input.focus();

    expect(document.activeElement).toBe(input);
    expect(input.matches(":focus")).toBe(true);
    expect(input.getBoundingClientRect()).toMatchObject({
      width: 0,
      height: 0,
    });
  });

  it("submits forms with the successful controls and supports cancellation", () => {
    const form = document.createElement("form");
    const channel = document.createElement("input");
    const submit = document.createElement("button");

    channel.name = "channel_id";
    channel.value = "106-03";
    submit.type = "submit";
    submit.name = "action";
    submit.value = "save";
    form.append(channel, submit);
    document.body.append(form);

    const received: FormData[] = [];
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      received.push(new FormData(form, submit));
    });

    form.requestSubmit(submit);

    expect(received).toHaveLength(1);
    expect(received[0]?.get("channel_id")).toBe("106-03");
    expect(received[0]?.get("action")).toBe("save");
  });

  it("preserves bubbling, custom event detail, and cancellation", () => {
    const parent = document.createElement("section");
    const child = document.createElement("button");
    parent.append(child);
    document.body.append(parent);

    const detail: unknown[] = [];
    parent.addEventListener("nexolab:select", (event) => {
      detail.push((event as CustomEvent).detail);
      event.preventDefault();
    });

    const accepted = child.dispatchEvent(
      new CustomEvent("nexolab:select", {
        bubbles: true,
        cancelable: true,
        detail: { channelId: "106-03" },
      }),
    );

    expect(accepted).toBe(false);
    expect(detail).toEqual([{ channelId: "106-03" }]);
  });

  it("does not fetch external resources merely by attaching DOM elements", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const image = document.createElement("img");
    image.src = "https://example.invalid/nexolab-test.png";

    document.body.append(image);
    await Promise.resolve();

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
