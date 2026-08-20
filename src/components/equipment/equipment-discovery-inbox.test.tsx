import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  EquipmentDiscoveryOverview,
  EquipmentDiscoveryRepository,
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
    candidates: [
      {
        id: "candidate-1",
        candidateKey: "ip:192.168.50.2",
        ipAddress: "192.168.50.2",
        macAddress: null,
        hostname: null,
        sourceInterface: null,
        sourceSubnet: "192.168.50.0/30",
        lifecycle: "new",
        present: true,
        firstSeenAt: "2026-08-20T06:00:00Z",
        lastSeenAt: "2026-08-20T06:00:00Z",
        lastScanId: "scan-1",
        linkedEquipmentKey: null,
        version: 1,
        services: [{ port: 443, transport: "tcp", service: "https", evidence: "connect_succeeded" }],
        evidence: { tcp_connect_only: true, payload_bytes_sent: 0 },
        changedSincePreviousScan: false,
      },
    ],
    networkAssets: [],
  };
}

function repository() {
  const getOverview = vi.fn(async () => overview());
  const startScan = vi.fn<EquipmentDiscoveryRepository["startScan"]>(async (input) => ({
    id: "scan-2",
    status: "running",
    requestedCidrs: input?.cidrs ?? [],
    requestedPorts: input?.ports ?? [],
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
    startedAt: "2026-08-20T06:00:00Z",
    completedAt: null,
    errorCode: null,
    errorMessage: null,
  }));
  const cancelScan = vi.fn<EquipmentDiscoveryRepository["cancelScan"]>();
  const actOnCandidate = vi.fn<EquipmentDiscoveryRepository["actOnCandidate"]>();
  const value: EquipmentDiscoveryRepository = { getOverview, startScan, cancelScan, actOnCandidate };
  return { value, getOverview, startScan, cancelScan, actOnCandidate };
}

describe("EquipmentDiscoveryInbox", () => {
  it("loads evidence but never starts a scan automatically", async () => {
    const repo = repository();
    render(<EquipmentDiscoveryInbox repository={repo.value} canManage assets={[]} />);

    await screen.findByText("192.168.50.2");
    expect(repo.getOverview).toHaveBeenCalledTimes(1);
    expect(repo.startScan).not.toHaveBeenCalled();
    expect(screen.getByText(/не стає acquisition target автоматично/i)).toBeInTheDocument();
  });

  it("starts only an explicit bounded policy scope", async () => {
    const repo = repository();
    render(<EquipmentDiscoveryInbox repository={repo.value} canManage assets={[]} />);
    await screen.findByText("192.168.50.2");

    fireEvent.click(screen.getByRole("button", { name: "Запустити scan" }));

    await waitFor(() => expect(repo.startScan).toHaveBeenCalledTimes(1));
    expect(repo.startScan).toHaveBeenCalledWith({ cidrs: ["192.168.50.0/30"], ports: [80, 443] });
  });

  it("keeps viewer discovery evidence read-only", async () => {
    const repo = repository();
    render(<EquipmentDiscoveryInbox repository={repo.value} canManage={false} assets={[]} />);
    await screen.findByText("192.168.50.2");

    expect(screen.getByRole("button", { name: "Запустити scan" })).toBeDisabled();
    expect(screen.getByText("Доступ лише для перегляду discovery evidence.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adopt" })).not.toBeInTheDocument();
    expect(repo.actOnCandidate).not.toHaveBeenCalled();
  });
});
