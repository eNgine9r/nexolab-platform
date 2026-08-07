from pathlib import Path

path = Path("src/components/refrigeration/refrigeration-detail-screen.tsx")
text = path.read_text()
old = '''      if (bindingSensors === null) {
        setBindingSensors(runtime.mode === "demo" ? null : []);
      }'''
new = '''      setBindingSensors((current) => current ?? (runtime.mode === "demo" ? null : []));'''
if text.count(old) != 1:
    raise SystemExit("expected one early binding sensor fallback")
path.write_text(text.replace(old, new))
Path("scripts/issue-357-fix-detail-lint.py").unlink()
Path(".github/workflows/issue-357-detail-lint-fix.yml").unlink()
