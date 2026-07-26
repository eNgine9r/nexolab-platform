from pathlib import Path

root = Path(__file__).resolve().parents[2]

audit_repository = root / "services/telemetry-service/app/sessions/audit_repository.py"
text = audit_repository.read_text()
old_key = "        normalized_key = self._normalize_idempotency_key(idempotency_key)\n"
new_key = "        normalized_key = self._scoped_create_idempotency_key(idempotency_key)\n"
first_key = text.find(old_key)
if first_key < 0:
    raise SystemExit("audited create normalized key line not found")
first_fingerprint = text.find("        fingerprint = _fingerprint(\n", first_key)
if first_fingerprint < 0 or first_fingerprint - first_key > 200:
    raise SystemExit("audited create fingerprint is not adjacent to normalized key")
text = text[:first_key] + new_key + text[first_key + len(old_key) :]

anchor = "    def _create_event_by_key(\n"
anchor_index = text.find(anchor)
if anchor_index < 0:
    raise SystemExit("create event helper insertion point not found")
helper = '''    def _scoped_create_idempotency_key(self, value: str) -> str:
        normalized = self._normalize_idempotency_key(value)
        namespaced = f"{self._organization_id}\\0{normalized}".encode("utf-8")
        return hashlib.sha256(namespaced).hexdigest()

'''
if "def _scoped_create_idempotency_key" not in text:
    text = text[:anchor_index] + helper + text[anchor_index:]
audit_repository.write_text(text)

api_test = root / "services/telemetry-service/tests/test_session_api_organization_scope.py"
text = api_test.read_text()
old_schema = "    app = create_app(settings)\n    with Session(app.state.database.engine) as session:\n"
new_schema = (
    "    app = create_app(settings)\n"
    "    app.state.database.create_schema()\n"
    "    with Session(app.state.database.engine) as session:\n"
)
if old_schema not in text and "app.state.database.create_schema()" not in text:
    raise SystemExit("API test schema insertion point not found")
if old_schema in text:
    text = text.replace(old_schema, new_schema, 1)
api_test.write_text(text)
