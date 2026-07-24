# Refrigeration layout persistence

This implementation slice introduces a repository boundary for versioned refrigeration layout drafts.

## Guarantees

- Draft versions increase monotonically after every successful mutation.
- Saves use an expected version and return `LAYOUT_VERSION_CONFLICT` for stale writers.
- Conflict responses never overwrite the caller's local draft.
- Published revisions are immutable and remain available in history.
- Restoring a revision creates a new draft version.
- Placements use normalized coordinates in the inclusive range `0..1`.

## Editor integration

The photo layout editor loads its draft through `RefrigerationLayoutRepository` and sends `expectedVersion` on every save. A successful save updates the editor's persisted baseline and advances the displayed draft version. A stale save leaves the editor in edit mode, keeps the local marker and image state intact, and displays both the expected and current repository versions.

The first adapter is deterministic and in-memory. PostgreSQL and object-storage adapters remain separate scopes.
