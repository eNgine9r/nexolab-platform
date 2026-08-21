import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  EquipmentDiscoveryOverview,
  EquipmentDiscoveryRepository,
  EquipmentDiscoveryScan,
} from "@/features/equipment/discovery-repository";

import { EquipmentDiscoveryInbox } from "./equipment-discovery-inbox";

function overview(): EquipmentDiscoveryOverview {
  return {
    policy: {
      enabled: true,
      allowedCidrs: ["192.168.50.0/30"],
      allowedPorts: [80, 443],
      maxHosts: 16,
      maxPorts: 3,
      connectTimeoutSeconds: 0.2,
      concurrency: 4,
      scheduleIntervalSeconds: 0,
      probeMode: "tcp-connect-only",
      payloadBytesSentPerProbe: 0,
    },
    activeScan: null,
    lastScan: null,
    candidateTotal: 0,
    candidateOffset: 0,
    candidateLimit: 50,
    candidates: [],
    networkAssetTotal: 0,
    networkAssets: [],
  };
}

function runningScan(): EquipmentDiscoveryScan {
  return {
    id: "scan-started",
    status: "running",
    requestedCidrs: ["192.168.50.0/30"],
    requestedPorts: [80, 443],
    hostBudget: 2,
    probeBudget: 4,
    hostsConsidered: 0,
    probesAttempted: 0,
    responsiveHosts: 0,
    durationMs: 0,
    processCpuMs: 0,
    networkConnectAttempts: 0,
    networkPayloadBytes: 0,
    trigger: "manual",
    newCandidates: 0,
    changedCandidates: 0,
    disappearedCandidates: 0,
    cancelRequested: false,
    requestedBy: "engineer",
    startedAt: "2026-08-21T09:00:00Z",
    completedAt: null,
    errorCode: null,
    errorMessage: null,
  };
}

describe("EquipmentDiscoveryInbox scan reconciliation", () => {
  it("retains a successfully launched scan when the immediate overview refresh fails", async () => {
    const initial = overview();
    const getOverview = vi.fn<EquipmentDiscoveryRepository["getOverview"]>();
    getOverview.mockResolvedValueOnce(initial).mockRejectedValueOnce(new Error("refresh failed"));
    const startScan = vi.fn<EquipmentDiscoveryRepository["startScan"]>(async () => runningScan());
    const repository: EquipmentDiscoveryRepository = {
      getOverview,
      startScan,
      cancelScan: vi.fn<EquipmentDiscoveryRepository["cancelScan"]>(),
      actOnCandidate: vi.fn<EquipmentDiscoveryRepository["actOnCandidate"]>(),
    };

    render(<EquipmentDiscoveryInbox repository={repository} canManage assets={[]} />);
    await screen.findByRole("button", { name: "Запустити scan" });

    fireEvent.click(screen.getByRole("button", { name: "Запустити scan" }));

    await waitFor(() => expect(startScan).toHaveBeenCalledTimes(1));
    await screen.findByText("Scan виконується");
    expect(screen.getByRole("button", { name: "Скасувати scan" })).toBeEnabled();
    expect(screen.getByText("refresh failed")).toBeInTheDocument();
  });
});
