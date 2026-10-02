import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { OverviewSensorGroups } from "./overview-sensor-groups";
import { overviewCatalogFixture } from "./overview-sensor-test-fixtures";
import { useOverviewSensorCatalog } from "./use-overview-sensor-catalog";

vi.mock("./use-overview-sensor-catalog", () => ({ useOverviewSensorCatalog: vi.fn() }));
afterEach(() => vi.clearAllMocks());

function Fixture() {
  const [selected, setSelected] = useState<string[]>(["106-03"]);
  return (
    <>
      <OverviewSensorGroups
        organizationId="org-1"
        nodeId="edge-01"
        channelIds={["106-03", "106-04"]}
        selected={selected}
        onToggleGroup={(ids) =>
          setSelected((current) =>
            ids.every((id) => current.includes(id))
              ? current.filter((id) => !ids.includes(id))
              : [...new Set([...current, ...ids])],
          )
        }
        renderSensor={(id, label) => (
          <span key={id}>
            {label} {id}
          </span>
        )}
      />
      <output aria-label="selected">{selected.join(",")}</output>
    </>
  );
}
describe("Overview hierarchy controls", () => {
  it("exposes mixed selection and selects the whole group even while searching", () => {
    vi.mocked(useOverviewSensorCatalog).mockReturnValue({
      equipment: [overviewCatalogFixture()],
      loading: false,
      error: null,
    });
    render(<Fixture />);
    const group = screen.getByRole("checkbox", { name: "Показувати всі датчики приладу: Контролер К106" });
    expect(group).toBePartiallyChecked();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Повітря" } });
    expect(screen.queryByText("Продукт 106-04")).not.toBeInTheDocument();
    fireEvent.click(group);
    expect(screen.getByLabelText("selected")).toHaveTextContent("106-03,106-04");
    expect(group).toBeChecked();
    fireEvent.click(group);
    expect(screen.getByLabelText("selected")).toBeEmptyDOMElement();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Камера №2" } });
    expect(screen.getByText("Продукт 106-04")).toBeVisible();
  });
  it("retains raw channels when metadata fails and explains the failure", () => {
    vi.mocked(useOverviewSensorCatalog).mockReturnValue({ equipment: [], loading: false, error: "offline" });
    render(<Fixture />);
    expect(screen.getByText(/Каталог камер недоступний: offline/)).toBeVisible();
    expect(screen.getByText("106-03 106-03")).toBeVisible();
    expect(screen.getByText("106-04 106-04")).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: /датчики приладу/ }));
    expect(screen.getByLabelText("selected")).toHaveTextContent("106-03,106-04");
  });
});
