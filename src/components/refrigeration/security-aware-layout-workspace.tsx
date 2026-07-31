"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, History, LoaderCircle, ShieldCheck, X } from "lucide-react";
import { clsx } from "clsx";

import { CameraScopedLayoutEditor } from "@/components/refrigeration/camera-scoped-layout-editor";
import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import { RefrigerationLayoutLifecyclePanel } from "@/components/refrigeration/refrigeration-layout-lifecycle-panel";
import { RefrigerationLayoutWorkspace } from "@/components/refrigeration/refrigeration-layout-workspace";
import type { RefrigerationEquipment, RefrigerationSensor } from "@/data/refrigeration";
import type {
  AvailableSensor,
  EquipmentLifecycleRepository,
  SensorBinding,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import { createRefrigerationLayoutRuntime } from "@/features/refrigeration/layout-repository-runtime";
import {
  getSecurityCredentials,
  hasPermission,
  setSecurityCredentials,
  type SecurityMembership,
  type SecuritySession,
} from "@/features/security/security-session";

export type LayoutCapabilities = {
  canEdit: boolean;
  canPublish: boolean;
  canRestore: boolean;
};

type SecurityAwareLayoutWorkspaceProps = {
  equipment: RefrigerationEquipment;
  visibleSensors: RefrigerationSensor[];
  selectedId: string | null;
  mode: LayoutEditorMode;
  forceReadOnly?: boolean;
  lifecycleRepository?: EquipmentLifecycleRepository | null;
  sensorConfigurationRepository?: EquipmentLifecycleRepository | null;
  channels?: readonly AvailableSensor[];
  availableSensors?: readonly AvailableSensor[];
  bindings?: readonly SensorBinding[];
  canManageEquipment?: boolean;
  toolbarTools?: ReactNode;
  onModeChange: (mode: LayoutEditorMode) => void;
  onSelect: (sensorId: string) => void;
  onEquipmentChange?: (equipment: RefrigerationEquipment) => void;
  onConfigurationSaved?: () => void;
  onCapabilitiesChange?: (capabilities: LayoutCapabilities) => void;
};

const readOnlyCapabilities: LayoutCapabilities = {
  canEdit: false,
  canPublish: false,
  canRestore: false,
};
const demoCapabilities: LayoutCapabilities = {
  canEdit: true,
  canPublish: true,
  canRestore: true,
};

export function SecurityAwareRefrigerationLayoutWorkspace({
  equipment,
  visibleSensors,
  selectedId,
  mode,
  forceReadOnly = false,
  lifecycleRepository = null,
  sensorConfigurationRepository = null,
  channels = [],
  availableSensors,
  bindings = [],
  canManageEquipment,
  toolbarTools,
  onModeChange,
  onSelect,
  onEquipmentChange,
  onConfigurationSaved,
  onCapabilitiesChange,
}: SecurityAwareLayoutWorkspaceProps) {
  const runtime = useMemo(() => createRefrigerationLayoutRuntime({ equipment }), [equipment]);
  const layoutRepository = runtime.repository;
  const [session, setSession] = useState<SecuritySession | null>(null);
  const [membership, setMembership] = useState<SecurityMembership | null>(null);
  const [securityState, setSecurityState] = useState<"loading" | "ready" | "error">(
    runtime.mode === "demo" ? "ready" : "loading",
  );
  const [securityError, setSecurityError] = useState<string | null>(runtime.error);
  const [workspaceEpoch, setWorkspaceEpoch] = useState(0);
  const [lifecycleOpen, setLifecycleOpen] = useState(false);

  const effectiveLifecycleRepository =
    sensorConfigurationRepository ?? lifecycleRepository;
  const effectiveChannels = availableSensors ?? channels;
  const externallyReadOnly = forceReadOnly || canManageEquipment === false;

  const capabilities = useMemo<LayoutCapabilities>(() => {
    if (externallyReadOnly) return readOnlyCapabilities;
    if (runtime.mode === "demo") return demoCapabilities;
    if (!session || !membership) return readOnlyCapabilities;
    return {
      canEdit: hasPermission(session, membership.organizationId, "layout.draft.edit"),
      canPublish: hasPermission(session, membership.organizationId, "layout.publish"),
      canRestore: hasPermission(session, membership.organizationId, "layout.restore"),
    };
  }, [externallyReadOnly, membership, runtime.mode, session]);

  useEffect(() => {
    onCapabilitiesChange?.(capabilities);
    if (!capabilities.canEdit && mode === "edit") onModeChange("view");
  }, [capabilities, mode, onCapabilitiesChange, onModeChange]);

  useEffect(() => {
    if (!lifecycleOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setLifecycleOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [lifecycleOpen]);

  useEffect(() => {
    if (runtime.mode === "demo") return;
    const client = runtime.sessionClient;
    if (!client) return;
    let cancelled = false;
    void client.getSession().then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setSecurityState("error");
        setSecurityError(result.error.message);
        return;
      }
      const selectedMembership =
        result.value.memberships.find(
          (item) => item.organizationId === runtime.organizationId,
        ) ?? result.value.memberships[0];
      if (!selectedMembership) {
        setSecurityState("error");
        setSecurityError("Користувач не має активного членства в організації NEXOLAB.");
        return;
      }
      const currentCredentials = getSecurityCredentials();
      setSecurityCredentials({
        accessToken: currentCredentials.accessToken,
        organizationId: runtime.organizationId ?? selectedMembership.organizationId,
      });
      setSession(result.value);
      setMembership(selectedMembership);
      setSecurityState("ready");
      setSecurityError(null);
    });
    return () => {
      cancelled = true;
    };
  }, [runtime]);

  const liveRuntimeUnavailable =
    runtime.mode === "live" && (!runtime.sessionClient || !layoutRepository);
  if (liveRuntimeUnavailable) {
    return (
      <div
        className="rounded-2xl border border-rose-400/20 bg-rose-500/10 p-4 text-sm text-rose-200"
        role="alert"
      >
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        {securityError ?? runtime.error ?? "Клієнт захищеної сесії не налаштований."}
      </div>
    );
  }
  if (securityState === "loading") {
    return (
      <div className="rounded-2xl border border-cyan-400/15 bg-[#08182e]/90 p-5 text-sm text-cyan-200">
        <LoaderCircle className="mr-2 inline h-4 w-4 animate-spin" />
        Перевірка доступу…
      </div>
    );
  }
  if (securityState === "error" || !layoutRepository) {
    return (
      <div
        className="rounded-2xl border border-rose-400/20 bg-rose-500/10 p-4 text-sm text-rose-200"
        role="alert"
      >
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        {securityError ?? "Захищена сесія NEXOLAB недоступна."}
      </div>
    );
  }

  const cameraScoped = Boolean(
    effectiveLifecycleRepository && (equipment.climateChamberId || equipment.nodeId),
  );
  const effectiveMode = capabilities.canEdit ? mode : "view";
  const effectiveModeChange = capabilities.canEdit ? onModeChange : () => undefined;
  const configurationChanged = () => {
    setWorkspaceEpoch((current) => current + 1);
    onConfigurationSaved?.();
  };

  return (
    <div
      className={clsx(
        "nexolab-rbac-layout space-y-2",
        !capabilities.canEdit && "nexolab-rbac-no-edit",
        !capabilities.canPublish && "nexolab-rbac-no-publish",
        !capabilities.canRestore && "nexolab-rbac-no-restore",
      )}
    >
      <style jsx global>{`
        .nexolab-rbac-no-edit button[aria-label="Редагувати схему та датчики"],
        .nexolab-rbac-no-edit .production-layout-editor #layout-editor > div > div:first-child > button {
          display: none !important;
        }
        .nexolab-rbac-no-publish button[aria-label="Опублікувати поточну чернетку"] {
          display: none !important;
        }
        .nexolab-rbac-no-restore button[aria-label^="Відновити ревізію"] {
          display: none !important;
        }
      `}</style>

      {cameraScoped ? (
        <div
          className="flex items-center justify-end gap-1.5"
          aria-label="Інструменти робочої області"
        >
          {toolbarTools}

          <details className="group relative">
            <summary
              aria-label="Інформація про доступ"
              title="Доступ оператора"
              className={clsx(
                compactToolClass,
                externallyReadOnly
                  ? "border-slate-300/15 text-slate-400"
                  : "border-emerald-300/15 text-emerald-300",
              )}
            >
              <ShieldCheck className="h-4 w-4" />
            </summary>
            <div className="absolute top-11 right-0 z-[70] w-[min(88vw,360px)] rounded-2xl border border-emerald-300/15 bg-[#07182f]/98 p-3 shadow-2xl shadow-black/45 backdrop-blur-xl">
              {runtime.mode === "demo" ? (
                <p className="text-[10px] text-emerald-100">Demo-доступ · повні можливості</p>
              ) : session && membership ? (
                <>
                  <p className="truncate text-[10px] font-semibold text-white">
                    {session.identity.displayName ??
                      session.identity.email ??
                      session.identity.subject}
                  </p>
                  <p className="mt-1 truncate text-[9px] text-emerald-200/70">
                    {membership.organizationName}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {membership.roles.map((role) => (
                      <span
                        key={role}
                        className="rounded-full border border-emerald-300/15 bg-emerald-300/[0.07] px-2 py-0.5 text-[8px] text-emerald-200"
                      >
                        {role}
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-[10px] text-slate-400">Контекст доступу недоступний.</p>
              )}
              {externallyReadOnly ? (
                <p className="mt-2 border-t border-white/[0.06] pt-2 text-[9px] text-slate-400">
                  Робоча область доступна лише для перегляду.
                </p>
              ) : null}
            </div>
          </details>

          <button
            type="button"
            aria-label="Відкрити версії та публікацію схеми"
            title="Версії схеми"
            onClick={() => setLifecycleOpen(true)}
            className={compactToolClass}
          >
            <History className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      {cameraScoped && effectiveLifecycleRepository ? (
        <CameraScopedLayoutEditor
          key={`camera-editor-${equipment.id}-${workspaceEpoch}`}
          equipment={equipment}
          visibleSensors={visibleSensors}
          selectedId={selectedId}
          mode={effectiveMode}
          onModeChange={effectiveModeChange}
          onSelect={onSelect}
          repository={layoutRepository}
          lifecycleRepository={effectiveLifecycleRepository}
          channels={effectiveChannels}
          bindings={bindings}
          onEquipmentChange={(updated) => {
            onEquipmentChange?.(updated);
            configurationChanged();
          }}
          onDraftChange={configurationChanged}
        />
      ) : (
        <RefrigerationLayoutWorkspace
          key={`${equipment.id}-${workspaceEpoch}`}
          equipment={equipment}
          visibleSensors={visibleSensors}
          selectedId={selectedId}
          mode={effectiveMode}
          onModeChange={effectiveModeChange}
          onSelect={onSelect}
          repository={layoutRepository}
          canEditDraft={capabilities.canEdit}
          canPublish={capabilities.canPublish}
          canRestore={capabilities.canRestore}
        />
      )}

      {lifecycleOpen ? (
        <div
          className="fixed inset-0 z-[95] flex justify-end bg-[#020817]/75 backdrop-blur-sm"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setLifecycleOpen(false);
          }}
        >
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="layout-lifecycle-title"
            className="flex h-full w-full max-w-3xl flex-col border-l border-cyan-300/15 bg-[#07182f] shadow-2xl shadow-black/50"
          >
            <header className="flex items-center gap-3 border-b border-white/[0.07] px-4 py-3">
              <div className="grid h-9 w-9 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-400/[0.06] text-cyan-200">
                <History className="h-4 w-4" />
              </div>
              <h2 id="layout-lifecycle-title" className="min-w-0 flex-1 truncate text-sm font-semibold text-white">
                Версії та публікація схеми
              </h2>
              <button
                type="button"
                aria-label="Закрити версії схеми"
                onClick={() => setLifecycleOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] text-slate-400 hover:border-cyan-300/20 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
              <RefrigerationLayoutLifecyclePanel
                key={`layout-lifecycle-${equipment.id}-${workspaceEpoch}`}
                equipment={equipment}
                mode={effectiveMode}
                repository={layoutRepository}
                actorId={runtime.actorId}
                canEditDraft={capabilities.canEdit}
                canPublish={capabilities.canPublish}
                canRestore={capabilities.canRestore}
                onServerMutation={configurationChanged}
              />
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

const compactToolClass =
  "grid h-9 w-9 cursor-pointer list-none place-items-center rounded-xl border border-white/[0.08] bg-white/[0.035] text-slate-400 transition hover:border-cyan-300/20 hover:text-cyan-100 [&::-webkit-details-marker]:hidden";
