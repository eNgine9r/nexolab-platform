import type { SessionBindingOption, SessionStageType } from "@/lib/sessions/types";
import type { SessionWizardStagePlan } from "@/lib/sessions/inputs";

export const WIZARD_STEPS = [
  "Загальна інформація",
  "Об’єкт",
  "Стандарт і метод",
  "Обладнання",
  "Sampling policy",
  "Допуски",
  "Етапи",
  "Перевірка",
] as const;

export const STAGE_TYPES: SessionStageType[] = [
  "preparation",
  "preconditioning",
  "stabilization",
  "main_test",
  "defrost",
  "recovery",
  "completion",
  "report",
];

export interface SessionWizardForm {
  sessionNumber: string;
  title: string;
  customer: string;
  testObject: string;
  model: string;
  serialNumber: string;
  standard: string;
  method: string;
  operatorId: string;
  engineerId: string;
  samplingSeconds: number;
  temperatureLower: number;
  temperatureUpper: number;
  temperatureHysteresis: number;
  temperatureDurationSeconds: number;
  powerUpper: number;
  selectedTelemetryKeys: string[];
  stages: SessionWizardStagePlan[];
}

const DEFAULT_STAGES: SessionWizardStagePlan[] = [
  {
    sequence_index: 0,
    stage_type: "preparation",
    name: "Підготовка",
    planned_duration_minutes: 30,
  },
  {
    sequence_index: 1,
    stage_type: "preconditioning",
    name: "Попереднє кондиціонування",
    planned_duration_minutes: 60,
  },
  {
    sequence_index: 2,
    stage_type: "stabilization",
    name: "Стабілізація",
    planned_duration_minutes: 120,
  },
  {
    sequence_index: 3,
    stage_type: "main_test",
    name: "Основне випробування",
    planned_duration_minutes: 480,
  },
  {
    sequence_index: 4,
    stage_type: "completion",
    name: "Завершення",
    planned_duration_minutes: 30,
  },
];

export function createInitialWizardForm(): SessionWizardForm {
  return {
    sessionNumber: `NXL-${new Date().getFullYear()}-${String(Date.now()).slice(-6)}`,
    title: "ISO 23953 — випробування холодильної вітрини",
    customer: "",
    testObject: "Холодильна вітрина",
    model: "",
    serialNumber: "",
    standard: "ISO 23953",
    method: "Temperature performance and energy measurement",
    operatorId: "dashboard-operator",
    engineerId: "laboratory-engineer",
    samplingSeconds: 10,
    temperatureLower: -5,
    temperatureUpper: 8,
    temperatureHysteresis: 0.5,
    temperatureDurationSeconds: 60,
    powerUpper: 3500,
    selectedTelemetryKeys: [],
    stages: DEFAULT_STAGES.map((stage) => ({ ...stage })),
  };
}

export function isWizardStepValid(step: number, form: SessionWizardForm): boolean {
  const bounded = (value: string, max: number, required = false) =>
    typeof value === "string" && [...value.trim()].length <= max && (!required || value.trim().length > 0);
  if (step === 0)
    return (
      bounded(form.sessionNumber, 64, true) &&
      bounded(form.title, 256, true) &&
      bounded(form.customer, 256, true) &&
      bounded(form.operatorId, 128) &&
      bounded(form.engineerId, 128)
    );
  if (step === 1)
    return (
      bounded(form.testObject, 256, true) &&
      bounded(form.model, 128, true) &&
      bounded(form.serialNumber, 128, true)
    );
  if (step === 2) return bounded(form.standard, 256, true) && bounded(form.method, 256, true);
  if (step === 3) return form.selectedTelemetryKeys.length > 0;
  if (step === 4)
    return Number.isFinite(form.samplingSeconds) && form.samplingSeconds >= 1 && form.samplingSeconds <= 3600;
  if (step === 5)
    return (
      [
        form.temperatureLower,
        form.temperatureUpper,
        form.temperatureHysteresis,
        form.temperatureDurationSeconds,
        form.powerUpper,
      ].every(Number.isFinite) &&
      form.temperatureLower <= form.temperatureUpper &&
      form.powerUpper > 0 &&
      form.temperatureHysteresis >= 0 &&
      form.temperatureDurationSeconds >= 0 &&
      Number.isInteger(form.temperatureDurationSeconds)
    );
  if (step === 6)
    return (
      form.stages.length > 0 &&
      new Set(form.stages.map((stage) => stage.sequence_index)).size === form.stages.length &&
      form.stages.every(
        (stage) =>
          bounded(stage.name, 128, true) &&
          STAGE_TYPES.includes(stage.stage_type) &&
          Number.isInteger(stage.sequence_index) &&
          stage.sequence_index >= 0 &&
          Number.isFinite(stage.planned_duration_minutes) &&
          stage.planned_duration_minutes >= 0,
      )
    );
  return true;
}
export function getWizardInvalidStep(form: SessionWizardForm): number | null {
  for (let step = 0; step < 7; step++) if (!isWizardStepValid(step, form)) return step;
  return null;
}
export function isWizardBindingValid(binding: SessionBindingOption): boolean {
  return (
    [binding.node_id, binding.equipment_id, binding.channel_id, binding.metric].every(
      (value) => typeof value === "string" && value.trim().length > 0 && [...value].length <= 128,
    ) &&
    typeof binding.unit === "string" &&
    [...binding.unit].length <= 32
  );
}
