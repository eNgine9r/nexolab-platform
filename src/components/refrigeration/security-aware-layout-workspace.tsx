"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle, ShieldCheck } from "lucide-react";
import { clsx } from "clsx";

import { CameraScopedLayoutEditor } from "@/components/refrigeration/camera-scoped-layout-editor";
import type { LayoutEditorMode } from "@/components/refrigeration/refrigeration-layout-editor";
import { RefrigerationLayoutWorkspace } from "@/components/refrigeration/refrigeration-layout-workspace";
import type { RefrigerationEquipment, RefrigerationSensor } from "@/data/refrigeration";
import type {
  AvailableSensor,
  EquipmentLifecycleRepository,
  SensorBinding,
} from "@/features/refrigeration/equipment-lifecycle-repository";
import { createRefrigerationLayoutRuntime } from "@/features/refrigeration/layout-repository-runtime";
import type { RefrigerationLayoutRepository } from "@/features/refrigeration/layout-repository";
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
  channels?: readonly AvailableSensor[];
  bindings?: readonly SensorBinding[];
  onModeChange: (mode: LayoutEditorMode) => void;
  onSelect: (sensorId: string) => void;
  onEquipmentChange?: (equipment: RefrigerationEquipment) => void;
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
  channels = [],
  bindings = [],
  onModeChange,
  onSelect,
  onEquipmentChange,
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

  const capabilities = useMemo<LayoutCapabilities>(() => {
    if (forceReadOnly) return readOnlyCapabilities;
    if (runtime.mode === "demo") return demoCapabilities;
    if (!session || !membership) return readOnlyCapabilities;
    return {
      canEdit: hasPermission(session, membership.organizationId, "layout.draft.edit"),
      canPublish: hasPermission(session, membership.organizationId, "layout.publish"),
      canRestore: hasPermission(session, membership.organizationId, "layout.restore"),
    };
  }, [forceReadOnly, membership, runtime.mode, session]);

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
        result.value.memberships.find((item) => item.organizationId === runtime.organizationId) ??
        result.value.memberships[0];
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

  const notifyRepositoryMutation = () => {
    window.setTimeout(() => setWorkspaceEpoch((current) => current + 1), 0);
  };
  const synchronizedRepository = useMemo(
    () => (runtime.repository ? observeMutations(runtime.repository, notifyRepositoryMutation) : null),
    [runtime.repository],
  );

  const liveRuntimeUnavailable = runtime.mode === "live" && (!runtime.sessionClient || !runtime.repository);

  if (liveRuntimeUnavailable) {
    return (
      <div className="rounded-2xl border border-rose-400/20 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert">
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

  if (securityState === "error" || !runtime.repository || !synchronizedRepository) {
    return (
      <div className="rounded-2xl border border-rose-400/20 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert">
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        {securityError ?? "Захищена сесія NEXOLAB недоступна."}
      </div>
    );
  }

  const cameraScoped = Boolean(lifecycleRepository && equipment.nodeId);

  return (
    <div
      className={clsx(
        "nexolab-rbac-layout space-y-3",
        cameraScoped && "nexolab-camera-scoped-layout",
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
        .nexolab-rbac-no-publish > div > section > div:nth-child(2) > button {
          display: none !important;
        }
        .nexolab-rbac-no-restore > div > section > div:nth-child(3) button {
          display: none !important;
        }
        .nexolab-camera-scoped-layout .camera-scoped-secondary .production-layout-editor {
          display: none !important;
        }
      `}</style>

      {forceReadOnly ? (
        <div className="rounded-2xl border border-slate-400/15 bg-slate-400/[0.06] px-4 py-3 text-xs text-slate-300">
          Lifecycle `retired`: схема заблокована для змін, публікації та відновлення.
        </div>
      ) : membership && session ? (
        <div className="flex flex-col gap-2 rounded-2xl border border-emerald-400/15 bg-emerald-500/[0.06] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 text-xs text-emerald-100">
            <ShieldCheck className="h-4 w-4 text-emerald-300" />
            <span className="font-medium">
              {session.identity.displayName ?? session.identity.email ?? session.identity.subject}
            </span>
            <span className="text-emerald-200/50">·</span>
            <span className="text-emerald-200/70">{membership.organizationName}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {membership.roles.map((role) => (
              <span key={role} className="rounded-full border border-emerald-300/15 bg-emerald-300/[0.07] px-2 py-1 text-[9px] text-emerald-200">
                {role}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {cameraScoped && lifecycleRepository ? (
        <CameraScopedLayoutEditor
          key={`camera-editor-${equipment.id}-${workspaceEpoch}`}
          equipment={equipment}
          visibleSensors={visibleSensors}
          selectedId={selectedId}
          mode={capabilities.canEdit ? mode : "view"}
          onModeChange={capabilities.canEdit ? onModeChange : () => undefined}
          onSelect={onSelect}
          repository={runtime.repository}
          lifecycleRepository={lifecycleRepository}
          channels={channels}
          bindings={bindings}
          onEquipmentChange={(updated) => {
            onEquipmentChange?.(updated);
            setWorkspaceEpoch((current) => current + 1);
          }}
          onDraftChange={() => setWorkspaceEpoch((current) => current + 1)}
        />
      ) : null}

      <div className={cameraScoped ? "camera-scoped-secondary" : undefined}>
        <RefrigerationLayoutWorkspace
          key={`lifecycle-workspace-${equipment.id}-${workspaceEpoch}`}
          equipment={equipment}
          visibleSensors={visibleSensors}
          selectedId={selectedId}
          mode={capabilities.canEdit ? mode : "view"}
          onModeChange={capabilities.canEdit ? onModeChange : () => undefined}
          onSelect={onSelect}
          repository={synchronizedRepository}
        />
      </div>
    </div>
  );
}

function observeMutations(
  repository: RefrigerationLayoutRepository,
  onMutation: () => void,
): RefrigerationLayoutRepository {
  return {
    getDraft: (equipmentId) => repository.getDraft(equipmentId),
    getPublished: (equipmentId) => repository.getPublished(equipmentId),
    listHistory: (equipmentId) => repository.listHistory(equipmentId),
    async saveDraft(input) {
      const result = await repository.saveDraft(input);
      if (result.ok) onMutation();
      return result;
    },
    async publishDraft(input) {
      const result = await repository.publishDraft(input);
      if (result.ok) onMutation();
      return result;
    },
    async restoreRevision(input) {
      const result = await repository.restoreRevision(input);
      if (result.ok) onMutation();
      return result;
    },
    uploadImage: (input) => repository.uploadImage(input),
  };
}
