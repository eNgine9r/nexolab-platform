import type { SessionBindingOption } from "@/lib/sessions/types";
import { createInitialWizardForm, STAGE_TYPES, type SessionWizardForm } from "./wizard-model";

export type WizardOperation = {
  bindingSnapshot: SessionBindingOption[] | null;
  sessionId: string | null;
  selectionKeys: string[] | null;
  createKey: string;
  bindingKeys: Map<string, string>;
  limitsKey: string;
  formSnapshot: SessionWizardForm | null;
};
export type WizardDraft = { form: SessionWizardForm; step: number; operation: WizardOperation };
export function wizardDraftKey(identity: string, organization: string) {
  return `nexolab.sessionWizardDraft.v1:${encodeURIComponent(identity)}:${encodeURIComponent(organization)}`;
}
function validForm(value: unknown): value is SessionWizardForm {
  if (!value || typeof value !== "object") return false;
  const form = value as SessionWizardForm;
  const defaults = createInitialWizardForm();
  return (
    Object.entries(defaults).every(([key, initial]) => {
      const current = form[key as keyof SessionWizardForm];
      if (typeof initial === "string") return typeof current === "string";
      if (typeof initial === "number") return typeof current === "number" && Number.isFinite(current);
      return true;
    }) &&
    Array.isArray(form.selectedTelemetryKeys) &&
    form.selectedTelemetryKeys.every((key) => typeof key === "string") &&
    Array.isArray(form.stages) &&
    form.stages.every(
      (stage) =>
        stage &&
        typeof stage.name === "string" &&
        STAGE_TYPES.includes(stage.stage_type) &&
        Number.isInteger(stage.sequence_index) &&
        (stage.planned_duration_minutes === null || Number.isFinite(stage.planned_duration_minutes)),
    )
  );
}
export function readWizardDraft(key: string | null): WizardDraft | null {
  if (!key || typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw || raw.length > 100000) return null;
    const data = JSON.parse(raw);
    const op = data.operation;
    if (
      data.version !== 1 ||
      !validForm(data.form) ||
      !Number.isInteger(data.step) ||
      data.step < 0 ||
      data.step > 7 ||
      !op ||
      typeof op.createKey !== "string" ||
      typeof op.limitsKey !== "string" ||
      !(op.sessionId === null || typeof op.sessionId === "string") ||
      !(
        op.selectionKeys === null ||
        (Array.isArray(op.selectionKeys) && op.selectionKeys.every((x: unknown) => typeof x === "string"))
      ) ||
      !(op.formSnapshot === null || validForm(op.formSnapshot)) ||
      !(
        op.bindingSnapshot == null ||
        (Array.isArray(op.bindingSnapshot) &&
          op.bindingSnapshot.length > 0 &&
          op.bindingSnapshot.every(
            (binding: Record<string, unknown>) =>
              binding &&
              ["node_id", "equipment_id", "channel_id", "metric", "unit"].every(
                (key) => typeof binding[key] === "string",
              ),
          ))
      ) ||
      !Array.isArray(op.bindingKeys) ||
      !op.bindingKeys.every(
        (x: unknown) => Array.isArray(x) && x.length === 2 && x.every((v) => typeof v === "string"),
      )
    )
      return null;
    return {
      form: op.formSnapshot ?? data.form,
      step: op.formSnapshot ? 7 : data.step,
      operation: { ...op, bindingSnapshot: op.bindingSnapshot ?? null, bindingKeys: new Map(op.bindingKeys) },
    };
  } catch {
    return null;
  }
}
export function saveWizardDraft(key: string | null, draft: WizardDraft): boolean {
  if (!key) return true;
  try {
    window.localStorage.setItem(
      key,
      JSON.stringify({
        version: 1,
        form: draft.form,
        step: draft.step,
        operation: { ...draft.operation, bindingKeys: [...draft.operation.bindingKeys] },
      }),
    );
    return true;
  } catch {
    return false;
  }
}
export function clearWizardDraft(key: string | null): boolean {
  if (!key) return true;
  try {
    window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
