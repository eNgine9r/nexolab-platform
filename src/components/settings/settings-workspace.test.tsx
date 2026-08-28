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

function renderWorkspace(overrides: Partial<React.ComponentProps<typeof SettingsWorkspace>> = {}) {
  return render(
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
      acquisitionCadenceContent={
        <div role="region" aria-label="Cadence fixture">
          Cadence fixture
        </div>
      }
      {...overrides}
    />,
  );
}

describe("SettingsWorkspace", () => {
  it("opens on General with task navigation and keeps diagnostics progressively disclosed", () => {
    renderWorkspace();

    expect(screen.getByRole("heading", { name: "Налаштування" })).toBeVisible();
    expect(screen.getByText("Viewer Acceptance", { exact: true })).toBeVisible();
    expect(screen.getByText("NEXOLAB Dashboard Acceptance", { exact: true })).toBeVisible();
    expect(screen.getByText("Спостерігач", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: /Загальні/ })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("http://127.0.0.1:18102", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("opaque-subject-that-must-not-render")).not.toBeInTheDocument();

    expect(screen.queryByRole("link", { name: /Вузли/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Обладнання/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Холодильне обладнання/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Тривоги/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Звіти/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Система/ }));
    expect(screen.getByRole("button", { name: /Система/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("LOCAL_LAN", { exact: true })).toBeVisible();
    fireEvent.click(screen.getByText("Runtime endpoints і деталі"));
    expect(screen.getByText("http://127.0.0.1:18102", { exact: true })).toBeVisible();
    expect(screen.getByText("ws://127.0.0.1:18102/api/v1/telemetry/live", { exact: true })).toBeVisible();
  });

  it("shows canonical administration destinations only with their permissions", () => {
    const { rerender } = renderWorkspace();
    expect(screen.queryByRole("link", { name: /Користувачі та доступ/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Версія та оновлення/ })).not.toBeInTheDocument();

    rerender(
      <SettingsWorkspace
        session={session}
        membership={{
          ...membership,
          roles: ["administrator"],
          permissions: [...membership.permissions, "memberships.manage", "project_versions.manage"],
        }}
        diagnostics={diagnostics}
        preferences={createDefaultSettingsPreferences()}
        preferencesLoaded
        preferencesRecovered={false}
        preferenceRecoveryReason={null}
        onPreferenceChange={() => undefined}
        onPreferencesReset={() => undefined}
      />,
    );

    expect(screen.getByRole("link", { name: /Користувачі та доступ/ })).toHaveAttribute(
      "href",
      "/settings/users",
    );
    expect(screen.getByRole("link", { name: /Версія та оновлення/ })).toHaveAttribute(
      "href",
      "/settings/system/version",
    );
  });

  it("preserves preference semantics across General and Appearance", () => {
    const onPreferenceChange = vi.fn();
    const onPreferencesReset = vi.fn();
    renderWorkspace({
      preferencesRecovered: true,
      preferenceRecoveryReason: "Recovered fixture",
      onPreferenceChange,
      onPreferencesReset,
    });

    expect(screen.getByText("Пошкоджені локальні налаштування відновлено")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Часові позначки"), { target: { value: "utc" } });
    fireEvent.change(screen.getByLabelText("Стандартне вікно телеметрії"), {
      target: { value: "24h" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Вигляд/ }));
    fireEvent.change(screen.getByLabelText("Щільність таблиць"), { target: { value: "compact" } });
    fireEvent.change(screen.getByLabelText("Анімація"), { target: { value: "reduced" } });

    fireEvent.click(screen.getByRole("button", { name: /Загальні/ }));
    fireEvent.click(screen.getByRole("button", { name: "Скинути локальні налаштування" }));

    expect(onPreferenceChange).toHaveBeenCalledWith("timeDisplay", "utc");
    expect(onPreferenceChange).toHaveBeenCalledWith("telemetryWindow", "24h");
    expect(onPreferenceChange).toHaveBeenCalledWith("tableDensity", "compact");
    expect(onPreferenceChange).toHaveBeenCalledWith("motion", "reduced");
    expect(onPreferencesReset).toHaveBeenCalledOnce();
  });

  it("keeps data collection in its dedicated section", () => {
    renderWorkspace();
    expect(screen.queryByRole("region", { name: "Cadence fixture" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Збір даних/ }));
    expect(screen.getByRole("region", { name: "Cadence fixture" })).toBeVisible();
  });
});
