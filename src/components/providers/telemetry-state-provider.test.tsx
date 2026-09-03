import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { pathname, retain } = vi.hoisted(() => ({
  pathname: { value: "/" },
  retain: vi.fn(),
}));

vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));
vi.mock("@/lib/telemetry/route-persistent-client", () => ({
  retainTelemetryApplicationShell: retain,
}));

import { TelemetryStateProvider } from "./telemetry-state-provider";

describe("TelemetryStateProvider route isolation", () => {
  beforeEach(() => {
    pathname.value = "/";
    retain.mockReset();
  });

  it("retains and releases the ordinary dashboard telemetry shell", () => {
    const release = vi.fn();
    retain.mockReturnValue(release);
    const view = render(<TelemetryStateProvider>dashboard</TelemetryStateProvider>);

    expect(retain).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("keeps the ordinary telemetry shell retained across ordinary route changes", () => {
    const release = vi.fn();
    retain.mockReturnValue(release);
    const view = render(<TelemetryStateProvider>dashboard</TelemetryStateProvider>);

    pathname.value = "/settings";
    view.rerender(<TelemetryStateProvider>settings</TelemetryStateProvider>);

    expect(retain).toHaveBeenCalledTimes(1);
    expect(release).not.toHaveBeenCalled();
    view.unmount();
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("does not start the desktop telemetry shell inside the Telegram Mini App", () => {
    pathname.value = "/telegram-miniapp";
    render(<TelemetryStateProvider>miniapp</TelemetryStateProvider>);

    expect(retain).not.toHaveBeenCalled();
  });
});
