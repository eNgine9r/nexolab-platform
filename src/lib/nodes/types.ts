export type NodeLifecycleState = "pending" | "active" | "suspended" | "revoked";
export type NodeClockStatus = "unknown" | "ok" | "warning" | "critical";
export type NodeAvailability = "online" | "offline" | "stale" | "unknown";
export type NodeHealthState = "healthy" | "degraded";
export type BrokerControlOperation = "provision" | "rotate" | "enable" | "disable" | "delete";
export type BrokerControlState = "pending" | "processing" | "retrying" | "applied" | "failed";
export type BrokerDesiredState = "provisioned" | "enabled" | "disabled" | "deleted";
export type BrokerSynchronizationState =
  "disabled" | "unknown" | "pending" | "processing" | "retrying" | "applied" | "failed" | "out_of_sync";

export type CentralNode = {
  id: string;
  organization_id: string;
  node_id: string;
  display_name: string;
  state: NodeLifecycleState;
  state_reason: string | null;
  clock_warning_ms: number;
  clock_critical_ms: number;
  last_seen_at: string | null;
  last_clock_offset_ms: number | null;
  clock_status: NodeClockStatus;
  clock_observed_at: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  current_credential: NodeCredential | null;
};

export type NodeCredential = {
  id: string;
  node_record_id: string;
  generation: number;
  secret_fingerprint: string;
  issued_by: string;
  issued_at: string;
  revoked_at: string | null;
};

export type NodeHealth = {
  id: string;
  event_id: string;
  node_record_id: string;
  node_sequence: number;
  health: NodeHealthState;
  uptime_seconds: number;
  queue_depth: number;
  samples_total: number;
  software_version: string;
  device_mode: string;
  last_sample_at: string | null;
  last_publish_at: string | null;
  last_error: string | null;
  captured_at: string;
  received_at: string;
  inserted_at: string;
};

export type NodeStatus = {
  id: string;
  event_id: string;
  node_record_id: string;
  node_sequence: number;
  status: "online" | "offline";
  reason: string;
  software_version: string | null;
  graceful: boolean;
  captured_at: string;
  received_at: string;
  inserted_at: string;
};

export type NodeOperationalState = {
  node_id: string;
  availability: NodeAvailability;
  stale_after_seconds: number;
  heartbeat_age_seconds: number | null;
  degraded_reason: string | null;
  latest_health: NodeHealth | null;
  latest_status: NodeStatus | null;
};

export type BrokerControlCommand = {
  id: string;
  operation: BrokerControlOperation;
  state: BrokerControlState;
  attempts: number;
  available_at: string;
  last_attempt_at: string | null;
  applied_at: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
};

export type NodeBrokerControl = {
  node_id: string;
  lifecycle_state: NodeLifecycleState;
  enabled: boolean;
  desired_state: BrokerDesiredState;
  synchronization: BrokerSynchronizationState;
  synchronized: boolean;
  latest_command: BrokerControlCommand | null;
  commands: BrokerControlCommand[];
};

export type ProvisionNodeResponse = {
  node: CentralNode;
  credential: NodeCredential;
  provisioning_secret: string | null;
  replayed: boolean;
};

export type RotateNodeCredentialResponse = ProvisionNodeResponse;
