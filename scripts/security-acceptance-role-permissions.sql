\set ON_ERROR_STOP on

-- Acceptance fixtures often seed memberships directly with SQL instead of
-- calling SecurityRepository.provision_membership(). Issue #385 makes
-- non-administrator authorization explicit-grant based, while migration 0023
-- preserves the historical bundles for already-persisted roles. Materialize
-- the same compatibility grants for fresh acceptance databases so the tests
-- exercise production-equivalent post-migration state rather than a schema-
-- incomplete seed.
INSERT INTO security_membership_permissions (
  membership_id,
  permission,
  assigned_by
)
SELECT
  roles.membership_id,
  grants.permission,
  'acceptance-role-compatibility'
FROM security_membership_roles AS roles
JOIN (
  VALUES
    ('laboratory_manager', 'dashboard.read'),
    ('laboratory_manager', 'live_dashboards.manage'),
    ('laboratory_manager', 'telemetry.read'),
    ('laboratory_manager', 'alerts.read'),
    ('laboratory_manager', 'audit.read'),
    ('laboratory_manager', 'reports.read'),
    ('laboratory_manager', 'nodes.read'),
    ('laboratory_manager', 'reports.generate'),
    ('laboratory_manager', 'equipment.manage'),
    ('laboratory_manager', 'nodes.manage'),
    ('laboratory_manager', 'layout.draft.edit'),
    ('laboratory_manager', 'layout.publish'),
    ('laboratory_manager', 'layout.restore'),
    ('laboratory_manager', 'sessions.manage'),
    ('laboratory_manager', 'sessions.operate'),
    ('laboratory_manager', 'alerts.rules.manage'),
    ('laboratory_manager', 'alerts.acknowledge'),
    ('laboratory_manager', 'reports.approve'),
    ('engineer', 'dashboard.read'),
    ('engineer', 'live_dashboards.manage'),
    ('engineer', 'telemetry.read'),
    ('engineer', 'alerts.read'),
    ('engineer', 'reports.read'),
    ('engineer', 'nodes.read'),
    ('engineer', 'reports.generate'),
    ('engineer', 'equipment.manage'),
    ('engineer', 'layout.draft.edit'),
    ('engineer', 'layout.publish'),
    ('engineer', 'layout.restore'),
    ('engineer', 'sessions.manage'),
    ('engineer', 'sessions.operate'),
    ('engineer', 'alerts.acknowledge'),
    ('operator', 'dashboard.read'),
    ('operator', 'live_dashboards.manage'),
    ('operator', 'telemetry.read'),
    ('operator', 'alerts.read'),
    ('operator', 'reports.read'),
    ('operator', 'nodes.read'),
    ('operator', 'layout.draft.edit'),
    ('operator', 'sessions.operate'),
    ('operator', 'alerts.acknowledge'),
    ('viewer', 'dashboard.read'),
    ('viewer', 'telemetry.read'),
    ('viewer', 'alerts.read'),
    ('viewer', 'reports.read'),
    ('viewer', 'nodes.read'),
    ('auditor', 'dashboard.read'),
    ('auditor', 'telemetry.read'),
    ('auditor', 'alerts.read'),
    ('auditor', 'audit.read'),
    ('auditor', 'reports.read'),
    ('auditor', 'nodes.read')
) AS grants(role, permission)
  ON grants.role = roles.role
ON CONFLICT (membership_id, permission) DO NOTHING;
