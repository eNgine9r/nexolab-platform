import { describe, expect, it } from "vitest";

import { catalogReturnHref, readSchemeNavigation, schemeEntryHref } from "./scheme-navigation";

describe("catalog scheme navigation", () => {
  it("preserves a local catalog filter context and encodes the exact equipment target", () => {
    const returnTo = "/equipment-layouts?q=Test+106&zone=A&layout=draft-only";
    const href = schemeEntryHref("equipment/106", returnTo, true);
    const url = new URL(href, "http://nexolab.invalid");
    expect(url.pathname).toBe("/refrigeration/equipment%2F106");
    expect(readSchemeNavigation(Object.fromEntries(url.searchParams))).toEqual({
      schemeEntry: true,
      editRequested: true,
      returnHref: returnTo,
    });
  });

  it.each(
    [
      "https://outside.example/equipment-layouts",
      "//outside.example/equipment-layouts",
      "/\\outside.example/equipment-layouts",
      "javascript:alert(1)",
      "/reports",
      "/equipment-layouts/other",
      "/equipment-layouts#other",
      "/equipment-layouts\n",
      ["/equipment-layouts"],
      undefined,
    ].map((value) => ({ value })),
  )("rejects unsupported or ambiguous return destinations: $value", ({ value }) => {
    expect(catalogReturnHref(value)).toBeNull();
  });

  it("does not treat an edit flag or repeated tab as a Scheme entry", () => {
    expect(readSchemeNavigation({ mode: "edit", tab: ["scheme", "graphs"] })).toEqual({
      schemeEntry: false,
      editRequested: false,
      returnHref: null,
    });
    expect(readSchemeNavigation({ mode: "edit" }).editRequested).toBe(false);
    expect(schemeEntryHref("equipment-1", "//outside.example", false)).toContain(
      "returnTo=%2Fequipment-layouts",
    );
  });
});
