import type { LimitRuleInput, SessionCommandInput, SessionStageType, TelemetryQuality } from "./types";

export interface ProductionBindingsInput extends SessionCommandInput {
  binding_metadata?: Record<string, unknown>;
}

export interface LimitSetInput extends SessionCommandInput {
  limits: LimitRuleInput[];
}

export interface StageAdvanceInput extends SessionCommandInput {
  sequence_index: number;
  stage_type: SessionStageType;
  name: string;
  description?: string | null;
  planned_duration_seconds?: number | null;
}

export interface SessionNoteInput extends SessionCommandInput {
  stage_id?: string | null;
  body: string;
}

export interface SessionTelemetryQuery {
  stage_id?: string;
  node_id?: string;
  equipment_id?: string;
  channel_id?: string;
  metric?: string;
  quality?: TelemetryQuality;
  alarm?: string;
  limit?: number;
  offset?: number;
}

export interface SessionHistoryQuery extends SessionTelemetryQuery {
  from: string | Date;
  to: string | Date;
}

export interface SessionWizardStagePlan {
  sequence_index: number;
  stage_type: SessionStageType;
  name: string;
  planned_duration_minutes: number;
}
