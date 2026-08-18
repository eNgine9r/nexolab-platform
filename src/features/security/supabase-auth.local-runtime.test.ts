import { afterEach, describe, expect, it, vi } from "vitest";

const API_BASE_URL = "http://127.0.0.1:8082";
const ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("legacy runtime credential provider", () => {
  it("delegates local authentication to the rotating local provider", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", API_BASE_URL);
    const localProvider = vi.fn(async () => ({
      accessToken: "rotated-local-access",
      organizationId: ORGANIZATION_ID,
    }));
    const createLocalCredentialProvider = vi.fn(() => localProvider);
    vi.doMock("./local-auth", () => ({ createLocalCredentialProvider }));
    vi.doMock("@supabase/supabase-js", () => ({ createClient: vi.fn() }));

    const { createRuntimeCredentialProvider } = await import("./supabase-auth");
    const provider = createRuntimeCredentialProvider(ORGANIZATION_ID);

    await expect(provider()).resolves.toEqual({
      accessToken: "rotated-local-access",
      organizationId: ORGANIZATION_ID,
    });
    expect(createLocalCredentialProvider).toHaveBeenCalledWith(API_BASE_URL, ORGANIZATION_ID);
  });

  it("fails closed when local authentication has no API base URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER", "local");
    vi.stubEnv("NEXT_PUBLIC_NEXOLAB_API_BASE_URL", "");
    const createLocalCredentialProvider = vi.fn();
    vi.doMock("./local-auth", () => ({ createLocalCredentialProvider }));
    vi.doMock("@supabase/supabase-js", () => ({ createClient: vi.fn() }));

    const { setSecurityCredentials } = await import("./security-session");
    setSecurityCredentials({ accessToken: "stale-access", organizationId: ORGANIZATION_ID });
    const { createRuntimeCredentialProvider } = await import("./supabase-auth");

    await expect(createRuntimeCredentialProvider(ORGANIZATION_ID)()).resolves.toEqual({
      accessToken: null,
      organizationId: ORGANIZATION_ID,
    });
    expect(createLocalCredentialProvider).not.toHaveBeenCalled();
  });
});
