import { beforeEach, expect, it } from "vitest";
import { createInitialWizardForm } from "./wizard-model";
import {
  clearWizardDraft,
  readWizardDraft,
  saveWizardDraft,
  wizardDraftKey,
  type WizardDraft,
} from "./session-wizard-draft";
const key = wizardDraftKey("operator-a", "org-a");
function draft(): WizardDraft {
  const form = createInitialWizardForm();
  return {
    form,
    step: 3,
    operation: {
      sessionId: null,
      selectionKeys: null,
      createKey: "create-1",
      limitsKey: "limits-1",
      bindingKeys: new Map(),
      formSnapshot: null,
    },
  };
}
beforeEach(() => localStorage.clear());
it("restores an unfinished form and its current step", () => {
  const value = draft();
  value.form.customer = "Laboratory customer";
  expect(saveWizardDraft(key, value)).toBe(true);
  expect(readWizardDraft(key)).toEqual(value);
});
it("restores the exact operation keys and frozen submitted payload after a partial server commit", () => {
  const value = draft();
  value.operation.sessionId = "existing-draft";
  value.operation.selectionKeys = ["probe"];
  value.operation.formSnapshot = structuredClone(value.form);
  value.operation.bindingKeys.set("binding", "binding-key");
  saveWizardDraft(key, value);
  const recovered = readWizardDraft(key)!;
  expect(recovered.step).toBe(7);
  expect(recovered.operation).toEqual(value.operation);
});
it("isolates drafts by verified user and organization", () => {
  saveWizardDraft(key, draft());
  expect(readWizardDraft(wizardDraftKey("operator-b", "org-a"))).toBeNull();
  expect(readWizardDraft(wizardDraftKey("operator-a", "org-b"))).toBeNull();
});
it.each(["{}", '{"version":2}', "broken"])("ignores malformed storage %s", (raw) => {
  localStorage.setItem(key, raw);
  expect(readWizardDraft(key)).toBeNull();
});
it("clears successful creation without touching another operator draft", () => {
  const other = wizardDraftKey("operator-b", "org-a");
  saveWizardDraft(key, draft());
  saveWizardDraft(other, draft());
  expect(clearWizardDraft(key)).toBe(true);
  expect(readWizardDraft(key)).toBeNull();
  expect(readWizardDraft(other)).not.toBeNull();
});
