import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TemperatureVisibilityDialog } from "./temperature-visibility-dialog";

const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
const showModal = vi.fn(function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
});
const close = vi.fn(function (this: HTMLDialogElement) {
  this.removeAttribute("open");
});
beforeEach(() => {
  showModal.mockClear();
  close.mockClear();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: showModal });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: close });
});
afterEach(() => {
  cleanup();
  for (const [key, descriptor] of [
    ["showModal", originalShowModal],
    ["close", originalClose],
  ] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, key, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, key);
  }
});

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

it("opens a native modal and cancels without applying the pending selection", () => {
  const onApply = vi.fn();
  const onClose = vi.fn();
  const { unmount } = render(
    <TemperatureVisibilityDialog
      open
      monitoredChannelIds={["106-01"]}
      visibleChannelIds={["106-01"]}
      targetDiagnostics={[]}
      monitoringError={null}
      onApply={onApply}
      onClose={onClose}
    />,
  );
  const dialog = screen.getByRole("dialog");
  expect(dialog.tagName).toBe("DIALOG");
  expect(showModal).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("checkbox"));
  const event = new Event("cancel", { cancelable: true });
  fireEvent(dialog, event);
  expect(event.defaultPrevented).toBe(true);
  expect(onClose).toHaveBeenCalledOnce();
  expect(onApply).not.toHaveBeenCalled();
  unmount();
  expect(close).toHaveBeenCalledOnce();
});

it("reopens with the current applied visibility after discarding an uncommitted draft", () => {
  const props = {
    monitoredChannelIds: ["106-01"],
    visibleChannelIds: ["106-01"],
    targetDiagnostics: [],
    monitoringError: null,
    onApply: vi.fn(),
    onClose: vi.fn(),
  };
  const { rerender } = render(<TemperatureVisibilityDialog {...props} open />);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  rerender(<TemperatureVisibilityDialog {...props} open={false} />);
  expect(close).toHaveBeenCalledOnce();
  rerender(<TemperatureVisibilityDialog {...props} open />);
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(showModal).toHaveBeenCalledTimes(2);
});

it.each([
  { monitoredChannelIds: [], monitoringError: null },
  { monitoredChannelIds: [], monitoringError: "Device Agent unavailable" },
  { monitoredChannelIds: ["106-01"], monitoringError: null },
])("wraps Tab at the dialog boundaries in populated, empty and error states: %j", (fixture) => {
  render(
    <TemperatureVisibilityDialog
      {...fixture}
      open
      visibleChannelIds={fixture.monitoredChannelIds}
      targetDiagnostics={[]}
      onApply={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const first = screen.getByRole("button", { name: "Закрити вибір датчиків Огляду" });
  const last = screen.getByRole("button", { name: "Застосувати відображення" });
  last.focus();
  fireEvent.keyDown(last, { key: "Tab" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
});
