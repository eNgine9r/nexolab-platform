from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "src/components/dashboard/temperature-chart.tsx"
content = path.read_text(encoding="utf-8")
old = "  const chart = useMemo(() => buildTemperatureHistoryChart(merged, window), [merged, window.from, window.to]);\n"
new = "  const chart = buildTemperatureHistoryChart(merged, queryWindow);\n"
if old not in content:
    raise RuntimeError("Expected stale history window reference was not found")
path.write_text(content.replace(old, new, 1), encoding="utf-8")
