import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TemperatureVisibilityDialog } from "./temperature-visibility-dialog";

describe("TemperatureVisibilityDialog", () => {
  it("changes Overview presentation without exposing an acquisition mutation callback", () => {
    const onApply = vi.fn();
    const onClose = vi.fn();

    render(
      <TemperatureVisibilityDialog
        open
        monitoredChannelIds={["106-01", "108-01"]}
        visibleChannelIds={["106-01", "108-01"]}
        targetDiagnostics={[]}
        monitoringError={null}
        onApply={onApply}
        onClose={onClose}
      />,
    );

    expect(screen.getByText(/Вибір змінює лише відображення в цьому браузері/)).toBeVisible();
    expect(screen.getByText(/жодних Device Agent mutations/)).toBeVisible();

    fireEvent.click(screen.getByLabelText("Показувати 106-01 на Огляді"));
    fireEvent.click(screen.getByRole("button", { name: "Застосувати відображення" }));

    expect(onApply).toHaveBeenCalledWith(["108-01"]);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("surfaces Device Agent configuration read failures instead of a truthful-empty state", () => {
    render(
      <TemperatureVisibilityDialog
        open
        monitoredChannelIds={[]}
        visibleChannelIds={[]}
        targetDiagnostics={[]}
        monitoringError="Device Agent unavailable"
        onApply={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Не вдалося підтвердити актуальний monitoring set: Device Agent unavailable",
    );
    expect(screen.getByText("Monitoring set недоступний через помилку Device Agent")).toBeVisible();
    expect(screen.queryByText("Немає каналів у безперервному моніторингу")).not.toBeInTheDocument();
  });

  it("allows hiding every monitored channel without disabling monitoring", () => {
    const onApply = vi.fn();
    render(
      <TemperatureVisibilityDialog
        open
        monitoredChannelIds={["104-03"]}
        visibleChannelIds={["104-03"]}
        targetDiagnostics={[]}
        monitoringError={null}
        onApply={onApply}
        onClose={() => undefined}
      />,
    );

    fireEvent.click(screen.getByLabelText("Показувати 104-03 на Огляді"));
    fireEvent.click(screen.getByRole("button", { name: "Застосувати відображення" }));

    expect(onApply).toHaveBeenCalledWith([]);
    expect(screen.getByText(/1 у безперервному моніторингу/)).toBeInTheDocument();
  });
});
