import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SecurityMembership, SecuritySession } from "@/features/security/security-session";
import { createDefaultSettingsPreferences } from "@/features/settings/preferences";
import { buildSettingsRuntimeDiagnostics } from "@/features/settings/runtime-diagnostics";

import { SettingsWorkspace } from "./settings-workspace";

const membership: SecurityMembership = {
  organizationId: "33333333-3333-3333-3333-333333333333",
  organizationSlug: "monitoring-acceptance",
  organizationName: "NEXOLAB Monitoring Acceptance",
  roles: ["engineer"],
  permissions: ["dashboard.read", "telemetry.read", "equipment.manage"],
};

const session: SecuritySession = {
  authenticated: true,
  identity: {
    id: "identity-id",
    provider: "local",
    subject: "engineer-subject",
    email: "engineer@example.test",
    displayName: "Monitoring Engineer",
  },
  memberships: [membership],
};

const diagnostics = buildSettingsRuntimeDiagnostics({
  profile: "LOCAL_LAN",
  dataMode: "live",
  authProvider: "local",
  apiBaseUrl: "http://127.0.0.1:18102",
  websocketUrl: "ws://127.0.0.1:18102/api/v1/telemetry/live",
  browserOrigin: "http://127.0.0.1:13020",
});

describe("Settings monitoring commissioning", () => {
  it("exposes explicit monitoring enrollment only to authorized operators", () => {
    const onOpenSensorMonitoring = vi.fn();
    render(
      <SettingsWorkspace
        session={session}
        membership={membership}
        diagnostics={diagnostics}
        preferences={createDefaultSettingsPreferences()}
        preferencesLoaded
        preferencesRecovered={false}
        preferenceRecoveryReason={null}
        onPreferenceChange={() => undefined}
        onPreferencesReset={() => undefined}
        canManageSensorMonitoring
        sensorMonitoringReady
        onOpenSensorMonitoring={onOpenSensorMonitoring}
      />,
    );

    const action = screen.getByRole("button", { name: /Моніторинг XJP60D/ });
    expect(action).toBeVisible();
    expect(screen.getByText(/явне persisted enrollment каналів у безперервний збір/)).toBeVisible();

    fireEvent.click(action);
    expect(onOpenSensorMonitoring).toHaveBeenCalledOnce();
  });

  it("keeps commissioning disabled until the authoritative monitoring configuration is loaded", () => {
    const onOpenSensorMonitoring = vi.fn();
    render(
      <SettingsWorkspace
        session={session}
        membership={membership}
        diagnostics={diagnostics}
        preferences={createDefaultSettingsPreferences()}
        preferencesLoaded
        preferencesRecovered={false}
        preferenceRecoveryReason={null}
        onPreferenceChange={() => undefined}
        onPreferencesReset={() => undefined}
        canManageSensorMonitoring
        sensorMonitoringReady={false}
        onOpenSensorMonitoring={onOpenSensorMonitoring}
      />,
    );

    const action = screen.getByRole("button", { name: /Моніторинг XJP60D/ });
    expect(action).toBeDisabled();
    fireEvent.click(action);
    expect(onOpenSensorMonitoring).not.toHaveBeenCalled();
  });
  it("surfaces monitoring configuration failures with an explicit retry action", () => {
    const retry = vi.fn();
    render(
      <SettingsWorkspace
        session={session}
        membership={membership}
        diagnostics={diagnostics}
        preferences={createDefaultSettingsPreferences()}
        preferencesLoaded
        preferencesRecovered={false}
        preferenceRecoveryReason={null}
        onPreferenceChange={() => undefined}
        onPreferencesReset={() => undefined}
        canManageSensorMonitoring
        sensorMonitoringReady={false}
        sensorMonitoringError="Device Agent unavailable"
        onRetrySensorMonitoring={retry}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Device Agent unavailable");
    const retryButton = screen.getByRole("button", { name: "Повторити завантаження" });
    expect(retryButton).toBeEnabled();
    fireEvent.click(retryButton);
    expect(retry).toHaveBeenCalledOnce();
  });
});
