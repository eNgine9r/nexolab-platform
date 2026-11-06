# Navigation-grant foundation

Issue #1528 introduces named navigation grants alongside existing resource and
operation permissions. A navigation grant controls presentation only after a
later UI work package uses it. It does not authorize data, and it does not
replace any existing API permission. Do not deploy the foundation by itself as
a completed page-access feature.

The migration preserves existing resource grants and backfills navigation
grants from the corresponding pre-existing capabilities. It does not grant
camera or planned-locker navigation to non-administrators. New local product
users receive only grants explicitly selected during provisioning. PostgreSQL
serializes concurrent permission writes while the migration runs.

The permission-replacement API uses `navigation_contract_version: 1` when the
caller intentionally replaces navigation grants. An older client that changes
only resource permissions preserves existing navigation choices; unversioned
attempts to assign navigation grants are rejected. Legacy membership
reprovisioning and administrator promotion retain stored navigation choices.
The application still revokes affected local sessions on permission changes.

The migration deliberately refuses automatic downgrade: removing the new
grants would discard administrator decisions, and an older interface cannot
enforce those decisions. Recovery requires a separately verified backup and
restore plan, with the compatible frontend and backend restored together.

Older frontends reject sessions containing unknown permission names, including
the implicit full administrator session. A release must therefore validate
frontend/backend compatibility and a protected, coordinated rollout before
applying the migration. A source merge or simulated database test is not a site
backup, a recoverability proof, or authorization to update the Raspberry Pi.
Existing local authentication, offline operation and resource authorization
must remain functional throughout the approved release procedure.
