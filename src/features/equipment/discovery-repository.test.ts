import { describe, expect, it, vi } from "vitest";

import { HttpEquipmentDiscoveryRepository } from "./discovery-repository";

function rawOverview() {
  return {
    policy: {
      enabled: true,
      allowed_cidrs: ["192.168.50.0/30"],
      allowed_ports: [80, 443],
      max_hosts: 16,
      max_ports: 3,
      connect_timeout_seconds: 0.2,
      concurrency: 4,
      schedule_interval_seconds: 0,
      probe_mode: "tcp-connect-only",
      payload_bytes_sent_per_probe: 0,
    },
    active_scan: null,
    last_scan: null,
    candidate_total: 1,
    candidate_offset: 0,
    candidate_limit: 50,
    candidates: [
      {
        id: "candidate-1",
        candidate_key: "ip:192.168.50.2",
        ip_address: "192.168.50.2",
        mac_address: null,
        hostname: null,
        source_interface: null,
        source_subnet: "192.168.50.0/30",
        lifecycle: "new",
        present: true,
        first_seen_at: "2026-08-20T06:00:00Z",
        last_seen_at: "2026-08-20T06:00:00Z",
        last_scan_id: "scan-1",
        linked_equipment_key: null,
        version: 1,
        services: [{ port: 443, transport: "tcp", service: "https", evidence: "connect_succeeded" }],
        evidence: { tcp_connect_only: true, payload_bytes_sent: 0 },
        changed_since_previous_scan: false,
      },
    ],
    network_assets: [],
  };
}

describe("HttpEquipmentDiscoveryRepository", () => {
  it("parses the explicit read-only discovery contract", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify(rawOverview()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const repository = new HttpEquipmentDiscoveryRepository({
      apiBaseUrl: "http://127.0.0.1:8082/",
      fetchImpl,
    });

    const overview = await repository.getOverview({ candidateOffset: 50, candidateLimit: 50 });

    expect(overview.policy.probeMode).toBe("tcp-connect-only");
    expect(overview.policy.payloadBytesSentPerProbe).toBe(0);
    expect(overview.policy.scheduleIntervalSeconds).toBe(0);
    expect(overview.candidates[0]?.services[0]?.port).toBe(443);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8082/api/v1/equipment-discovery?candidate_offset=50&candidate_limit=50",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  });

  it("rejects non-boolean candidate contract fields", async () => {
    for (const field of ["present", "changed_since_previous_scan"] as const) {
      const payload = rawOverview();
      Object.assign(payload.candidates[0]!, { [field]: "false" });
      const repository = new HttpEquipmentDiscoveryRepository({
        apiBaseUrl: "http://127.0.0.1:8082",
        fetchImpl: vi.fn<typeof fetch>(
          async () =>
            new Response(JSON.stringify(payload), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
        ),
      });

      await expect(repository.getOverview()).rejects.toMatchObject({ code: "invalid_response" });
    }
  });

  it("rejects non-boolean scan cancellation state", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(
          JSON.stringify({
            id: "scan-2",
            status: "running",
            requested_cidrs: ["192.168.50.0/30"],
            requested_ports: [443],
            host_budget: 2,
            probe_budget: 2,
            hosts_considered: 0,
            probes_attempted: 0,
            responsive_hosts: 0,
            duration_ms: 0,
            process_cpu_ms: 0,
            network_connect_attempts: 0,
            network_payload_bytes: 0,
            trigger: "manual",
            new_candidates: 0,
            changed_candidates: 0,
            disappeared_candidates: 0,
            cancel_requested: "false",
            requested_by: "engineer",
            started_at: "2026-08-20T06:00:00Z",
            completed_at: null,
            error_code: null,
            error_message: null,
          }),
          { status: 202 },
        ),
    );
    const repository = new HttpEquipmentDiscoveryRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      fetchImpl,
    });

    await expect(repository.startScan({ cidrs: ["192.168.50.0/30"], ports: [443] })).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("sends bounded scan scope and optimistic candidate actions", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (_input, init) => {
      const method = init?.method;
      if (method === "POST") {
        return new Response(
          JSON.stringify({
            id: "scan-2",
            status: "running",
            requested_cidrs: ["192.168.50.0/30"],
            requested_ports: [443],
            host_budget: 2,
            probe_budget: 2,
            hosts_considered: 0,
            probes_attempted: 0,
            responsive_hosts: 0,
            duration_ms: 0,
            process_cpu_ms: 0,
            network_connect_attempts: 0,
            network_payload_bytes: 0,
            trigger: "manual",
            new_candidates: 0,
            changed_candidates: 0,
            disappeared_candidates: 0,
            cancel_requested: false,
            requested_by: "engineer",
            started_at: "2026-08-20T06:00:00Z",
            completed_at: null,
            error_code: null,
            error_message: null,
          }),
          { status: 202 },
        );
      }
      const overview = rawOverview();
      return new Response(
        JSON.stringify({
          candidate: { ...overview.candidates[0], lifecycle: "reviewed", version: 2 },
          network_asset: null,
        }),
        { status: 200 },
      );
    });
    const repository = new HttpEquipmentDiscoveryRepository({
      apiBaseUrl: "http://127.0.0.1:8082",
      fetchImpl,
    });

    await repository.startScan({ cidrs: ["192.168.50.0/30"], ports: [443] });
    await repository.actOnCandidate("candidate-1", { action: "review" }, 1);

    const scanRequest = fetchImpl.mock.calls[0];
    expect(JSON.parse(String(scanRequest?.[1]?.body))).toEqual({ cidrs: ["192.168.50.0/30"], ports: [443] });
    const actionRequest = fetchImpl.mock.calls[1];
    expect(actionRequest?.[1]?.headers).toEqual(
      expect.objectContaining({ "If-Match": 'W/"equipment-discovery-candidate-v1"' }),
    );
    expect(JSON.parse(String(actionRequest?.[1]?.body))).toEqual({ action: "review" });
  });
});
