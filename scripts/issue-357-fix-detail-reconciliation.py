from pathlib import Path

path = Path("src/components/refrigeration/refrigeration-detail-screen.tsx")
text = path.read_text()
old_catch = '''      .catch((cause) => {
        if (!active) return;
        if (bindingSensors === null) setBindingSensors([]);
        setChannelError(
          cause instanceof Error ? cause.message : "Не вдалося оновити структурний snapshot обладнання.",
        );
      });'''
new_catch = '''      .catch((cause) => {
        if (!active) return;
        setBindingSensors((current) => current ?? []);
        setChannelError(
          cause instanceof Error ? cause.message : "Не вдалося оновити структурний snapshot обладнання.",
        );
      });'''
old_deps = '''  }, [bindingEpoch, bindingSensors, equipmentRecord.climateChamberId, equipmentRecord.id, runtime]);'''
new_deps = '''  }, [bindingEpoch, equipmentRecord.climateChamberId, equipmentRecord.id, runtime]);'''
if text.count(old_catch) != 1:
    raise SystemExit("expected one structural reconciliation error handler")
if text.count(old_deps) != 1:
    raise SystemExit("expected one structural reconciliation dependency list")
path.write_text(text.replace(old_catch, new_catch).replace(old_deps, new_deps))
Path("scripts/issue-357-fix-detail-reconciliation.py").unlink()
Path(".github/workflows/issue-357-detail-reconciliation-fix.yml").unlink()
