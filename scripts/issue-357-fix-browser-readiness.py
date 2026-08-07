from pathlib import Path

path = Path("e2e/refrigeration-layout.production.e2e.ts")
text = path.read_text()
old = '    waitUntil: "networkidle",\n'
new = '    waitUntil: "domcontentloaded",\n'
marker = "async function openProductionEquipment"
start = text.index(marker)
end = text.index("\n}\n\nasync function enterEditMode", start)
section = text[start:end]
if section.count(old) != 1:
    raise SystemExit("expected one networkidle readiness wait in openProductionEquipment")
text = text[:start] + section.replace(old, new) + text[end:]
path.write_text(text)
Path("scripts/issue-357-fix-browser-readiness.py").unlink()
Path(".github/workflows/issue-357-browser-readiness-fix.yml").unlink()
