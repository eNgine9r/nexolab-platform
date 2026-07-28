\set ON_ERROR_STOP on

INSERT INTO test_sessions (
  id, organization_id, create_idempotency_key, session_number, node_id, state,
  title, customer, test_object, model, serial_number, standard, method,
  operator_id, responsible_engineer_id, metadata_payload, started_at,
  completed_at, created_at, updated_at
) VALUES (
  '40000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  'dr-session-create-v1',
  'NX-DR-0001',
  'edge-01',
  'completed',
  'Disaster recovery completed session',
  'NEXOLAB acceptance',
  'K106 refrigerated display cabinet',
  'DR-FIXTURE',
  'DR-0001',
  'ISO 23953',
  'temperature distribution',
  'dr-operator',
  'dr-engineer',
  '{"immutable":true,"recovery_fixture":true}'::jsonb,
  '2026-07-28T07:00:00Z',
  '2026-07-28T08:00:00Z',
  '2026-07-28T06:55:00Z',
  '2026-07-28T08:00:00Z'
);

INSERT INTO session_config_snapshots (
  id, session_id, version, source, payload, content_sha256, created_by,
  captured_at, created_at
) VALUES (
  '41000000-0000-0000-0000-000000000099',
  '40000000-0000-0000-0000-000000000099',
  1,
  'session_start',
  '{"channels":["106-03"],"sample_interval_seconds":10}'::jsonb,
  'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  'dr-engineer',
  '2026-07-28T07:00:00Z',
  '2026-07-28T07:00:00Z'
);

UPDATE test_sessions
SET active_config_snapshot_id = '41000000-0000-0000-0000-000000000099'
WHERE id = '40000000-0000-0000-0000-000000000099';

INSERT INTO session_stages (
  id, session_id, sequence_index, stage_type, name, description,
  planned_duration_seconds, entered_at, exited_at, created_at
) VALUES (
  '42000000-0000-0000-0000-000000000099',
  '40000000-0000-0000-0000-000000000099',
  0,
  'main_test',
  'Main Test',
  'Protected recovery stage fixture',
  3600,
  '2026-07-28T07:00:00Z',
  '2026-07-28T08:00:00Z',
  '2026-07-28T07:00:00Z'
);

INSERT INTO alert_rules (
  id, organization_id, name, description, enabled, severity, node_id,
  equipment_id, channel_id, metric, session_id, current_version, created_by,
  created_at, updated_at
) VALUES (
  '50000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  'DR high temperature',
  'Protected alert rule fixture',
  true,
  'warning',
  'edge-01',
  'K106',
  '106-03',
  'temperature.probe',
  '40000000-0000-0000-0000-000000000099',
  1,
  'dr-engineer',
  '2026-07-28T07:00:00Z',
  '2026-07-28T08:00:00Z'
);

INSERT INTO alert_rule_versions (
  id, rule_id, version, condition, trigger_threshold, clear_threshold,
  minimum_duration_seconds, clear_duration_seconds, debounce_seconds,
  cooldown_seconds, configuration, created_by, created_at
) VALUES (
  '51000000-0000-0000-0000-000000000099',
  '50000000-0000-0000-0000-000000000099',
  1,
  'threshold_high',
  8.0,
  7.0,
  60,
  30,
  0,
  120,
  '{"standard":"ISO 23953"}'::jsonb,
  'dr-engineer',
  '2026-07-28T07:00:00Z'
);

INSERT INTO alert_instances (
  id, organization_id, rule_id, rule_version_id, resource_key, node_id,
  equipment_id, channel_id, metric, state, severity, trigger_value,
  trigger_threshold, clear_threshold, maximum_deviation, first_event_id,
  last_event_id, session_id, stage_id, binding_id, context, triggered_at,
  acknowledged_at, resolved_at, closed_at, lock_version, created_at, updated_at
) VALUES (
  '52000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  '50000000-0000-0000-0000-000000000099',
  '51000000-0000-0000-0000-000000000099',
  'edge-01|K106|106-03|temperature.probe',
  'edge-01',
  'K106',
  '106-03',
  'temperature.probe',
  'closed',
  'warning',
  8.5,
  8.0,
  7.0,
  1.2,
  '20000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000099',
  '42000000-0000-0000-0000-000000000099',
  NULL,
  '{"recovery_fixture":true}'::jsonb,
  '2026-07-28T07:10:00Z',
  '2026-07-28T07:11:00Z',
  '2026-07-28T07:20:00Z',
  '2026-07-28T07:21:00Z',
  4,
  '2026-07-28T07:10:00Z',
  '2026-07-28T07:21:00Z'
);

INSERT INTO alert_transitions (
  id, alert_id, event_type, previous_state, next_state, actor_id,
  actor_source, reason, idempotency_key, payload, occurred_at, inserted_at
) VALUES (
  '53000000-0000-0000-0000-000000000099',
  '52000000-0000-0000-0000-000000000099',
  'alert_closed',
  'resolved',
  'closed',
  'dr-engineer',
  'disaster-recovery-acceptance',
  'Recovery fixture finalized',
  'dr-alert-close-v1',
  '{"immutable":true}'::jsonb,
  '2026-07-28T07:21:00Z',
  '2026-07-28T07:21:01Z'
);

INSERT INTO test_report_versions (
  id, organization_id, session_id, config_snapshot_id, version,
  idempotency_key, session_state, source_started_at, source_ended_at,
  source_snapshot, source_sha256, manifest_sha256, generator_version,
  generated_by, generated_at, created_at
) VALUES (
  '60000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  '40000000-0000-0000-0000-000000000099',
  '41000000-0000-0000-0000-000000000099',
  1,
  'dr-report-v1',
  'completed',
  '2026-07-28T07:00:00Z',
  '2026-07-28T08:00:00Z',
  '{"session_number":"NX-DR-0001","immutable":true}'::jsonb,
  'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
  'dr-renderer-v1',
  'dr-engineer',
  '2026-07-28T08:01:00Z',
  '2026-07-28T08:01:00Z'
);

INSERT INTO test_report_artifacts (
  id, report_id, name, media_type, sha256, size_bytes, row_count, content,
  created_at
) VALUES (
  '61000000-0000-0000-0000-000000000099',
  '60000000-0000-0000-0000-000000000099',
  'protocol-proof.bin',
  'application/octet-stream',
  '8891e05dd3204700089d03971479cfd3725e5127ba5530fa5785d0f2824cd0dd',
  7,
  1,
  decode('4e45584f4c4142', 'hex'),
  '2026-07-28T08:01:00Z'
);

INSERT INTO central_nodes (
  id, organization_id, node_id, display_name, state, state_reason,
  clock_warning_ms, clock_critical_ms, last_seen_at, last_clock_offset_ms,
  clock_status, clock_observed_at, created_by, created_at, updated_at
) VALUES
  (
    '70000000-0000-0000-0000-000000000091',
    '00000000-0000-0000-0000-000000000099',
    'edge-01',
    'DR Edge 01',
    'active',
    'restorable active node',
    30000,
    120000,
    '2026-07-28T07:59:00Z',
    12,
    'ok',
    '2026-07-28T07:59:00Z',
    'dr-engineer',
    '2026-07-28T06:00:00Z',
    '2026-07-28T07:59:00Z'
  ),
  (
    '70000000-0000-0000-0000-000000000092',
    '00000000-0000-0000-0000-000000000099',
    'edge-02',
    'DR Edge 02',
    'suspended',
    'disabled identity recovery fixture',
    30000,
    120000,
    '2026-07-28T07:58:00Z',
    18,
    'ok',
    '2026-07-28T07:58:00Z',
    'dr-engineer',
    '2026-07-28T06:00:00Z',
    '2026-07-28T07:58:00Z'
  );

INSERT INTO central_node_credentials (
  id, organization_id, node_record_id, generation, secret_salt,
  secret_hash, secret_fingerprint, idempotency_key, command_sha256,
  issued_by, issued_at, revoked_at, revoked_by, revocation_reason
) VALUES
  (
    '71000000-0000-0000-0000-000000000091',
    '00000000-0000-0000-0000-000000000099',
    '70000000-0000-0000-0000-000000000091',
    2,
    '1111111111111111111111111111111111111111111111111111111111111111',
    '2222222222222222222222222222222222222222222222222222222222222222',
    '2222222222222222',
    'dr-edge-01-credential-v2',
    '3333333333333333333333333333333333333333333333333333333333333333',
    'dr-engineer',
    '2026-07-28T06:30:00Z',
    NULL,
    NULL,
    NULL
  ),
  (
    '71000000-0000-0000-0000-000000000092',
    '00000000-0000-0000-0000-000000000099',
    '70000000-0000-0000-0000-000000000092',
    1,
    '4444444444444444444444444444444444444444444444444444444444444444',
    '5555555555555555555555555555555555555555555555555555555555555555',
    '5555555555555555',
    'dr-edge-02-credential-v1',
    '6666666666666666666666666666666666666666666666666666666666666666',
    'dr-engineer',
    '2026-07-28T06:30:00Z',
    NULL,
    NULL,
    NULL
  );

INSERT INTO central_node_broker_commands (
  id, organization_id, node_record_id, node_id, credential_id, operation,
  state, deduplication_key, command_sha256, secret_ciphertext, secret_nonce,
  secret_key_id, attempts, available_at, locked_at, last_attempt_at,
  applied_at, failed_at, error_code, error_detail, created_at, updated_at
) VALUES (
  '72000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  '70000000-0000-0000-0000-000000000092',
  'edge-02',
  '71000000-0000-0000-0000-000000000092',
  'disable',
  'applied',
  'dr-disable-edge-02-v1',
  '7777777777777777777777777777777777777777777777777777777777777777',
  NULL,
  NULL,
  NULL,
  1,
  '2026-07-28T06:40:00Z',
  NULL,
  '2026-07-28T06:40:01Z',
  '2026-07-28T06:40:02Z',
  NULL,
  NULL,
  NULL,
  '2026-07-28T06:40:00Z',
  '2026-07-28T06:40:02Z'
);

INSERT INTO equipment_images (
  id, organization_id, equipment_id, storage_key, original_filename,
  media_type, size_bytes, width_px, height_px, checksum_sha256, object_etag,
  created_by, created_at
) VALUES (
  '80000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  'K106',
  'equipment/fixture-a.bin',
  'fixture-a.bin',
  'application/octet-stream',
  41,
  1,
  1,
  'c858f8b56ecd70696959f480e741b89b356ba1485851bb5929bac6455f0082a0',
  'dr-fixture-etag',
  'dr-engineer',
  '2026-07-28T06:50:00Z'
);

INSERT INTO refrigeration_layout_drafts (
  id, organization_id, equipment_id, version, image_id, placements,
  created_at, updated_at
) VALUES (
  '81000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  'K106',
  1,
  '80000000-0000-0000-0000-000000000099',
  '[{"channel_id":"106-03","x":0.25,"y":0.35},{"channel_id":"106-04","x":0.75,"y":0.65}]'::jsonb,
  '2026-07-28T06:51:00Z',
  '2026-07-28T06:52:00Z'
);

INSERT INTO refrigeration_layout_revisions (
  id, organization_id, equipment_id, revision, source_draft_version,
  image_id, placements, published_by, published_at
) VALUES (
  '82000000-0000-0000-0000-000000000099',
  '00000000-0000-0000-0000-000000000099',
  'K106',
  1,
  1,
  '80000000-0000-0000-0000-000000000099',
  '[{"channel_id":"106-03","x":0.25,"y":0.35},{"channel_id":"106-04","x":0.75,"y":0.65}]'::jsonb,
  'dr-engineer',
  '2026-07-28T06:53:00Z'
);
