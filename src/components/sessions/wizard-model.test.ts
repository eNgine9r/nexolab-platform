import { expect, it } from "vitest";
import {
  createInitialWizardForm,
  getWizardInvalidStep,
  isWizardBindingValid,
  isWizardStepValid,
} from "./wizard-model";
import type { SessionBindingOption } from "@/lib/sessions/types";
function complete() {
  return {
    ...createInitialWizardForm(),
    customer: "Customer",
    model: "Model",
    serialNumber: "Serial",
    selectedTelemetryKeys: ["probe"],
  };
}
it.each([
  { temperatureHysteresis: -1 },
  { temperatureDurationSeconds: -1 },
  { temperatureDurationSeconds: 1.5 },
  { temperatureLower: 10, temperatureUpper: 8 },
  { powerUpper: Infinity },
])("rejects backend-invalid limits before creation: %j", (values) => {
  const form = { ...complete(), ...values };
  expect(isWizardStepValid(5, form)).toBe(false);
  expect(getWizardInvalidStep(form)).toBe(5);
});
it("permits zero hysteresis/duration and the existing valid configuration", () => {
  expect(
    getWizardInvalidStep({ ...complete(), temperatureHysteresis: 0, temperatureDurationSeconds: 0 }),
  ).toBeNull();
});
it("uses the existing server text bounds, counting Unicode code points", () => {
  expect(getWizardInvalidStep({ ...complete(), sessionNumber: "x".repeat(65) })).toBe(0);
  expect(getWizardInvalidStep({ ...complete(), sessionNumber: "😀".repeat(64) })).toBeNull();
});
it("rejects nonfinite sampling and invalid stage plans", () => {
  expect(getWizardInvalidStep({ ...complete(), samplingSeconds: NaN })).toBe(4);
  const form = complete();
  form.stages[0]!.planned_duration_minutes = -1;
  expect(getWizardInvalidStep(form)).toBe(6);
});
it("checks the resolved binding payload against existing API bounds", () => {
  const binding: SessionBindingOption = {
    node_id: "edge-01",
    equipment_id: "K106",
    channel_id: "106-03",
    metric: "temperature.probe",
    unit: "degC",
    device_type: "sensor",
    profile_version: "v1",
    register_key: "probe",
    register_address: 1,
  };
  expect(isWizardBindingValid(binding)).toBe(true);
  expect(isWizardBindingValid({ ...binding, channel_id: "x".repeat(129) })).toBe(false);
  expect(isWizardBindingValid({ ...binding, unit: "x".repeat(33) })).toBe(false);
});

it("respects the existing stage-name storage bound", () => {
  const form = complete();
  form.stages[0]!.name = "x".repeat(128);
  expect(getWizardInvalidStep(form)).toBeNull();
  form.stages[0]!.name = "x".repeat(129);
  expect(getWizardInvalidStep(form)).toBe(6);
});
