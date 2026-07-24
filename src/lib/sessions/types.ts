export type SessionState =
  | "draft"
  | "ready"
  | "running"
  | "paused"
  | "completed"
  | "cancelled"
  | "archived";

export type SessionAction =
  | "prepare"
  | "start"
  | "pause"
  | "resume"
  | "complete"
  | "cancel"
  | "archive";

export type SessionStageType =
  | "preparation"
  | "preconditioning"
  | "stabilization"
  | "main_test"
  | "defrost"
  | "recovery"
  | "completion"
  | "report";

export interface LaboratorySession {
  id: string;
  session_number: string;
  node_id: string;
  state: SessionState;
  title: string;
  customer: string | null;
  test_object: string;
  model: string | null;
  serial_number: string | null;
  standard: string | null;
  method: string | null;
  operator_id: string | null;
  responsible_engineer_id: string | null;
  metadata_payload: Record<string, unknown>;
  current_stage_id: string | null;
  active_config_snapshot_id: string | null;
  active_limit_version: number | null;
  lock_version: number;
  prepared_at: string | null;
  started_at: string | null;
  paused_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionEvent {
  id: string;
  session_id: string;
  event_type: string;
  previous_state: SessionState | null;
  next_state: SessionState | null;
  actor_id: string;
  actor_source: string;
  reason: string | null;
  payload: Record<string, unknown>;
  idempotency_key: string;
  occurred_at: string;
  inserted_at: string;
}

export interface SessionPage {
  items: LaboratorySession[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface SessionEventPage {
  items: SessionEvent[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface SessionMutationResponse {
  session: LaboratorySession;
  event: SessionEvent;
  replayed: boolean;
}

export interface SessionBinding {
  id: string;
  session_id: string;
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: string;
  unit: string | null;
  binding_metadata: Record<string, unknown>;
  activated_at: string | null;
  released_at: string | null;
  created_at: string;
}

export interface SessionLimit {
  id: string;
  session_id: string;
  binding_id: string | null;
  config_snapshot_id: string | null;
  supersedes_limit_id: string | null;
  metric: string;
  unit: string;
  version: number;
  lower_limit: number | null;
  upper_limit: number | null;
  hysteresis: number | null;
  duration_seconds: number | null;
  payload: Record<string, unknown>;
  created_by: string;
  effective_at: string;
  created_at: string;
}

export interface SessionConfigSnapshot {
  id: string;
  session_id: string;
  version: number;
  source: string;
  payload: Record<string, unknown>;
  content_sha256: string;
  created_by: string;
  captured_at: string;
  created_at: string;
}

export interface SessionConfiguration {
  session: LaboratorySession;
  bindings: SessionBinding[];
  active_limits: SessionLimit[];
  active_snapshot: SessionConfigSnapshot | null;
  snapshots: SessionConfigSnapshot[];
}

export interface ProductionBindingsResponse {
  bindings: SessionBinding[];
  event: SessionEvent;
  replayed: boolean;
  active_config_snapshot_id: string | null;
  expected_series_count: number;
}

export interface LimitSetMutationResponse {
  version: number;
  limits: SessionLimit[];
  event: SessionEvent;
  replayed: boolean;
  active_config_snapshot_id: string | null;
}

export interface SessionStage {
  id: string;
  session_id: string;
  sequence_index: number;
  stage_type: SessionStageType;
  name: string;
  description: string | null;
  planned_duration_seconds: number | null;
  entered_at: string | null;
  exited_at: string | null;
  created_at: string;
}

export interface SessionStageTransition {
  id: string;
  session_id: string;
  session_event_id: string;
  from_stage_id: string | null;
  to_stage_id: string;
  from_sequence_index: number | null;
  to_sequence_index: number;
  actor_id: string;
  reason: string | null;
  occurred_at: string;
  inserted_at: string;
}

export interface StageAdvanceResponse {
  stage: SessionStage;
  transition: SessionStageTransition;
  event: SessionEvent;
  replayed: boolean;
}

export interface SessionNote {
  id: string;
  session_id: string;
  stage_id: string | null;
  author_id: string;
  body: string;
  created_at: string;
}

export interface SessionNoteResponse {
  note: SessionNote;
  event: SessionEvent;
  replayed: boolean;
}

export interface SessionNotesPage {
  items: SessionNote[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface AuditLogEntry {
  id: string;
  session_id: string | null;
  session_event_id: string | null;
  actor_id: string;
  actor_source: string;
  action: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  inserted_at: string;
}

export interface SessionAuditPage {
  items: AuditLogEntry[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export type TelemetryQuality =
  | "valid"
  | "stale"
  | "sensor_missing"
  | "sensor_fault"
  | "communication_error"
  | "invalid_range"
  | "unmapped"
  | "estimated";

export interface AttributedTelemetrySample {
  event_id: string;
  node_id: string;
  captured_at: string;
  metric: string;
  value: number | null;
  unit: string;
  quality: TelemetryQuality;
  source: string;
  equipment_id: string;
  channel_id: string;
  alarm: string | null;
  raw_value: number | null;
  raw_status: number | null;
  received_at: string;
  session_id: string;
  stage_id: string | null;
  binding_id: string;
  config_snapshot_id: string;
  resolver_version: string;
}

export interface AttributedTelemetryCollection {
  items: AttributedTelemetrySample[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface SessionCreateInput {
  session_number: string;
  title: string;
  test_object: string;
  node_id: string;
  customer?: string | null;
  model?: string | null;
  serial_number?: string | null;
  standard?: string | null;
  method?: string | null;
  operator_id?: string | null;
  responsible_engineer_id?: string | null;
  metadata_payload: Record<string, unknown>;
  actor_id: string;
  actor_source: string;
  occurred_at: string;
  reason?: string | null;
}

export interface LimitRuleInput {
  binding_id?: string | null;
  metric: string;
  unit: string;
  lower_limit?: number | null;
  upper_limit?: number | null;
  hysteresis?: number | null;
  duration_seconds?: number | null;
  payload?: Record<string, unknown>;
}

export interface SessionCommandInput {
  actor_id: string;
  actor_source: string;
  occurred_at: string;
  reason?: string | null;
}
