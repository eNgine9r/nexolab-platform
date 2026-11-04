import { describe, expect, it, vi } from "vitest";
import { HttpCommissioningRepository } from "./commissioning-repository";

const input = {
  nodeId: "edge-01",
  busId: "commissioning-1234567890abcdef",
  stableTransportIdentifier: "/dev/serial/by-id/usb-test",
  unitId: 7,
};
const wire = {
  schema_version: 1,
  node_id: input.nodeId,
  bus_id: input.busId,
  stable_transport_identifier: input.stableTransportIdentifier,
  unit_id: 7,
  profile_id: "dixell-xjp60d",
  profile_version: "dixell-xjp60d-fc03-v1",
  state: "completed",
  attempted: 1,
  total: 1,
  candidates: [7],
  exception_addresses: [],
  error_code: null,
  modbus_writes: "none",
  hardware_writes: "none",
};

describe("address search transport", () => {
  it("sends the fixed profile and refuses mismatched or contradictory evidence", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(wire), { status: 200 }));
    const repository = new HttpCommissioningRepository({ apiBaseUrl: "http://127.0.0.1:8082", fetchImpl });
    expect((await repository.searchAddress(input, new AbortController().signal)).candidates).toEqual([7]);
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toMatchObject({
      unit_id: 7,
      read_only_confirmed: true,
      profile_id: "dixell-xjp60d",
    });
    for (const change of [
      { node_id: "other" },
      { candidates: [8] },
      { state: "failed" },
      { exception_addresses: [7] },
      { attempted: 0 },
    ]) {
      fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify({ ...wire, ...change }), { status: 200 }));
      await expect(repository.searchAddress(input, new AbortController().signal)).rejects.toThrow();
    }
  });

  it("propagates cancellation to the bounded fetch", async () => {
    let transportSignal: AbortSignal | undefined;
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(
      (_, init) =>
        new Promise((_, reject) => {
          transportSignal = init?.signal ?? undefined;
          transportSignal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const repository = new HttpCommissioningRepository({ apiBaseUrl: "http://127.0.0.1:8082", fetchImpl });
    const controller = new AbortController();
    const result = repository.searchAddress(input, controller.signal);
    controller.abort();
    await expect(result).rejects.toThrow();
    expect(transportSignal?.aborted).toBe(true);
  });
});
