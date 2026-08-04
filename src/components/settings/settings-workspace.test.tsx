import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SecurityMembership, SecuritySession } from "@/features/security/security-session";
import { createDefaultSettingsPreferences } from "@/features/settings/preferences";
import { buildSettingsRuntimeDiagnostics } from "@/features/settings/runtime-diagnostics";

import { SettingsWorkspace } from "./settings-workspace";

const membership: SecurityMembership = {
  organizationId: "33333333-3333-3333-3333-333333333333",
  organizationSlug: "dashboard-acceptance",
  organizationName: "NEXOLAB Dashboard Acceptance",
  roles: ["viewer"],
  permissions: ["dashboard.read", "telemetry.read", "alerts.read", "reports.read", "nodes.read"],
};

const session: SecuritySession = {
  authenticated: true,
  identity: {
    id: "identity-id",
    provider: "acceptance-oidc",
    subject: "opaque-subject-that-must-not-render",
    email: "viewer@example.test",
    displayName: "Viewer Acceptance",
  },
  memberships: [membership],
};

const diagnostics = buildSettingsRuntimeDiagnostics({
  profile: "LOCAL_LAN",
  dataMode: "live",
  authProvider: "acceptance",
  apiBaseUrl: "http://127.0.0.1:18102",
  websocketUrl: "ws://127.0.0.1:18102/api/v1/telemetry/live",
  browserOrigin: "http://127.0.0.1:13020",
});

describe("SettingsWorkspace", () => {
  it("renders verified operator context, sanitized diagnostics and canonical links", () => {
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
      />,
    );

    expect(screen.getByRole("heading", { name: "Налаштування" })).toBeVisible();
    expect(screen.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
    expect(screen.getByText("NEXOLAB Dashboard Acceptance", { exact: true })).toBeVisible();
    expect(screen.getByText("Спостерігач", { exact: true })).toBeVisible();
    expect(screen.getByText("Конфігурація готова", { exact: true })).toBeVisible();
    expect(screen.getByText("http://127.0.0.1:18102", { exact: true })).toBeVisible();
    expect(
      screen.getByText("ws://127.0.0.1:18102/api/v1/telemetry/live", { exact: true }),
    ).toBeVisible();
    expect(screen.queryByText("opaque-subject-that-must-not-render")).not.toBeInTheDocument();

    expect(screen.getByRole("link", { name: /Вузли/ })).toHaveAttribute("href", "/nodes");
    expect(screen.getByRole("link", { name: /Обладнання/ })).toHaveAttribute("href", "/equipment");
    expect(screen.getByRole("link", { name: /Холодильне обладнання/ })).toHaveAttribute(
      "href",
      "/refrigeration",
    );
    expect(screen.getByRole("link", { name: /Тривоги/ })).toHaveAttribute("href", "/alerts");
    expect(screen.getByRole("link", { name: /Звіти/ })).toHaveAttribute("href", "/reports");
  });

  it("emits validated local preference changes and reset actions", () => {
    const onPreferenceChange = vi.fn();
    const onPreferencesReset = vi.fn();
    render(
      <SettingsWorkspace
        session={session}
        membership={membership}
        diagnostics={diagnostics}
        preferences={createDefaultSettingsPreferences()}
        preferencesLoaded
        preferencesRecovered
        preferenceRecoveryReason="Recovered fixture"
        onPreferenceChange={onPreferenceChange}
        onPreferencesReset={onPreferencesReset}
      />,
    );

    expect(screen.getByText("Пошкоджені локальні налаштування відновлено")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Часові позначки"), { target: { value: "utc" } });
    fireEvent.change(screen.getByLabelText("Стандартне вікно телеметрії"), {
      target: { value: "24h" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Скинути локальні налаштування" }));

    expect(onPreferenceChange).toHaveBeenCalledWith("timeDisplay", "utc");
    expect(onPreferenceChange).toHaveBeenCalledWith("telemetryWindow", "24h");
    expect(onPreferencesReset).toHaveBeenCalledOnce();
  });
});
