import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => window.location.pathname }));

import { LoginReturnLink } from "./login-return-link";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("shared protected-page login link", () => {
  it("tracks fragment and browser-history changes without losing query context", async () => {
    window.history.replaceState(null, "", "/live?compare=channel#chart");
    render(<LoginReturnLink>Увійти</LoginReturnLink>);
    const link = screen.getByRole("link", { name: "Увійти" });
    await waitFor(() =>
      expect(link).toHaveAttribute(
        "href",
        `/login?returnTo=${encodeURIComponent("/live?compare=channel#chart")}`,
      ),
    );
    act(() => {
      window.history.replaceState(null, "", "/live?compare=channel#inventory");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await waitFor(() =>
      expect(link).toHaveAttribute(
        "href",
        `/login?returnTo=${encodeURIComponent("/live?compare=channel#inventory")}`,
      ),
    );
    act(() => {
      window.history.replaceState(null, "", "/nodes?filter=attention#inventory");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await waitFor(() =>
      expect(link).toHaveAttribute(
        "href",
        `/login?returnTo=${encodeURIComponent("/nodes?filter=attention#inventory")}`,
      ),
    );
  });

  it("does not update after the gate unmounts", async () => {
    window.history.replaceState(null, "", "/settings");
    const view = render(<LoginReturnLink>Увійти</LoginReturnLink>);
    view.unmount();
    await act(async () => {
      window.dispatchEvent(new PopStateEvent("popstate"));
      await Promise.resolve();
    });
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
