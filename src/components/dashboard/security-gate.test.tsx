import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SecurityGate } from "./security-gate";

const diagnostics = {
  apiOrigin: "http://192.168.1.50:8082",
  browserOrigin: "http://192.168.1.20:3000",
  endpointPath: "/api/v1/auth/session" as const,
  timeoutMs: 8_000,
  httpStatus: null,
};

describe("SecurityGate", () => {
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
