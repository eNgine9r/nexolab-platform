import { describe, expect, it } from "vitest";

import { versionConfirmationPhrase } from "./version-confirmation";

describe("versionConfirmationPhrase", () => {
  it("uses the exact target bundle for update confirmation", () => {
    expect(versionConfirmationPhrase("update", "release-2")).toBe("APPLY release-2");
  });

  it("uses the exact target bundle for rollback confirmation", () => {
    expect(versionConfirmationPhrase("rollback", "release-1")).toBe("ROLLBACK release-1");
  });
});
