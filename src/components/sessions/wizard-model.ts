import type { SessionStageType } from "@/lib/sessions/types";
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
  productionBindings: boolean;
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
    productionBindings: true,
    stages: DEFAULT_STAGES.map((stage) => ({ ...stage })),
  };
}

export function isWizardStepValid(step: number, form: SessionWizardForm): boolean {
  const required = (value: string) => value.trim().length > 0;
  if (step === 0) {
    return required(form.sessionNumber) && required(form.title) && required(form.customer);
  }
  if (step === 1) {
    return required(form.testObject) && required(form.model) && required(form.serialNumber);
  }
  if (step === 2) return required(form.standard) && required(form.method);
  if (step === 3) return form.productionBindings;
  if (step === 4) return form.samplingSeconds >= 1 && form.samplingSeconds <= 3600;
  if (step === 5) {
    return form.temperatureLower <= form.temperatureUpper && form.powerUpper > 0;
  }
  if (step === 6) {
    return form.stages.length > 0 && form.stages.every((stage) => required(stage.name));
  }
  return true;
}
