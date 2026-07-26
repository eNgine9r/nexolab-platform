export interface ReportArtifact {
  id: string;
  report_id: string;
  name: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  row_count: number | null;
  created_at: string;
}

export interface TestReport {
  id: string;
  organization_id: string;
  session_id: string;
  config_snapshot_id: string;
  version: number;
  session_state: "completed" | "archived";
  source_started_at: string;
  source_ended_at: string;
  source_sha256: string;
  manifest_sha256: string;
  generator_version: string;
  generated_by: string;
  generated_at: string;
  created_at: string;
  artifacts: ReportArtifact[];
}

export interface ReportGenerationResponse extends TestReport {
  replayed: boolean;
}

export interface ReportPage {
  items: TestReport[];
  count: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export type ReportRenderFormat = "xlsx" | "pdf";
export type ReportApprovalStatus = "generated" | "approved" | "superseded";
export type ReportApprovalDecision = "approve" | "replay" | "supersede";

export interface ReportRender {
  id: string;
  report_id: string;
  organization_id: string;
  format: ReportRenderFormat;
  artifact_name: string;
  media_type: string;
  renderer_version: string;
  manifest_sha256: string;
  sha256: string;
  size_bytes: number;
  rendered_by: string;
  rendered_at: string;
  created_at: string;
}

export interface ReportRenderResponse extends ReportRender {
  replayed: boolean;
}

export interface ReportApprovalState {
  state: ReportApprovalStatus;
  manifest_sha256: string;
  approved_by: string | null;
  approved_at: string | null;
  approval_reason: string | null;
  approval_idempotency_key: string | null;
  approval_command_sha256: string | null;
  superseded_by_report_id: string | null;
  superseded_at: string | null;
}

export interface ReportOutputState {
  report_id: string;
  approval: ReportApprovalState;
  renders: ReportRender[];
}

export interface ReportApprovalActionResponse {
  event_id: string;
  decision: ReportApprovalDecision;
  approval: ReportApprovalState;
}

export interface ReportDownload {
  blob: Blob;
  filename: string;
  mediaType: string;
  sha256: string | null;
  manifestSha256?: string | null;
}
