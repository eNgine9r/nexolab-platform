import { afterEach, describe, expect, it, vi } from "vitest";

import { installOpenSocketEvidence } from "./websocket-open-evidence";

class FakeWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readyState = FakeWebSocket.CONNECTING;
  closeArguments: [number | undefined, string | undefined] | null = null;

  constructor(
    readonly url: string,
    readonly protocols?: string | string[],
  ) {
    super();
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  close(code?: number, reason?: string): void {
    if (code === 1234) throw new DOMException("Invalid close code", "InvalidAccessError");
    this.closeArguments = [code, reason];
    this.readyState = FakeWebSocket.CLOSING;
  }

  completeClose(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }
}

function socket(): FakeWebSocket {
  return new window.WebSocket("ws://localhost/telemetry") as unknown as FakeWebSocket;
}

describe("browser OPEN transport evidence", () => {
  afterEach(() => vi.unstubAllGlobals());

  function install(): void {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    installOpenSocketEvidence();
  }

  it("excludes connecting and closing transports while retaining delayed close evidence", () => {
    install();
    const previous = socket();
    previous.open();
    const replacement = socket();
    expect(window.__nexolabOpenSocketEvidence).toMatchObject({ active: 1, maximum: 1 });
    previous.close(1000, "superseded telemetry connection");
    expect(window.__nexolabOpenSocketEvidence.active).toBe(0);
    replacement.open();
    expect(previous.readyState).toBe(FakeWebSocket.CLOSING);
    expect(window.__nexolabOpenSocketEvidence).toEqual({
      opened: 2,
      closed: 0,
      active: 1,
      maximum: 1,
    });
    previous.completeClose();
    expect(window.__nexolabOpenSocketEvidence).toEqual({
      opened: 2,
      closed: 1,
      active: 1,
      maximum: 1,
    });
  });

  it("detects two actual OPEN transports even after the overlap ends", () => {
    install();
    const first = socket();
    const second = socket();
    first.open();
    second.open();
    expect(window.__nexolabOpenSocketEvidence).toMatchObject({ active: 2, maximum: 2 });
    second.close();
    second.completeClose();
    expect(window.__nexolabOpenSocketEvidence).toMatchObject({ active: 1, maximum: 2 });
  });

  it("preserves native constructor, protocol and close behavior", () => {
    install();
    const protocols = ["telemetry-v1"];
    const transport = new window.WebSocket("ws://localhost/telemetry", protocols);
    const native = transport as unknown as FakeWebSocket;
    expect(transport).toBeInstanceOf(FakeWebSocket);
    expect(transport).toBeInstanceOf(window.WebSocket);
    expect(window.WebSocket.OPEN).toBe(FakeWebSocket.OPEN);
    expect(native.protocols).toBe(protocols);
    native.open();
    expect(() => transport.close(1234)).toThrow("Invalid close code");
    expect(window.__nexolabOpenSocketEvidence.active).toBe(1);
    transport.close(1000, "normal");
    expect(native.closeArguments).toEqual([1000, "normal"]);
    expect(window.__nexolabOpenSocketEvidence.active).toBe(0);
  });
});
