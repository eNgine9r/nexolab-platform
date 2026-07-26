from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "src/components/dashboard/temperature-chart.tsx"
content = path.read_text(encoding="utf-8")
content = content.replace("  const window = historyWindow ?? {", "  const queryWindow = historyWindow ?? {", 1)
content = content.replace(
    "    () => buildTemperatureHistoryChart(merged, window),\n    [merged, window.from, window.to],",
    "    () => buildTemperatureHistoryChart(merged, queryWindow),\n    [merged, queryWindow.from, queryWindow.to],",
    1,
)
path.write_text(content, encoding="utf-8")
