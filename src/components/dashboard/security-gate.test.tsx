import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SecurityGate } from "./security-gate";

vi.mock("next/navigation", () => ({ usePathname: () => window.location.pathname }));

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

const diagnostics = {
  apiOrigin: "http://192.168.1.50:8082",
  browserOrigin: "http://192.168.1.20:3000",
  endpointPath: "/api/v1/auth/session" as const,
  timeoutMs: 8_000,
  httpStatus: null,
};

describe("SecurityGate", () => {
  it("carries the protected path, query and fragment into login and follows route changes", async () => {
    const initial = "/settings?tab=general#display";
    window.history.replaceState(null, "", initial);
    const view = render(
      <SecurityGate
        state="unauthenticated"
        error="Потрібен вхід."
        errorCode={null}
        diagnostics={null}
        onRetry={() => undefined}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Увійти" })).toHaveAttribute(
        "href",
        `/login?returnTo=${encodeURIComponent(initial)}`,
      ),
    );
    const next = "/reports?session=example#protocol";
    window.history.replaceState(null, "", next);
    view.rerender(
      <SecurityGate
        state="unauthenticated"
        error="Потрібен вхід."
        errorCode={null}
        diagnostics={null}
        onRetry={() => undefined}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Увійти" })).toHaveAttribute(
        "href",
        `/login?returnTo=${encodeURIComponent(next)}`,
      ),
    );
  });

  it("does not create a nested login return loop", async () => {
    window.history.replaceState(null, "", "/login?returnTo=https%3A%2F%2Fexample.com");
    render(
      <SecurityGate
        state="unauthenticated"
        error="Потрібен вхід."
        errorCode={null}
        diagnostics={null}
        onRetry={() => undefined}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Увійти" })).toHaveAttribute("href", "/login"),
    );
  });

  it("does not present a browser transport failure as an authorization denial", () => {
    render(
      <SecurityGate
        state="error"
        error="API NEXOLAB недоступний з цього браузера або поточний browser origin не дозволений CORS."
        errorCode="SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED"
        diagnostics={diagnostics}
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByRole("heading", { name: "Сервіс захищеної сесії недоступний" })).toBeVisible();
    expect(screen.queryByText("Доступ до dashboard відхилено")).not.toBeInTheDocument();
    expect(screen.getByText("SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED")).toBeVisible();
    expect(screen.getByText("http://192.168.1.20:3000")).toBeVisible();
    expect(screen.getByText("http://192.168.1.50:8082/api/v1/auth/session")).toBeVisible();
  });

  it("keeps a verified forbidden response as an authorization denial", () => {
    render(
      <SecurityGate
        state="forbidden"
        error="Поточний користувач не має доступу до вибраної організації."
        errorCode="ACCESS_DENIED"
        diagnostics={{ ...diagnostics, httpStatus: 403 }}
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByRole("heading", { name: "Доступ до dashboard відхилено" })).toBeVisible();
    expect(screen.getByText("403")).toBeVisible();
  });

  it("retries the session bootstrap on operator request", () => {
    const onRetry = vi.fn();
    render(
      <SecurityGate
        state="error"
        error="API NEXOLAB не відповідає."
        errorCode="SESSION_REQUEST_TIMEOUT"
        diagnostics={diagnostics}
        onRetry={onRetry}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Повторити перевірку" }));

    expect(onRetry).toHaveBeenCalledOnce();
  });
});
