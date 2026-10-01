import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  replace: vi.fn(),
  signIn: vi.fn(),
}));
vi.mock("@/features/security/login-navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/security/login-navigation")>()),
  replaceAfterLogin: state.replace,
}));
vi.mock("@/features/security/auth-runtime", () => ({ signInWithPassword: state.signIn }));
vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({ mode: "live", apiBaseUrl: "http://localhost:8082" }),
}));

import { LoginForm } from "./login-form";

beforeEach(() => {
  state.replace.mockReset();
  state.signIn.mockReset();
  state.signIn.mockResolvedValue({ ok: true });
  localStorage.clear();
  sessionStorage.clear();
});

function fillCredentials() {
  fireEvent.change(screen.getByLabelText("Логін або email"), { target: { value: "operator" } });
  fireEvent.change(screen.getByLabelText("Пароль", { exact: true }), {
    target: { value: "unit-test-password" },
  });
}

describe("operator login form", () => {
  it("temporarily reveals the same password through a non-submit accessible button", () => {
    render(<LoginForm returnTo="/settings" />);
    fillCredentials();
    const password = screen.getByLabelText("Пароль", { exact: true });
    const toggle = screen.getByRole("button", { name: "Показати пароль" });
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("unit-test-password");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Приховати пароль" }));
    expect(password).toHaveAttribute("type", "password");
    expect(state.signIn).not.toHaveBeenCalled();
    expect(Object.keys(localStorage)).toEqual([]);
    expect(Object.keys(sessionStorage)).toEqual([]);
  });

  it("returns to the protected local destination after successful authentication", async () => {
    const destination = "/reports?session=example#protocol";
    render(<LoginForm returnTo={destination} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: "Показати пароль" }));
    fireEvent.click(screen.getByRole("button", { name: "Увійти" }));
    await waitFor(() => expect(state.replace).toHaveBeenCalledWith(destination));
    expect(state.signIn).toHaveBeenCalledWith("http://localhost:8082", "operator", "unit-test-password");
    expect(screen.getByLabelText("Пароль", { exact: true })).toHaveAttribute("type", "password");
  });

  it.each([undefined, "https://example.com", "//example.com", "/login?returnTo=/reports"])(
    "uses Overview for an absent or unsafe destination: %s",
    async (returnTo) => {
      render(<LoginForm returnTo={returnTo} />);
      fillCredentials();
      fireEvent.click(screen.getByRole("button", { name: "Увійти" }));
      await waitFor(() => expect(state.replace).toHaveBeenCalledWith("/"));
    },
  );

  it("retains return intent after a rejected login and navigates only after successful retry", async () => {
    state.signIn.mockResolvedValueOnce({ ok: false, message: "Невірні облікові дані." });
    const destination = "/settings?tab=general#display";
    render(<LoginForm returnTo={destination} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: "Увійти" }));
    await expect(screen.findByRole("alert")).resolves.toHaveTextContent("Невірні облікові дані.");
    expect(state.replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Увійти" }));
    await waitFor(() => expect(state.replace).toHaveBeenCalledWith(destination));
  });
});
