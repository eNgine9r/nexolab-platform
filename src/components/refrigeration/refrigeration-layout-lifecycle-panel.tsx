"use client";

import type { ChangeEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Cloud,
  History,
  ImagePlus,
  LoaderCircle,
  RotateCcw,
  UploadCloud,
} from "lucide-react";

import { RefrigerationIconButton } from "@/components/refrigeration/refrigeration-icon-button";
import type { RefrigerationEquipment } from "@/data/refrigeration";
import type {
  PublishedLayoutRevision,
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";

const acceptedImageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageSizeBytes = 1536 * 1024;
const imageLimitMessage =
  "Розмір зображення перевищує допустимі 1,5 МБ. Стисніть файл або завантажте інше зображення.";

type ActionState = "idle" | "uploading" | "publishing" | "restoring";

export function RefrigerationLayoutLifecyclePanel({
  equipment,
  mode,
  repository,
  actorId = "dashboard-operator",
  onServerMutation,
}: {
  equipment: RefrigerationEquipment;
  mode: "view" | "edit";
  repository: RefrigerationLayoutRepository;
  actorId?: string;
  onServerMutation: () => void;
}) {
  const [draft, setDraft] = useState<RefrigerationLayoutDraft | null>(null);
  const [published, setPublished] = useState<PublishedLayoutRevision | null>(null);
  const [historyItems, setHistoryItems] = useState<PublishedLayoutRevision[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<ActionState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const photoInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [draftResult, publishedResult, historyResult] = await Promise.all([
      repository.getDraft(equipment.id),
      repository.getPublished(equipment.id),
      repository.listHistory(equipment.id),
    ]);
    const failed = [draftResult, publishedResult, historyResult].find((result) => !result.ok);
    if (failed && !failed.ok) {
      setError(repositoryErrorMessage(failed.error));
      setLoading(false);
      return;
    }
    if (draftResult.ok && publishedResult.ok && historyResult.ok) {
      setDraft(draftResult.value);
      setPublished(publishedResult.value);
      setHistoryItems(historyResult.value);
    }
    setLoading(false);
  }, [equipment.id, repository]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const uploadPhoto = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !draft || action !== "idle") return;
    setError(null);
    setNotice(null);
    if (mode === "edit") {
      setError("Спочатку збережіть або скасуйте зміни датчиків.");
      return;
    }
    if (!acceptedImageTypes.has(file.type)) {
      setError("Підтримуються лише JPEG, PNG та WebP.");
      return;
    }
    if (file.size > maxImageSizeBytes) {
      setError(imageLimitMessage);
      return;
    }

    setAction("uploading");
    const uploaded = await repository.uploadImage({ equipmentId: equipment.id, file, actorId });
    if (!uploaded.ok) {
      setError(repositoryErrorMessage(uploaded.error));
      setAction("idle");
      return;
    }
    const attached = await repository.saveDraft({
      equipmentId: equipment.id,
      expectedVersion: draft.version,
      imageId: uploaded.value.id,
      placements: draft.placements,
    });
    if (!attached.ok) {
      setError(repositoryErrorMessage(attached.error));
      setAction("idle");
      return;
    }
    setDraft(attached.value);
    setNotice(`Фото ${file.name} завантажено та прив’язано до чернетки v${attached.value.version}.`);
    setAction("idle");
    onServerMutation();
  };

  const publish = async () => {
    if (!draft || action !== "idle") return;
    setError(null);
    setNotice(null);
    if (mode === "edit") {
      setError("Збережіть або скасуйте редагування перед публікацією.");
      return;
    }
    if (!draft.imageId) {
      setError("Для публікації спочатку завантажте фото обладнання.");
      return;
    }
    if (draft.placements.length === 0) {
      setError("Для публікації розмістіть хоча б один датчик.");
      return;
    }
    setAction("publishing");
    const result = await repository.publishDraft({
      equipmentId: equipment.id,
      expectedVersion: draft.version,
      actorId,
    });
    if (!result.ok) {
      setError(repositoryErrorMessage(result.error));
      setAction("idle");
      return;
    }
    setDraft(result.value.draft);
    setPublished(result.value.published);
    const updatedHistory = await repository.listHistory(equipment.id);
    if (updatedHistory.ok) setHistoryItems(updatedHistory.value);
    setNotice(`Опубліковано ревізію r${result.value.published.revision}.`);
    setAction("idle");
    onServerMutation();
  };

  const restore = async (revision: PublishedLayoutRevision) => {
    if (!draft || action !== "idle") return;
    if (mode === "edit") {
      setError("Збережіть або скасуйте редагування перед відновленням історії.");
      return;
    }
    if (!window.confirm(`Відновити ревізію r${revision.revision} як нову чернетку?`)) return;
    setAction("restoring");
    setError(null);
    setNotice(null);
    const result = await repository.restoreRevision({
      equipmentId: equipment.id,
      revisionId: revision.id,
      expectedVersion: draft.version,
    });
    if (!result.ok) {
      setError(repositoryErrorMessage(result.error));
      setAction("idle");
      return;
    }
    setDraft(result.value);
    setNotice(`Ревізію r${revision.revision} відновлено як чернетку v${result.value.version}.`);
    setAction("idle");
    onServerMutation();
  };

  if (loading || !draft) {
    return (
      <div className="rounded-2xl border border-cyan-400/15 bg-[#08182e]/90 p-5 text-xs text-cyan-200">
        <LoaderCircle className="mr-2 inline h-4 w-4 animate-spin" />
        Завантаження фото, публікації та історії…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error ? <Feedback tone="error">{error}</Feedback> : null}
      {notice ? <Feedback tone="success">{notice}</Feedback> : null}

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_1.25fr]">
        <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <ImagePlus className="h-4 w-4 text-cyan-300" />
                <h3 className="text-xs font-semibold text-white">Production-фото</h3>
              </div>
              <p className="mt-1 text-[10px] text-slate-500">JPEG, PNG або WebP · максимум 1,5 МБ</p>
            </div>
            <input
              ref={photoInput}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              aria-label="Вибрати production-фото обладнання"
              className="sr-only"
              onChange={uploadPhoto}
            />
            <RefrigerationIconButton
              label={draft.image ? "Замінити production-фото" : "Завантажити production-фото"}
              onClick={() => photoInput.current?.click()}
              disabled={action !== "idle" || mode === "edit"}
              tone="info"
            >
              {action === "uploading" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <UploadCloud className="h-4 w-4" />
              )}
            </RefrigerationIconButton>
          </div>
          <p className="mt-4 truncate rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2 text-[10px] text-slate-300">
            {draft.image?.fileName ?? "Фото ще не завантажено"}
          </p>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Cloud className="h-4 w-4 text-cyan-300" />
                <h3 className="text-xs font-semibold text-white">Публікація</h3>
              </div>
              <p className="mt-1 text-[10px] text-slate-500">
                {published ? `Активна ревізія r${published.revision}` : "Опублікованої ревізії немає"}
              </p>
            </div>
            <RefrigerationIconButton
              label="Опублікувати поточну чернетку"
              onClick={() => void publish()}
              disabled={action !== "idle" || mode === "edit" || !draft.imageId || draft.placements.length === 0}
              tone="success"
            >
              {action === "publishing" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
            </RefrigerationIconButton>
          </div>
          <p className="mt-4 text-[10px] leading-5 text-slate-400">
            Чернетка v{draft.version} · {draft.placements.length} розміщених датчиків
          </p>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#08182e]/90 p-4">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-cyan-300" />
            <h3 className="text-xs font-semibold text-white">Історія схем</h3>
          </div>
          <div className="mt-3 max-h-32 space-y-2 overflow-y-auto pr-1">
            {historyItems.length === 0 ? (
              <p className="text-[10px] text-slate-500">Історія поки порожня.</p>
            ) : (
              historyItems.map((revision) => (
                <div
                  key={revision.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-[10px] font-semibold text-slate-200">Ревізія r{revision.revision}</p>
                    <p className="truncate text-[9px] text-slate-600">{revision.image.fileName}</p>
                  </div>
                  <RefrigerationIconButton
                    label={`Відновити ревізію r${revision.revision}`}
                    onClick={() => void restore(revision)}
                    disabled={action !== "idle" || mode === "edit"}
                    size="sm"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </RefrigerationIconButton>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function Feedback({ tone, children }: { tone: "error" | "success"; children: React.ReactNode }) {
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={
        tone === "error"
          ? "flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
          : "flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200"
      }
    >
      {tone === "error" ? (
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      ) : (
        <Check className="h-4 w-4 shrink-0" />
      )}
      {children}
    </p>
  );
}

function repositoryErrorMessage(error: { code: string; issues?: Array<{ message: string }> }): string {
  if (error.code === "LAYOUT_VERSION_CONFLICT") {
    return "Схему вже змінив інший оператор. Оновіть сторінку та повторіть дію.";
  }
  if (error.code === "LAYOUT_VALIDATION_FAILED") {
    return error.issues?.map((issue) => issue.message).join(" ") || "Схема не пройшла перевірку.";
  }
  return "Операцію зі схемою обладнання не виконано.";
}
