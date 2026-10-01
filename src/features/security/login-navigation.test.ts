import { describe, expect, it } from "vitest";

import { localLoginHref, replaceAfterLogin, safeLocalReturnTo } from "./login-navigation";

describe("safe local login destination", () => {
  it.each([
    "/",
    "/settings?tab=general#display",
    "/reports?session=00000000-0000-0000-0000-000000000001",
    "/equipment-layouts?search=%D0%9A%D0%B0%D0%BC%D0%B5%D1%80%D0%B0%201",
    "/live?compare=edge%7Cequipment%7Cchannel&range=24h",
  ])("preserves local path, query and fragment: %s", (path) => {
    expect(safeLocalReturnTo(path)).toBe(path);
    const href = localLoginHref(path);
    expect(href).toBe(path === "/" ? "/login" : `/login?returnTo=${encodeURIComponent(path)}`);
  });

  it.each([
    undefined,
    null,
    [" /settings", "/reports"],
    "",
    "settings",
    "https://example.com/settings",
    "//example.com/settings",
    "/\\example.com",
    "/settings\n",
    "/settings\u0000",
    "/%2Fexample.com",
    "/%252Fexample.com",
    "/%5Cexample.com",
    "/%255Cexample.com",
    "/%0Asettings",
    "/%250Asettings",
    "/%ZZ",
    "/%2525252Fexample.com",
    "/login",
    "/login?returnTo=/reports",
    "/LOGIN/",
    "/login/anything",
    "/%6cogin",
    "/%256cogin",
    "/settings/../login",
    "/settings/%2e%2e/login",
    "/%2E%2E/login",
    "/settings".repeat(300),
  ])("falls back for unsafe, malformed, repeated or looping targets: %s", (value) => {
    expect(safeLocalReturnTo(value)).toBe("/");
    expect(localLoginHref(value)).toBe("/login");
  });

  it("normalizes local dot segments without changing the local origin", () => {
    const path = "/settings/../reports?session=example#detail";
    expect(safeLocalReturnTo(path)).toBe("/reports?session=example#detail");
  });
});

describe("authentication document boundary", () => {
  it.each([
    ["/reports?filter=completed#versions", "/reports?filter=completed#versions"],
    [
      "/reports/00000000-0000-0000-0000-000000000001#protocol",
      "/reports/00000000-0000-0000-0000-000000000001#protocol",
    ],
    ["https://example.com/settings", "/"],
    ["//example.com/settings", "/"],
    ["/login?returnTo=/reports", "/"],
  ])("replaces the document with a rechecked local target: %s", (returnTo, expected) => {
    const destinations: string[] = [];
    replaceAfterLogin(returnTo, { replace: (destination) => destinations.push(String(destination)) });
    expect(destinations).toEqual([expected]);
  });
});
