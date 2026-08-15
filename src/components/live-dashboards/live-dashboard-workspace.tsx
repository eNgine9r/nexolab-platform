"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, X } from "lucide-react";

import {
  createEmptyLiveDashboardDraft,
  dashboardToDraft,
  validateLiveDashboardDraft,
} from "@/features/live-dashboards/model";
import type {
  LiveDashboard,
  LiveDashboardDraft,
  LiveDashboardWorkspaceMode,
} from "@/features/live-dashboards/types";
import { useLiveDashboardInventory } from "@/hooks/use-live-dashboard-inventory";
import { type LiveDashboardConflict, useLiveDashboardLibrary } from "@/hooks/use-live-dashboard-library";
import { useLiveDashboardTelemetry } from "@/hooks/use-live-dashboard-telemetry";

import { DashboardEditor } from "./dashboard-editor";
import { DashboardLibrary } from "./dashboard-library";
import { DashboardLiveView } from "./dashboard-live-view";

function matchesDashboard(dashboard: LiveDashboard, search: string): boolean {
  const query = search.trim().toLocaleLowerCase("uk-UA");
  if (!query) return true;
  return [
    dashboard.name,
    dashboard.description ?? "",
    dashboard.owner_subject,
    ...dashboard.items.flatMap((item) => [item.channel_id, item.metric, item.native_unit]),
  ].some((value) => value.toLocaleLowerCase("uk-UA").includes(query));
}

export function LiveDashboardWorkspace({
  organizationId,
  canManage,
}: {
  organizationId: string;
  canManage: boolean;
}) {
  const [mode, setMode] = useState<LiveDashboardWorkspaceMode>("library");
  const [search, setSearch] = useState("");
  const [activeDashboard, setActiveDashboard] = useState<LiveDashboard | null>(null);
  const [draft, setDraft] = useState<LiveDashboardDraft>(createEmptyLiveDashboardDraft);
  const [conflict, setConflict] = useState<LiveDashboardConflict | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<Error | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<Error | null>(null);
  const library = useLiveDashboardLibrary({ enabled: true, organizationId });
  const inventory = useLiveDashboardInventory({
    enabled: mode === "editor",
    organizationId,
  });
  const telemetry = useLiveDashboardTelemetry({
    dashboard: mode === "live" ? activeDashboard : null,
    organizationId,
    enabled: mode === "live" && activeDashboard !== null,
  });
  const validation = useMemo(() => validateLiveDashboardDraft(draft), [draft]);
  const visibleDashboards = useMemo(
    () => library.dashboards.filter((dashboard) => matchesDashboard(dashboard, search)),
    [library.dashboards, search],
  );

  const returnToLibrary = () => {
    setMode("library");
    setActiveDashboard(null);
    setConflict(null);
    setSaveError(null);
    setOperationError(null);
  };

  const createDashboard = () => {
    if (!canManage) return;
    setDraft(createEmptyLiveDashboardDraft());
    setConflict(null);
    setSaveError(null);
    setMode("editor");
  };

  const editDashboard = async (dashboard: LiveDashboard) => {
    if (!canManage || dashboard.status !== "active") return;
    setOperationError(null);
    try {
      const latest = await library.get(dashboard.id);
      setDraft(dashboardToDraft(latest.value, latest.etag));
      setActiveDashboard(latest.value);
      setConflict(null);
      setSaveError(null);
      setMode("editor");
    } catch (error) {
      setOperationError(
        error instanceof Error ? error : new Error("Dashboard не вдалося відкрити для редагування."),
      );
    }
  };

  const openDashboard = async (dashboard: LiveDashboard) => {
    if (dashboard.status !== "active" || dashboard.items.length === 0) return;
    setOperationError(null);
    try {
      const latest = await library.get(dashboard.id);
      setActiveDashboard(latest.value);
      setConflict(null);
      setMode("live");
    } catch (error) {
      setOperationError(error instanceof Error ? error : new Error("Dashboard не вдалося відкрити."));
    }
  };

  const saveDashboard = async () => {
    if (!canManage || !validation.valid) return;
    setSaving(true);
    setSaveError(null);
    setConflict(null);
    try {
      const result = await library.save(draft);
      if (result.conflict) {
        setConflict(result.conflict);
        return;
      }
      if (result.saved) {
        setDraft(dashboardToDraft(result.saved.value, result.saved.etag));
        setActiveDashboard(result.saved.value);
        setNotice(`Dashboard «${result.saved.value.name}» збережено.`);
        setMode("live");
      }
    } catch (error) {
      setSaveError(error instanceof Error ? error : new Error("Dashboard не вдалося зберегти."));
    } finally {
      setSaving(false);
    }
  };

  const duplicateDashboard = async (dashboard: LiveDashboard) => {
    if (!canManage) return;
    setOperationError(null);
    try {
      const created = await library.duplicate(dashboard);
      setNotice(`Створено копію «${created.value.name}».`);
    } catch (error) {
      setOperationError(error instanceof Error ? error : new Error("Dashboard не вдалося дублювати."));
    }
  };

  const archiveDashboard = async (dashboard: LiveDashboard) => {
    if (!canManage || dashboard.status !== "active") return;
    const confirmed = window.confirm(`Архівувати «${dashboard.name}»? Телеметрія та історія не видаляються.`);
    if (!confirmed) return;
    setOperationError(null);
    try {
      await library.archive(dashboard);
      setNotice(`Dashboard «${dashboard.name}» архівовано.`);
    } catch (error) {
      setOperationError(error instanceof Error ? error : new Error("Dashboard не вдалося архівувати."));
    }
  };

  const useServerVersion = () => {
    if (!conflict?.server) return;
    setDraft(dashboardToDraft(conflict.server.value, conflict.server.etag));
    setActiveDashboard(conflict.server.value);
    setConflict(null);
    setSaveError(null);
  };

  const saveConflictAsCopy = async () => {
    if (!conflict || !canManage) return;
    const copyDraft: LiveDashboardDraft = {
      ...conflict.draft,
      id: null,
      name: `${conflict.draft.name} — моя копія`.slice(0, 128),
      version: null,
      etag: null,
    };
    setDraft(copyDraft);
    setConflict(null);
    setSaving(true);
    setSaveError(null);
    try {
      const result = await library.save(copyDraft);
      if (result.saved) {
        setDraft(dashboardToDraft(result.saved.value, result.saved.etag));
        setActiveDashboard(result.saved.value);
        setNotice(`Конфліктну версію збережено як «${result.saved.value.name}».`);
        setMode("live");
      }
    } catch (error) {
      setSaveError(error instanceof Error ? error : new Error("Копію не вдалося зберегти."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {notice ? (
        <div
          className="flex items-start justify-between gap-3 rounded-2xl border border-emerald-300/15 bg-emerald-400/[0.06] p-4 text-sm text-emerald-100"
          role="status"
        >
          <span className="inline-flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
            {notice}
          </span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Закрити повідомлення"
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg hover:bg-emerald-300/10"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {operationError ? (
        <div
          className="flex items-start justify-between gap-3 rounded-2xl border border-red-300/15 bg-red-400/[0.06] p-4 text-sm text-red-100"
          role="alert"
        >
          <span>{operationError.message}</span>
          <button
            type="button"
            onClick={() => setOperationError(null)}
            aria-label="Закрити помилку"
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg hover:bg-red-300/10"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {mode === "library" ? (
        <DashboardLibrary
          dashboards={visibleDashboards}
          status={library.status}
          error={library.error}
          search={search}
          onSearchChange={setSearch}
          includeArchived={library.includeArchived}
          onIncludeArchivedChange={library.setIncludeArchived}
          canManage={canManage}
          onCreate={createDashboard}
          onOpen={(dashboard) => void openDashboard(dashboard)}
          onEdit={(dashboard) => void editDashboard(dashboard)}
          onDuplicate={(dashboard) => void duplicateDashboard(dashboard)}
          onArchive={(dashboard) => void archiveDashboard(dashboard)}
          onRetry={library.refresh}
        />
      ) : null}

      {mode === "editor" ? (
        <DashboardEditor
          organizationId={organizationId}
          draft={draft}
          setDraft={setDraft}
          inventory={inventory}
          validation={validation}
          conflict={conflict}
          saving={saving}
          saveError={saveError}
          onSave={() => void saveDashboard()}
          onCancel={returnToLibrary}
          onUseServerVersion={useServerVersion}
          onSaveAsCopy={() => void saveConflictAsCopy()}
        />
      ) : null}

      {mode === "live" && activeDashboard ? (
        <DashboardLiveView
          dashboard={activeDashboard}
          telemetry={telemetry}
          canManage={canManage}
          onBack={returnToLibrary}
          onEdit={() => void editDashboard(activeDashboard)}
        />
      ) : null}
    </div>
  );
}
