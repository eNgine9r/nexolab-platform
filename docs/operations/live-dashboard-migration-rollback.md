# Live Dashboard migration, backup and rollback

Issue: #287  
Migration: `20260805_0022`

## Upgrade

The migration creates:

- `live_dashboards`;
- `live_dashboard_items`;
- organization/status/update indexes;
- deterministic item-order indexes;
- foreign keys to local organizations and canonical measurement channels.

Run the normal telemetry-service Alembic upgrade before starting the new service
image. The migration contains no hardware, acquisition-registry or telemetry-history
mutation.

## Backup

Live Dashboard definitions are part of the PostgreSQL backup boundary already used
by NEXOLAB. A normal database backup captures dashboard definitions and ordered
items together with the canonical channel catalog.

No dashboard-specific cloud export is required.

## Rollback

Before downgrading below `20260805_0022`, export or back up the PostgreSQL database
when dashboard definitions must be retained. The downgrade intentionally drops only:

1. `live_dashboard_items`;
2. `live_dashboards`.

It does not delete or modify:

- `telemetry_samples`;
- telemetry history or dead letters;
- measurement channels, devices, buses or chambers;
- refrigeration equipment or layouts;
- the Device Agent acquisition registry;
- scheduler state;
- security identities or audit history.

After schema downgrade, roll back the telemetry-service image using the established
offline bundle procedure. Keep persistent volumes intact.

## Recovery verification

A release is acceptable only when CI proves:

- upgrade from the current single Alembic head;
- PostgreSQL CRUD and organization isolation;
- stale-writer rejection;
- archive preserving telemetry;
- authenticated role boundaries;
- audit events;
- disconnected bundle startup and update/rollback data preservation.

Physical Raspberry Pi and RS-485 verification is not required for this database-only
domain, but no hardware acceptance claim may be inferred from the migration.
