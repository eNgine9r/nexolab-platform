import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { refrigerationTabStorageKey, useRefrigerationDetailTab } from "./use-refrigeration-detail-tab";

function Harness({ scope }: { scope: string | null }) {
  const { activeTab, setActiveTab } = useRefrigerationDetailTab(scope);
  return (
    <div>
      <output aria-label="Selected tab">{activeTab}</output>
      <button onClick={() => setActiveTab("graphs")}>Graphs</button>
      <button onClick={() => setActiveTab("controller")}>Controller</button>
    </div>
  );
}

describe("equipment-scoped refrigeration tab preferences", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("restores a valid tab without writing the initial Overview back to storage", () => {
    const scope = refrigerationTabStorageKey("organization-a", "equipment-a");
    window.localStorage.setItem(scope, "graphs");
    const write = vi.spyOn(Storage.prototype, "setItem");
    render(<Harness scope={scope} />);

    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("graphs");
    expect(window.localStorage.getItem(scope)).toBe("graphs");
    expect(write).not.toHaveBeenCalled();
  });

  it("keeps equipment and organization choices independent across return navigation", () => {
    const scopeA = refrigerationTabStorageKey("organization-a", "equipment-a");
    const scopeB = refrigerationTabStorageKey("organization-a", "equipment-b");
    const otherOrganization = refrigerationTabStorageKey("organization-b", "equipment-a");
    const { rerender } = render(<Harness scope={scopeA} />);
    fireEvent.click(screen.getByRole("button", { name: "Graphs" }));

    rerender(<Harness scope={scopeB} />);
    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("overview");
    fireEvent.click(screen.getByRole("button", { name: "Controller" }));

    rerender(<Harness scope={otherOrganization} />);
    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("overview");
    rerender(<Harness scope={scopeA} />);
    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("graphs");
    rerender(<Harness scope={scopeB} />);
    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("controller");
  });

  it("ignores legacy and invalid preferences without rewriting either", () => {
    const scope = refrigerationTabStorageKey("organization-a", "equipment-a");
    window.localStorage.setItem("nexolab:refrigeration-detail-tab", "graphs");
    window.localStorage.setItem(scope, "unknown-tab");
    const write = vi.spyOn(Storage.prototype, "setItem");
    render(<Harness scope={scope} />);

    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("overview");
    expect(window.localStorage.getItem(scope)).toBe("unknown-tab");
    expect(write).not.toHaveBeenCalled();
  });

  it("keeps tab navigation usable when browser reads and writes throw", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "QuotaExceededError");
    });
    render(<Harness scope={refrigerationTabStorageKey("organization-a", "equipment-a")} />);

    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("overview");
    fireEvent.click(screen.getByRole("button", { name: "Graphs" }));
    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("graphs");
    fireEvent.click(screen.getByRole("button", { name: "Controller" }));
    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("controller");
  });

  it("does not persist an unknown organization and avoids ambiguous scope identifiers", () => {
    const read = vi.spyOn(Storage.prototype, "getItem");
    const write = vi.spyOn(Storage.prototype, "setItem");
    render(<Harness scope={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Graphs" }));

    expect(screen.getByLabelText("Selected tab")).toHaveTextContent("graphs");
    expect(read).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
    expect(refrigerationTabStorageKey("a:b", "c")).not.toBe(refrigerationTabStorageKey("a", "b:c"));
  });
});
