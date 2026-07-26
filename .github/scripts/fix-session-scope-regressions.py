from pathlib import Path

root = Path(__file__).resolve().parents[2]

audit_repository = root / "services/telemetry-service/app/sessions/audit_repository.py"
text = audit_repository.read_text()
old = '''    ) -> TransitionResult:\n        normalized_key = self._normalize_idempotency_key(idempotency_key)\n        fingerprint = _fingerprint(\n'''
new = '''    ) -> TransitionResult:\n        normalized_key = self._scoped_create_idempotency_key(idempotency_key)\n        fingerprint = _fingerprint(\n'''
if old not in text:
    raise SystemExit("audited create idempotency anchor not found")
text = text.replace(old, new, 1)
anchor = '''    def _create_event_by_key(\n        self,\n        db_session: Session,\n        idempotency_key: str,\n    ) -> SessionEvent | None:\n'''
helper = '''    def _scoped_create_idempotency_key(self, value: str) -> str:\n        normalized = self._normalize_idempotency_key(value)\n        namespaced = f"{self._organization_id}\\0{normalized}".encode("utf-8")\n        return hashlib.sha256(namespaced).hexdigest()\n\n    def _create_event_by_key(\n        self,\n        db_session: Session,\n        idempotency_key: str,\n    ) -> SessionEvent | None:\n'''
if anchor not in text:
    raise SystemExit("create event helper anchor not found")
audit_repository.write_text(text.replace(anchor, helper, 1))

api_test = root / "services/telemetry-service/tests/test_session_api_organization_scope.py"
text = api_test.read_text()
old = '''    app = create_app(settings)\n    with Session(app.state.database.engine) as session:\n'''
new = '''    app = create_app(settings)\n    app.state.database.create_schema()\n    with Session(app.state.database.engine) as session:\n'''
if old not in text:
    raise SystemExit("API test schema anchor not found")
api_test.write_text(text.replace(old, new, 1))

doc = root / "docs/organization-scoped-test-sessions.md"
text = doc.read_text()
addition = '''\n## Create idempotency namespace\n\nSession-create idempotency keys are normalized and stored as a SHA-256 namespace of the verified organization ID and the client key. The same client-generated key can therefore be replayed independently in two organizations without exposing the original key or weakening the legacy unique database guard.\n'''
if "## Create idempotency namespace" not in text:
    doc.write_text(text.rstrip() + "\n" + addition)
