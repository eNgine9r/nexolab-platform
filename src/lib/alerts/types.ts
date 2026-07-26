export type AlertSeverity = "information" | "warning" | "alarm" | "critical" | "system";

export type AlertState = "active" | "acknowledged" | "resolved" | "closed";

export interface AlertInstance {
  id: string;
  organization_id: string;
  rule_id: string;
  rule_version_id: string;
  resource_key: string;
  node_id: string;
  equipment_id: string;
  channel_id: string;
  metric: string;
  state: AlertState;
  severity: AlertSeverity;
  trigger_value: number | null;
  trigger_threshold: number | null;
  clear_threshold: number | null;
  maximum_deviation: number;
  first_event_id: string;
  last_event_id: string;
  session_id: string | null;
  stage_id: string | null;
  binding_id: string | null;
  context: Record<string, unknown>;
  triggered_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
}

export interface AlertPage {
  items: AlertInstance[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface AlertTransition {
  id: string;
  alert_id: string;
  event_type: string;
  previous_state: AlertState | null;
  next_state: AlertState;
  actor_id: string;
  actor_source: string;
  reason: string | null;
  idempotency_key: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  inserted_at: string;
}

export interface AlertTransitionPage {
  items: AlertTransition[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface AlertLifecycleResponse {
  alert: AlertInstance;
  transition: AlertTransition;
  replayed: boolean;
}
