"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle, ShieldCheck } from "lucide-react";
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
  /** Legacy camera-scoped repository prop. */
  lifecycleRepository?: EquipmentLifecycleRepository | null;
  /** Explicit repository name used by the atomic configuration workspace. */
  sensorConfigurationRepository?: EquipmentLifecycleRepository | null;
  /** Legacy available-channel prop. */
  channels?: readonly AvailableSensor[];
  /** Explicit available-channel prop used by the detail screen. */
  availableSensors?: readonly AvailableSensor[];
  bindings?: readonly SensorBinding[];
  canManageEquipment?: boolean;
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
  onModeChange,
  onSelect,
  onEquipmentChange,
  onConfigurationSaved,
  onCapabilitiesChange,
}: SecurityAwareLayoutWorkspaceProps) {
  const runtime = useMemo(() => createRefrigerationLayoutRuntime({ equipment }), [equipment]);
  const [session, setSession] = useState<SecuritySession | null>(null);
  const [membership, setMembership] = useState<SecurityMembership | null>(null);
  const [securityState, setSecurityState] = useState<"loading" | "ready" | "error">(
    runtime.mode === "demo" ? "ready" : "loading",
  );
  const [securityError, setSecurityError] = useState<string | null>(runtime.error);
  const [workspaceEpoch, setWorkspaceEpoch] = useState(0);

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
    runtime.mode === "live" && (!runtime.sessionClient || !runtime.repository);
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
        Перевірка ролі, організації та дозволів оператора…
      </div>
    );
  }
  if (securityState === "error" || !runtime.repository) {
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
        "nexolab-rbac-layout space-y-3",
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

      {membership && session ? (
        <div className="flex flex-col gap-2 rounded-2xl border border-emerald-400/15 bg-emerald-500/[0.06] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 text-xs text-emerald-100">
            <ShieldCheck className="h-4 w-4 text-emerald-300" />
            <span className="font-medium">
              {session.identity.displayName ??
                session.identity.email ??
                session.identity.subject}
            </span>
            <span className="text-emerald-200/50">·</span>
            <span className="text-emerald-200/70">{membership.organizationName}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {membership.roles.map((role) => (
              <span
                key={role}
                className="rounded-full border border-emerald-300/15 bg-emerald-300/[0.07] px-2 py-1 text-[9px] text-emerald-200"
              >
                {role}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {externallyReadOnly ? (
        <div className="rounded-2xl border border-slate-400/15 bg-slate-400/[0.06] px-4 py-3 text-xs text-slate-300">
          Схема доступна лише для перегляду відповідно до lifecycle та дозволів.
        </div>
      ) : null}

      {cameraScoped && effectiveLifecycleRepository ? (
        <>
          <CameraScopedLayoutEditor
            key={`camera-editor-${equipment.id}-${workspaceEpoch}`}
            equipment={equipment}
            visibleSensors={visibleSensors}
            selectedId={selectedId}
            mode={effectiveMode}
            onModeChange={effectiveModeChange}
            onSelect={onSelect}
            repository={runtime.repository}
            lifecycleRepository={effectiveLifecycleRepository}
            channels={effectiveChannels}
            bindings={bindings}
            onEquipmentChange={(updated) => {
              onEquipmentChange?.(updated);
              configurationChanged();
            }}
            onDraftChange={configurationChanged}
          />
          <RefrigerationLayoutLifecyclePanel
            key={`layout-lifecycle-${equipment.id}-${workspaceEpoch}`}
            equipment={equipment}
            mode={effectiveMode}
            repository={runtime.repository}
            actorId={runtime.actorId}
            canEditDraft={capabilities.canEdit}
            canPublish={capabilities.canPublish}
            canRestore={capabilities.canRestore}
            onServerMutation={configurationChanged}
          />
        </>
      ) : (
        <RefrigerationLayoutWorkspace
          key={`${equipment.id}-${workspaceEpoch}`}
          equipment={equipment}
          visibleSensors={visibleSensors}
          selectedId={selectedId}
          mode={effectiveMode}
          onModeChange={effectiveModeChange}
          onSelect={onSelect}
          repository={runtime.repository}
        />
      )}
    </div>
  );
}
