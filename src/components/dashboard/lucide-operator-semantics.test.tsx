import { render, screen } from "@testing-library/react";
import { Zap } from "lucide-react";
import { describe, expect, it } from "vitest";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";

import { platformNavItems } from "./sidebar";

describe("Lucide operator semantics", () => {
  it("keeps Zap mapped to the Energy operator route", () => {
    const energyItem = platformNavItems.find((item) => item.href === "/energy");

    expect(energyItem).toMatchObject({
      label: "Енергомоніторинг",
      href: "/energy",
      icon: Zap,
    });
  });

  it("keeps icon-only refrigeration controls named, focusable and token-sized", () => {
    render(
      <RefrigerationIconButton label="Редагувати енергомоніторинг">
        <Zap className="h-4 w-4" aria-hidden="true" />
      </RefrigerationIconButton>,
    );

    const button = screen.getByRole("button", { name: "Редагувати енергомоніторинг" });

    expect(button).toHaveAttribute("title", "Редагувати енергомоніторинг");
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("h-10", "w-10", "focus-visible:outline-2");
  });
});
