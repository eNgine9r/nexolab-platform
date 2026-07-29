\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned

SELECT jsonb_build_object(
  'sessions', jsonb_build_object(
    'test_sessions', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM test_sessions AS item
      WHERE item.id = '40000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'config_snapshots', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM session_config_snapshots AS item
      WHERE item.session_id = '40000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'stages', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM session_stages AS item
      WHERE item.session_id = '40000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb)
  ),
  'alerts', jsonb_build_object(
    'rules', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM alert_rules AS item
      WHERE item.id = '50000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'versions', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM alert_rule_versions AS item
      WHERE item.rule_id = '50000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'instances', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM alert_instances AS item
      WHERE item.id = '52000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'transitions', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM alert_transitions AS item
      WHERE item.alert_id = '52000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb)
  ),
  'reports', jsonb_build_object(
    'versions', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM test_report_versions AS item
      WHERE item.id = '60000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'artifacts', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM test_report_artifacts AS item
      WHERE item.report_id = '60000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb)
  ),
  'nodes', jsonb_build_object(
    'registry', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM central_nodes AS item
      WHERE item.organization_id = '00000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'credentials', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM central_node_credentials AS item
      WHERE item.organization_id = '00000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'broker_commands', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM central_node_broker_commands AS item
      WHERE item.organization_id = '00000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb)
  ),
  'refrigeration', jsonb_build_object(
    'images', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM equipment_images AS item
      WHERE item.id = '80000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'drafts', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM refrigeration_layout_drafts AS item
      WHERE item.id = '81000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb),
    'revisions', COALESCE((
      SELECT jsonb_agg(to_jsonb(item) ORDER BY item.id)
      FROM refrigeration_layout_revisions AS item
      WHERE item.id = '82000000-0000-0000-0000-000000000099'
    ), '[]'::jsonb)
  )
)::text;
