from pathlib import Path

path = Path("src/components/refrigeration/refrigeration-equipment-route.tsx")
text = path.read_text()
old_catch = '''      .catch((reason: unknown) => {
        if (!active) return;
        if (!equipment) setEquipment(null);
        setError(reason instanceof Error ? reason.message : "Обладнання не знайдено.");
      })'''
new_catch = '''      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Обладнання не знайдено.");
      })'''
old_dependencies = '''  }, [equipment, equipmentId, runtime.repository, runtime.structuralSnapshotRepository]);'''
new_dependencies = '''  }, [equipmentId, runtime.repository, runtime.structuralSnapshotRepository]);'''
if text.count(old_catch) != 1:
    raise SystemExit("expected one route error handler")
if text.count(old_dependencies) != 1:
    raise SystemExit("expected one route effect dependency list")
path.write_text(text.replace(old_catch, new_catch).replace(old_dependencies, new_dependencies))
Path("scripts/issue-357-fix-route-effect.py").unlink()
Path(".github/workflows/issue-357-route-effect-fix.yml").unlink()
