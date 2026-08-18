import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { VersionOperation } from "@/features/settings/version-management";

import { VersionOperationProgress } from "./version-operation-progress";

function operation(
  overrides: Partial<VersionOperation> = {},
): VersionOperation {
  return {
    id: "operation-1",
    actorSubject: "admin",
    action: "update",
    sourceRelease: "1.0.0",
    targetRelease: "2.0.0",
    targetBundleId: "release-2",
    targetCommit: "2".repeat(40),
    status: "running",
    startedAt: "2026-08-18T10:00:00Z",
    endedAt: null,
    backupEvidenceId: null,
    capacityEvidenceId: "operation-evidence/operation-1/capacity-preflight.txt",
    resultCode: null,
    phase: "creating_backup",
    phaseStatus: "running",
    completedPhases: ["verifying_package", "checking_capacity"],
    safeMessage: null,
    ...overrides,
  };
}

describe("VersionOperationProgress", () => {
  it("renders durable phases without invented percentage completion", () => {
    render(<VersionOperationProgress operation={operation()} />);

    expect(screen.getByText("Перевірка пакета")).toBeInTheDocument();
    expect(screen.getByText("Перевірка вільного місця")).toBeInTheDocument();
    expect(screen.getByText("Створення резервної копії")).toBeInTheDocument();
    expect(screen.getAllByText("завершено")).toHaveLength(2);
    expect(screen.getByText("виконується")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("keeps expected runtime restart explicit and tied to the same operation", () => {
    render(
      <VersionOperationProgress
        operation={operation({
          phase: "verifying_runtime",
          completedPhases: [
            "verifying_package",
            "checking_capacity",
            "creating_backup",
            "applying_update",
          ],
        })}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "NEXOLAB перезапускається — очікуємо локальний runtime",
    );
    expect(screen.getByRole("status")).toHaveTextContent("не запускає повторне оновлення");
    expect(screen.getByText("operation operation-1")).toBeInTheDocument();
  });

  it("shows a failed phase and bounded evidence without hiding the reason", () => {
    render(
      <VersionOperationProgress
        operation={operation({
          status: "failed",
          phase: "checking_capacity",
          phaseStatus: "failed",
          completedPhases: ["verifying_package"],
          safeMessage: "capacity blocked",
          resultCode: "VersionManagerFailure",
        })}
      />,
    );

    expect(screen.getByLabelText("Помилка")).toBeInTheDocument();
    expect(screen.getByText("capacity blocked")).toBeInTheDocument();
    expect(screen.getByText(/Capacity:/)).toBeInTheDocument();
    expect(screen.getByText(/Result: VersionManagerFailure/)).toBeInTheDocument();
  });
});
