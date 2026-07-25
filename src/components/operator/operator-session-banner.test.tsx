import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OperatorSessionBanner } from "./operator-session-banner";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("OperatorSessionBanner", () => {
  it("stays hidden in demo mode", () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "demo");

    render(<OperatorSessionBanner />);

    expect(screen.queryByTestId("operator-session")).not.toBeInTheDocument();
  });

  it("shows the trusted tailscale operator in live mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://central.example.ts.net:8443");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            actor_id: "operator@example.com",
            display_name: "NEXOLAB Operator",
            provider: "tailscale",
            authenticated: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(<OperatorSessionBanner />);

    expect(await screen.findByTestId("operator-session")).toHaveTextContent("NEXOLAB Operator");
    expect(screen.getByTestId("operator-session")).toHaveTextContent("operator@example.com");
    expect(screen.getByTestId("operator-session")).toHaveTextContent("Tailscale identity");
  });

  it("surfaces a missing trusted proxy session", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_DATA_MODE", "live");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "https://central.example.ts.net:8443");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "operator_identity_required",
              message: "Tailscale Serve user identity is required for this operation",
            },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    render(<OperatorSessionBanner />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Tailscale Serve user identity is required");
  });
});
