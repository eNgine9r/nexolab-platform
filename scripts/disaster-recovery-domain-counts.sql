\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned

SELECT jsonb_build_object(
  'sessions', (SELECT count(*) FROM test_sessions WHERE id = '40000000-0000-0000-0000-000000000099'),
  'session_config_snapshots', (SELECT count(*) FROM session_config_snapshots WHERE session_id = '40000000-0000-0000-0000-000000000099'),
  'session_stages', (SELECT count(*) FROM session_stages WHERE session_id = '40000000-0000-0000-0000-000000000099'),
  'alert_rules', (SELECT count(*) FROM alert_rules WHERE id = '50000000-0000-0000-0000-000000000099'),
  'alert_rule_versions', (SELECT count(*) FROM alert_rule_versions WHERE rule_id = '50000000-0000-0000-0000-000000000099'),
  'alert_instances', (SELECT count(*) FROM alert_instances WHERE id = '52000000-0000-0000-0000-000000000099'),
  'alert_transitions', (SELECT count(*) FROM alert_transitions WHERE alert_id = '52000000-0000-0000-0000-000000000099'),
  'report_versions', (SELECT count(*) FROM test_report_versions WHERE id = '60000000-0000-0000-0000-000000000099'),
  'report_artifacts', (SELECT count(*) FROM test_report_artifacts WHERE report_id = '60000000-0000-0000-0000-000000000099'),
  'nodes', (SELECT count(*) FROM central_nodes WHERE organization_id = '00000000-0000-0000-0000-000000000099'),
  'node_credentials', (SELECT count(*) FROM central_node_credentials WHERE organization_id = '00000000-0000-0000-0000-000000000099'),
  'broker_commands', (SELECT count(*) FROM central_node_broker_commands WHERE organization_id = '00000000-0000-0000-0000-000000000099'),
  'equipment_images', (SELECT count(*) FROM equipment_images WHERE id = '80000000-0000-0000-0000-000000000099'),
  'refrigeration_drafts', (SELECT count(*) FROM refrigeration_layout_drafts WHERE id = '81000000-0000-0000-0000-000000000099'),
  'refrigeration_revisions', (SELECT count(*) FROM refrigeration_layout_revisions WHERE id = '82000000-0000-0000-0000-000000000099')
)::text;
