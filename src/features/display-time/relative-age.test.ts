import { describe, expect, it } from "vitest";

import { formatRelativeAge } from "./relative-age";

describe("formatRelativeAge", () => {
  it("scales from seconds to days", () => {
    expect(formatRelativeAge(500)).toBe("щойно");
    expect(formatRelativeAge(12_000)).toBe("12 с тому");
    expect(formatRelativeAge(61_000)).toBe("1 хв тому");
    expect(formatRelativeAge(2 * 3_600_000)).toBe("2 год тому");
    expect(formatRelativeAge(3 * 3_600_000 + 5 * 60_000)).toBe("3 год 5 хв тому");
    // The live audit saw "23436 хв тому" for a meter silent since early November.
    expect(formatRelativeAge(23_436 * 60_000)).toBe("16 дн тому");
  });
});
