export type NodeLifecycleState = "pending" | "active" | "suspended" | "revoked";
export type NodeClockStatus = "unknown" | "ok" | "warning" | "critical";

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

export type ProvisionNodeResponse = {
  node: CentralNode;
  credential: NodeCredential;
  provisioning_secret: string | null;
  replayed: boolean;
};

export type RotateNodeCredentialResponse = ProvisionNodeResponse;
