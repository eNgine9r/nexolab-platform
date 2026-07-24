"use client";

import type { ChangeEvent } from "react";
import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Clock3,
  Cloud,
  History,
  ImagePlus,
  LoaderCircle,
  RefreshCcw,
  RotateCcw,
  UploadCloud,
} from "lucide-react";

import {
  RefrigerationLayoutEditor,
  type LayoutEditorMode,
} from "@/components/refrigeration/refrigeration-layout-editor";
import type {
  EquipmentImageMetadata,
  RefrigerationEquipment,
  RefrigerationSensor,
} from "@/data/refrigeration";
import { createRefrigerationLayoutRuntime } from "@/features/refrigeration/layout-repository-runtime";
import type {
  LayoutRepositoryError,
  PublishedLayoutRevision,
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";

const acceptedImageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageSizeBytes = 15 * 1024 * 1024;

type ConflictOperation = "save" | "publish" | "restore" | "attach-image";

type ConflictState = {
  operation: ConflictOperation;
  expectedVersion: number;
  actualVersion: number;
};

type ActionState = "idle" | "uploading" | "attaching" | "publishing" | "restoring" | "reloading";

type UploadPreview = {
  url: string;
  fileName: string;
  sizeBytes: number;
};

type RefrigerationLayoutWorkspaceProps = {
  equipment: RefrigerationEquipment;
  visibleSensors: RefrigerationSensor[];
  selectedId: string | null;
  mode: LayoutEditorMode;
  onModeChange: (mode: LayoutEditorMode) => void;
  onSelect: (sensorId: string) => void;
  repository?: RefrigerationLayoutRepository;
  actorId?: string;
  runtimeMode?: "demo" | "live";
};

export function RefrigerationLayoutWorkspace({
  equipment,
  visibleSensors,
  selectedId,
  mode,
  onModeChange,
  onSelect,
  repository: repositoryOverride,
  actorId: actorIdOverride,
  runtimeMode,
}: RefrigerationLayoutWorkspaceProps) {
  const runtime = useMemo(
    () =>
      repositoryOverride
        ? {
            mode: runtimeMode ?? "live",
            repository: repositoryOverride,
            actorId: actorIdOverride?.trim() || "dashboard-operator",
            error: null,
          }
        : createRefrigerationLayoutRuntime({ equipment }),
    [actorIdOverride, equipment, repositoryOverride, runtimeMode],
  );
  const baseRepository = runtime.repository;

  const [draft, setDraft] = useState<RefrigerationLayoutDraft | null>(null);
  const [published, setPublished] = useState<PublishedLayoutRevision | null>(null);
  const [history, setHistory] = useState<PublishedLayoutRevision[]>([]);
  const [workspaceState, setWorkspaceState] = useState<"loading" | "ready">("loading");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(runtime.error);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [editorEpoch, setEditorEpoch] = useState(0);
  const [uploadPreview, setUploadPreview] = useState<UploadPreview | null>(null);
  const [pendingImage, setPendingImage] = useState<EquipmentImageMetadata | null>(null);
  const photoInputRef = useRef<HTMLInputElement>(null);

  const registerConflict = useCallback((operation: ConflictOperation, error: LayoutRepositoryError) => {
    if (error.code !== "LAYOUT_VERSION_CONFLICT") return;
    setConflict({
      operation,
      expectedVersion: error.expectedVersion,
      actualVersion: error.actualVersion,
    });
  }, []);

  const repository = useMemo(
    () =>
      baseRepository
        ? observeRepository(baseRepository, {
            onDraft: setDraft,
            onPublished: setPublished,
            onHistory: setHistory,
            onConflict: registerConflict,
          })
        : null,
    [baseRepository, registerConflict],
  );

  const loadWorkspace = useCallback(async () => {
    if (!baseRepository) {
      setWorkspaceState("ready");
      setErrorMessage(runtime.error ?? "Сховище схем обладнання недоступне.");
      return;
    }

    setWorkspaceState("loading");
    setErrorMessage(null);
    const [draftResult, publishedResult, historyResult] = await Promise.all([
      baseRepository.getDraft(equipment.id),
      baseRepository.getPublished(equipment.id),
      baseRepository.listHistory(equipment.id),
    ]);

    const failure = [draftResult, publishedResult, historyResult].find((result) => !result.ok);
    if (failure && !failure.ok) {
      setErrorMessage(repositoryErrorMessage(failure.error));
      setWorkspaceState("ready");
      return;
    }

    if (draftResult.ok && publishedResult.ok && historyResult.ok) {
      setDraft(draftResult.value);
      setPublished(publishedResult.value);
      setHistory(historyResult.value);
    }
    setWorkspaceState("ready");
  }, [baseRepository, equipment.id, runtime.error]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(
    () => () => {
      if (uploadPreview) URL.revokeObjectURL(uploadPreview.url);
    },
    [uploadPreview],
  );

  const effectiveEquipment = useMemo(
    () => ({ ...equipment, image: draft?.image ?? equipment.image }),
    [draft?.image, equipment],
  );

  const clearFeedback = () => {
    setErrorMessage(null);
    setNotice(null);
    setConflict(null);
  };

  const attachImage = async (image: EquipmentImageMetadata, expectedVersion: number) => {
    if (!repository || !draft) return;

    setActionState("attaching");
    const result = await repository.saveDraft({
      equipmentId: equipment.id,
      expectedVersion,
      imageId: image.id,
      placements: draft.placements,
    });

    if (!result.ok) {
      registerConflict("attach-image", result.error);
      setPendingImage(image);
      setErrorMessage(repositoryErrorMessage(result.error));
      setActionState("idle");
      return;
    }

    setDraft(result.value);
    setPendingImage(null);
    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview.url);
      setUploadPreview(null);
    }
    setEditorEpoch((current) => current + 1);
    setNotice(`Фото ${image.fileName} завантажено та прив’язано до чернетки v${result.value.version}.`);
    setActionState("idle");
  };

  const handlePhotoChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !repository || !draft) return;

    clearFeedback();
    if (mode === "edit") {
      setErrorMessage("Спочатку збережіть або скасуйте зміни позицій датчиків.");
      return;
    }
    if (!acceptedImageTypes.has(file.type)) {
      setErrorMessage("Підтримуються лише JPEG, PNG та WebP.");
      return;
    }
    if (file.size > maxImageSizeBytes) {
      setErrorMessage("Розмір фото не повинен перевищувати 15 МБ.");
      return;
    }

    if (uploadPreview) URL.revokeObjectURL(uploadPreview.url);
    const previewUrl = URL.createObjectURL(file);
    setUploadPreview({
      url: previewUrl,
      fileName: file.name,
      sizeBytes: file.size,
    });
    setActionState("uploading");

    const result = await repository.uploadImage({
      equipmentId: equipment.id,
      file,
      actorId: runtime.actorId,
    });
    if (!result.ok) {
      setErrorMessage(repositoryErrorMessage(result.error));
      setActionState("idle");
      return;
    }

    setPendingImage(result.value);
    await attachImage(result.value, draft.version);
  };

  const handlePublish = async () => {
    if (!repository || !draft || actionState !== "idle") return;
    clearFeedback();
    if (mode === "edit") {
      setErrorMessage("Збережіть або скасуйте редагування перед публікацією.");
      return;
    }
    if (!draft.imageId) {
      setErrorMessage("Для публікації спочатку завантажте фото обладнання.");
      return;
    }

    setActionState("publishing");
    const result = await repository.publishDraft({
      equipmentId: equipment.id,
      expectedVersion: draft.version,
      actorId: runtime.actorId,
    });
    if (!result.ok) {
      registerConflict("publish", result.error);
      setErrorMessage(repositoryErrorMessage(result.error));
      setActionState("idle");
      return;
    }

    setDraft(result.value.draft);
    setPublished(result.value.published);
    const historyResult = await repository.listHistory(equipment.id);
    if (historyResult.ok) setHistory(historyResult.value);
    setEditorEpoch((current) => current + 1);
    setNotice(`Опубліковано ревізію r${result.value.published.revision}.`);
    setActionState("idle");
  };

  const handleRestore = async (revision: PublishedLayoutRevision) => {
    if (!repository || !draft || actionState !== "idle") return;
    clearFeedback();
    if (mode === "edit") {
      setErrorMessage("Збережіть або скасуйте редагування перед відновленням історії.");
      return;
    }
    if (!window.confirm(`Відновити ревізію r${revision.revision} як нову чернетку?`)) {
      return;
    }

    setActionState("restoring");
    const result = await repository.restoreRevision({
      equipmentId: equipment.id,
      revisionId: revision.id,
      expectedVersion: draft.version,
    });
    if (!result.ok) {
      registerConflict("restore", result.error);
      setErrorMessage(repositoryErrorMessage(result.error));
      setActionState("idle");
      return;
    }

    setDraft(result.value);
    setEditorEpoch((current) => current + 1);
    onModeChange("edit");
    setNotice(`Ревізію r${revision.revision} відновлено як чернетку v${result.value.version}.`);
    setActionState("idle");
  };

  const handleReloadServerDraft = async () => {
    if (!baseRepository || actionState !== "idle") return;
    if (
      mode === "edit" &&
      !window.confirm("Завантажити серверну версію та відкинути локальні незбережені зміни?")
    ) {
      return;
    }

    setActionState("reloading");
    const result = await baseRepository.getDraft(equipment.id);
    if (!result.ok) {
      setErrorMessage(repositoryErrorMessage(result.error));
      setActionState("idle");
      return;
    }

    setDraft(result.value);
    setConflict(null);
    setErrorMessage(null);
    setEditorEpoch((current) => current + 1);
    onModeChange("view");
    setNotice(`Завантажено серверну чернетку v${result.value.version}.`);
    setActionState("idle");
  };

  const handleRetryImageAttachment = async () => {
    if (!pendingImage || !draft || actionState !== "idle") return;
    clearFeedback();
    await attachImage(pendingImage, draft.version);
  };

  if (workspaceState === "loading") {
    return (
      <div className="rounded-2xl border border-cyan-400/15 bg-[#08182e]/90 p-6 text-sm text-cyan-200">
        <LoaderCircle className="mr-2 inline h-4 w-4 animate-spin" />
        Завантаження production-схеми, публікації та історії…
      </div>
    );
  }

  if (!repository || !draft) {
    return (
      <div
        className="rounded-2xl border border-rose-400/20 bg-rose-500/10 p-4 text-sm text-rose-200"
        role="alert"
      >
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        {errorMessage ?? "Чернетку схеми не вдалося завантажити."}
        <button
          type="button"
          onClick={() => void loadWorkspace()}
          className="ml-3 rounded-lg border border-rose-300/20 px-2.5 py-1.5 text-xs hover:bg-rose-300/10"
        >
          Повторити
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="production-layout-editor">
        <style jsx global>{`
          .production-layout-editor input[aria-label="Завантажити фото обладнання"] + button {
            display: none;
          }
        `}</style>
        <RefrigerationLayoutEditor
          key={`${equipment.id}-${editorEpoch}`}
          equipment={effectiveEquipment}
          visibleSensors={visibleSensors}
          selectedId={selectedId}
          mode={mode}
          onModeChange={onModeChange}
          onSelect={onSelect}
          repository={repository}
        />
      </div>

      {errorMessage ? <Feedback tone="error">{errorMessage}</Feedback> : null}
      {notice ? <Feedback tone="success">{notice}</Feedback> : null}
      {conflict ? (
        <ConflictRecovery
          conflict={conflict}
          busy={actionState !== "idle"}
          onContinue={() => setConflict(null)}
          onReload={() => void handleReloadServerDraft()}
        />
      ) : null}

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_1.25fr]">
        <PhotoUploadCard
          draft={draft}
          mode={mode}
          actionState={actionState}
          preview={uploadPreview}
          pendingImage={pendingImage}
          inputRef={photoInputRef}
          onChange={handlePhotoChange}
          onOpen={() => photoInputRef.current?.click()}
          onRetry={() => void handleRetryImageAttachment()}
        />
        <PublicationCard
          draft={draft}
          published={published}
          runtimeMode={runtime.mode}
          busy={actionState !== "idle"}
          mode={mode}
          onPublish={() => void handlePublish()}
        />
        <HistoryCard
          items={history}
          busy={actionState !== "idle"}
          mode={mode}
          onRestore={(revision) => void handleRestore(revision)}
        />
      </section>
    </div>
  );
}

function PhotoUploadCard({
  draft,
  mode,
  actionState,
  preview,
  pendingImage,
  inputRef,
  onChange,
  onOpen,
  onRetry,
}: {
  draft: RefrigerationLayoutDraft;
  mode: LayoutEditorMode;
  actionState: ActionState;
  preview: UploadPreview | null;
  pendingImage: EquipmentImageMetadata | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onOpen: () => void;
  onRetry: () => void;
}) {
  const uploading = actionState === "uploading" || actionState === "attaching";
  const disabled = mode === "edit" || actionState !== "idle";

  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-white">Production-фото</p>
          <p className="mt-1 text-[10px] text-slate-500">S3-compatible storage · JPEG/PNG/WebP · до 15 МБ</p>
        </div>
        <ImagePlus className="h-4 w-4 text-cyan-300" />
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="sr-only"
        aria-label="Вибрати production-фото обладнання"
        onChange={onChange}
      />

      {preview ? (
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-cyan-400/15 bg-cyan-500/[0.06] p-2">
          <Image
            src={preview.url}
            alt="Локальний preview завантаження"
            width={84}
            height={56}
            unoptimized
            className="h-14 w-[84px] rounded-lg object-cover"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[11px] text-slate-200">{preview.fileName}</p>
            <p className="mt-1 text-[9px] text-cyan-300">
              {uploading ? "Завантаження та прив’язка…" : formatFileSize(preview.sizeBytes)}
            </p>
          </div>
          {uploading ? <LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> : null}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
          <p className="truncate text-[11px] text-slate-300">
            {draft.image?.fileName ?? "Фото ще не прив’язано"}
          </p>
          <p className="mt-1 text-[9px] text-slate-600">
            {draft.image
              ? `${draft.image.widthPx}×${draft.image.heightPx} · ${formatFileSize(draft.image.sizeBytes)}`
              : "Завантажте фото перед публікацією"}
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={onOpen}
          className="inline-flex items-center gap-2 rounded-xl border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200 enabled:hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <UploadCloud className="h-3.5 w-3.5" />
          {draft.image ? "Замінити фото" : "Завантажити фото"}
        </button>
        {pendingImage && actionState === "idle" ? (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
          >
            <RefreshCcw className="h-3.5 w-3.5" />
            Повторити прив’язку
          </button>
        ) : null}
      </div>
      {mode === "edit" ? (
        <p className="mt-2 text-[9px] text-amber-300">Збережіть позиції датчиків перед заміною фото.</p>
      ) : null}
    </div>
  );
}

function PublicationCard({
  draft,
  published,
  runtimeMode,
  busy,
  mode,
  onPublish,
}: {
  draft: RefrigerationLayoutDraft;
  published: PublishedLayoutRevision | null;
  runtimeMode: "demo" | "live";
  busy: boolean;
  mode: LayoutEditorMode;
  onPublish: () => void;
}) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-white">Публікація</p>
          <p className="mt-1 text-[10px] text-slate-500">
            Чернетка v{draft.version} · {runtimeMode === "live" ? "PostgreSQL" : "Demo"}
          </p>
        </div>
        <Cloud className="h-4 w-4 text-blue-300" />
      </div>

      <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
        {published ? (
          <>
            <p className="text-sm font-semibold text-emerald-200">Ревізія r{published.revision}</p>
            <p className="mt-1 text-[10px] text-slate-500">
              {formatDateTime(published.publishedAt)} · {published.publishedBy}
            </p>
            <p className="mt-1 truncate text-[9px] text-slate-600">{published.image.fileName}</p>
          </>
        ) : (
          <p className="text-[11px] text-slate-500">Опублікованої ревізії ще немає.</p>
        )}
      </div>

      <button
        type="button"
        disabled={busy || mode === "edit" || !draft.imageId}
        onClick={onPublish}
        className="mt-3 inline-flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-200 enabled:hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        Опублікувати поточну чернетку
      </button>
    </div>
  );
}

function HistoryCard({
  items,
  busy,
  mode,
  onRestore,
}: {
  items: PublishedLayoutRevision[];
  busy: boolean;
  mode: LayoutEditorMode;
  onRestore: (revision: PublishedLayoutRevision) => void;
}) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-white">Історія схем</p>
          <p className="mt-1 text-[10px] text-slate-500">Незмінні ревізії · новіші зверху</p>
        </div>
        <History className="h-4 w-4 text-violet-300" />
      </div>

      <div className="mt-3 max-h-48 space-y-2 overflow-y-auto pr-1">
        {items.length === 0 ? (
          <p className="rounded-xl border border-dashed border-white/[0.07] p-3 text-[11px] text-slate-600">
            Історія з’явиться після першої публікації.
          </p>
        ) : (
          items.map((revision) => (
            <div
              key={revision.id}
              className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5"
            >
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-violet-400/10 text-[10px] font-semibold text-violet-200">
                r{revision.revision}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[10px] text-slate-300">{revision.image.fileName}</p>
                <p className="mt-1 inline-flex items-center gap-1 text-[9px] text-slate-600">
                  <Clock3 className="h-3 w-3" />
                  {formatDateTime(revision.publishedAt)}
                </p>
              </div>
              <button
                type="button"
                disabled={busy || mode === "edit"}
                onClick={() => onRestore(revision)}
                className="inline-flex items-center gap-1 rounded-lg border border-white/[0.08] px-2 py-1.5 text-[9px] text-slate-400 enabled:hover:bg-white/[0.05] enabled:hover:text-white disabled:opacity-35"
              >
                <RotateCcw className="h-3 w-3" />
                Відновити
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ConflictRecovery({
  conflict,
  busy,
  onContinue,
  onReload,
}: {
  conflict: ConflictState;
  busy: boolean;
  onContinue: () => void;
  onReload: () => void;
}) {
  return (
    <div
      className="rounded-2xl border border-amber-400/25 bg-amber-500/10 p-4 text-xs text-amber-100"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">End-to-end конфлікт версій</p>
          <p className="mt-1 leading-5 text-amber-100/80">
            Операція «{operationLabel(conflict.operation)}» очікувала v{conflict.expectedVersion}, але сервер
            уже зберігає v{conflict.actualVersion}. Локальні позиції та preview фото не перезаписано.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onContinue}
              className="rounded-lg border border-amber-300/20 px-2.5 py-1.5 text-[10px] hover:bg-amber-300/10 disabled:opacity-40"
            >
              Продовжити локально
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onReload}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300/25 bg-amber-300/10 px-2.5 py-1.5 text-[10px] hover:bg-amber-300/15 disabled:opacity-40"
            >
              <RefreshCcw className="h-3 w-3" />
              Завантажити серверну v{conflict.actualVersion}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Feedback({ children, tone }: { children: React.ReactNode; tone: "error" | "success" }) {
  return (
    <div
      className={
        tone === "success"
          ? "rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
          : "rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
      }
      role={tone === "error" ? "alert" : "status"}
    >
      {tone === "success" ? (
        <Check className="mr-2 inline h-3.5 w-3.5" />
      ) : (
        <AlertTriangle className="mr-2 inline h-3.5 w-3.5" />
      )}
      {children}
    </div>
  );
}

type RepositoryObserverHooks = {
  onDraft: (draft: RefrigerationLayoutDraft) => void;
  onPublished: (published: PublishedLayoutRevision | null) => void;
  onHistory: (history: PublishedLayoutRevision[]) => void;
  onConflict: (operation: ConflictOperation, error: LayoutRepositoryError) => void;
};

function observeRepository(
  repository: RefrigerationLayoutRepository,
  hooks: RepositoryObserverHooks,
): RefrigerationLayoutRepository {
  return {
    async getDraft(equipmentId) {
      const result = await repository.getDraft(equipmentId);
      if (result.ok) hooks.onDraft(result.value);
      return result;
    },
    async getPublished(equipmentId) {
      const result = await repository.getPublished(equipmentId);
      if (result.ok) hooks.onPublished(result.value);
      return result;
    },
    async saveDraft(input) {
      const result = await repository.saveDraft(input);
      if (result.ok) hooks.onDraft(result.value);
      else hooks.onConflict("save", result.error);
      return result;
    },
    async publishDraft(input) {
      const result = await repository.publishDraft(input);
      if (result.ok) {
        hooks.onDraft(result.value.draft);
        hooks.onPublished(result.value.published);
      } else {
        hooks.onConflict("publish", result.error);
      }
      return result;
    },
    async listHistory(equipmentId) {
      const result = await repository.listHistory(equipmentId);
      if (result.ok) hooks.onHistory(result.value);
      return result;
    },
    async restoreRevision(input) {
      const result = await repository.restoreRevision(input);
      if (result.ok) hooks.onDraft(result.value);
      else hooks.onConflict("restore", result.error);
      return result;
    },
    uploadImage(input) {
      return repository.uploadImage(input);
    },
  };
}

function repositoryErrorMessage(error: LayoutRepositoryError): string {
  if (error.code === "LAYOUT_NOT_FOUND") {
    return "Чернетку схеми не знайдено.";
  }
  if (error.code === "LAYOUT_REVISION_NOT_FOUND") {
    return "Вибрану ревізію схеми не знайдено.";
  }
  if (error.code === "LAYOUT_VERSION_CONFLICT") {
    return `Конфлікт версій: очікувалась v${error.expectedVersion}, сервер має v${error.actualVersion}.`;
  }
  return error.issues.map((issue) => issue.message).join(" ");
}

function operationLabel(operation: ConflictOperation): string {
  if (operation === "publish") return "публікація";
  if (operation === "restore") return "відновлення";
  if (operation === "attach-image") return "прив’язка фото";
  return "збереження";
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(sizeBytes / 1024))} КБ`;
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} МБ`;
}
