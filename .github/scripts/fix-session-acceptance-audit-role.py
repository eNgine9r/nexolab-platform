from pathlib import Path

root = Path(__file__).resolve().parents[2]
runner = root / "scripts/run-test-sessions-browser-acceptance.sh"
text = runner.read_text()
old = """  ('88888888-8888-4888-8888-888888888801', 'viewer', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888802', 'engineer', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888803', 'engineer', 'sessions-acceptance-seed')
"""
new = """  ('88888888-8888-4888-8888-888888888801', 'viewer', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888802', 'engineer', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888802', 'auditor', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888803', 'engineer', 'sessions-acceptance-seed')
"""
if old not in text:
    raise SystemExit("acceptance role seed anchor not found")
runner.write_text(text.replace(old, new, 1))
