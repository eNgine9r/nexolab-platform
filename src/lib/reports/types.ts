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

export interface ReportDownload {
  blob: Blob;
  filename: string;
  mediaType: string;
  sha256: string | null;
}
