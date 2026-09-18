import { describe, expect, it, vi } from "vitest";

import {
  DERIVED_THERMODYNAMIC_METRICS,
  HttpRefrigerationThermodynamicsRepository,
  type RefrigerationCircuitSummary,
} from "./thermodynamics-repository";

const observationAt = new Date("2026-09-18T10:00:00.000Z");

function circuit(id: string, equipmentId = "showcase-1") {
  return {
    id,
    equipment_id: equipmentId,
    business_key: `circuit-${id}`,
    display_name: `Контур ${id}`,
    created_by: "operator",
    created_at: "2026-09-01T00:00:00Z",
  };
}

function derivedPayload(circuitId: string, unavailableMetric?: string) {
  return {
    circuit_id: circuitId,
    observation_at: observationAt.toISOString(),
    metrics: DERIVED_THERMODYNAMIC_METRICS.map((metric, index) => {
      const unavailable = metric === unavailableMetric;
      const unit = metric.includes("saturation") ? "degC" : "K";
      return {
        metric,
        availability: unavailable ? "unavailable" : "available",
        reason_codes: unavailable ? ["raw_sample_unavailable"] : [],
        observation_at: observationAt.toISOString(),
        computed_at: "2026-09-18T10:00:01.000Z",
        kernel_result: unavailable
          ? null
          : {
              metric,
              availability: "available",
              value: index + 1.25,
              unit,
              effective_at: "2026-09-18T09:59:58.000Z",
            },
      };
    }),
  };
}

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpRefrigerationThermodynamicsRepository", () => {
  it("filters circuits by equipment and reads all canonical metrics", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response({ items: [circuit("a"), circuit("b", "other")] }))
      .mockResolvedValueOnce(response(derivedPayload("a")));
    const repository = new HttpRefrigerationThermodynamicsRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    const circuits = await repository.listForEquipment("showcase-1");
    const snapshot = await repository.readDerived(circuits[0], observationAt);

    expect(circuits).toHaveLength(1);
    expect(circuits[0]).toMatchObject({ id: "a", equipmentId: "showcase-1" });
    expect(snapshot.metrics.map((item) => item.metric)).toEqual(DERIVED_THERMODYNAMIC_METRICS);
    expect(snapshot.metrics[0]).toMatchObject({
      availability: "available",
      value: 1.25,
      unit: "degC",
      effectiveAt: "2026-09-18T09:59:58.000Z",
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("preserves canonical unavailable reasons without inventing a numeric value", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(derivedPayload("a", "refrigeration.superheat")));
    const repository = new HttpRefrigerationThermodynamicsRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );
    const summary: RefrigerationCircuitSummary = {
      id: "a",
      equipmentId: "showcase-1",
      businessKey: "circuit-a",
      displayName: "Контур A",
    };

    const snapshot = await repository.readDerived(summary, observationAt);

    expect(snapshot.metrics[2]).toEqual(
      expect.objectContaining({
        metric: "refrigeration.superheat",
        availability: "unavailable",
        value: null,
        unit: "K",
        reasonCodes: ["raw_sample_unavailable"],
      }),
    );
  });

  it("fails closed when an available metric has no finite numeric value", async () => {
    const payload = derivedPayload("a");
    const firstKernel = payload.metrics[0].kernel_result as { value: number | null } | null;
    if (firstKernel) firstKernel.value = null;
    const fetchImpl = vi.fn().mockResolvedValue(response(payload));
    const repository = new HttpRefrigerationThermodynamicsRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );
    const summary: RefrigerationCircuitSummary = {
      id: "a",
      equipmentId: "showcase-1",
      businessKey: "circuit-a",
      displayName: "Контур A",
    };

    await expect(repository.readDerived(summary, observationAt)).rejects.toThrow(
      "Некоректний контракт термодинаміки",
    );
  });

  it("returns every circuit owned by the equipment in deterministic order", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      response({
        items: [
          { ...circuit("z"), business_key: "z-last" },
          { ...circuit("a"), business_key: "a-first" },
          circuit("foreign", "other"),
        ],
      }),
    );
    const repository = new HttpRefrigerationThermodynamicsRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    const circuits = await repository.listForEquipment("showcase-1");

    expect(circuits.map((item) => item.id)).toEqual(["a", "z"]);
  });

  it("surfaces API failures and does not silently fall back to demo data", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ detail: { message: "Доступ заборонено." } }, 403));
    const repository = new HttpRefrigerationThermodynamicsRepository(
      "http://127.0.0.1:8082",
      fetchImpl as unknown as typeof fetch,
    );

    await expect(repository.listForEquipment("showcase-1")).rejects.toThrow("Доступ заборонено.");
  });
});
