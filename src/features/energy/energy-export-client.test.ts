import { describe, expect, it, vi } from "vitest";
import {
  EnergyExportClient,
  parseEnergyExportJob,
  type EnergyExportJob,
  type EnergyExportOptions,
} from "./energy-export-client";

const options: EnergyExportOptions = {
  series: [
    {
      node_id: "edge-01",
      equipment_id: "LE01MP-200",
      channel_id: "200-voltage",
      metric: "electrical.voltage",
      unit: "V",
    },
  ],
  from: "2026-07-23T09:00:00Z",
  to: "2026-07-23T10:00:00Z",
  step_seconds: 0,
  statistics: ["avg"],
  format: "xlsx",
};
const job: EnergyExportJob = {
  job_id: "a".repeat(32),
  status: "queued",
  phase: "preview",
  created_at: "2026-10-13T10:00:00Z",
  expires_at: "2026-10-13T11:00:00Z",
  options,
  progress: { processed: 0, total: null, unit: "source_events" },
  preview: null,
  artifact: null,
  error: null,
};

describe("Energy export contract", () => {
  it("rejects incomplete ready artifacts, invalid units and unsupported response states", () => {
    expect(parseEnergyExportJob(job).status).toBe("queued");
    expect(() => parseEnergyExportJob({ ...job, status: "ready" })).toThrow(/Некоректна/);
    expect(() => parseEnergyExportJob({ ...job, status: "unknown" })).toThrow();
    expect(() =>
      parseEnergyExportJob({
        ...job,
        options: { ...options, series: [{ ...options.series[0], unit: "W" }] },
      }),
    ).toThrow();
    expect(() => parseEnergyExportJob({ ...job, progress: { ...job.progress, processed: -1 } })).toThrow();
  });
  it("posts only export options and uses the existing authenticated transport", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(job), { status: 202 }));
    const client = new EnergyExportClient(transport, "https://api.example.test");
    await client.preview(options);
    expect(transport).toHaveBeenCalledTimes(1);
    const [url, init] = transport.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/v1/energy/exports/preview");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual(options);
    expect(String(init?.body)).not.toMatch(/poll_interval|cadence|graph_points/);
  });
  it("restricts native-download tickets to the requested artifact and API origin", async () => {
    const transport = vi.fn<typeof fetch>();
    const client = new EnergyExportClient(transport, "https://api.example.test/proxy");
    transport.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          download_path: `/api/v1/energy/exports/${job.job_id}/download?ticket=${"x".repeat(43)}`,
        }),
      ),
    );
    expect(await client.downloadUrl(job.job_id)).toBe(
      `https://api.example.test/proxy/api/v1/energy/exports/${job.job_id}/download?ticket=${"x".repeat(43)}`,
    );
    for (const path of [
      "https://other.example.test/file",
      `/api/v1/energy/exports/${"b".repeat(32)}/download?ticket=${"x".repeat(43)}`,
      `/api/v1/energy/exports/${job.job_id}/download?ticket=x&redirect=https://other.test`,
    ]) {
      transport.mockResolvedValueOnce(new Response(JSON.stringify({ download_path: path })));
      await expect(client.downloadUrl(job.job_id)).rejects.toThrow(/Некоректна/);
    }
  });
});
