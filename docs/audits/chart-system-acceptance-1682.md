# XWEB Advanced Chart System — isolated real-browser acceptance (#1682)

**Scope:** WP-S evidence. **Environment:** a developer desktop (Windows 11, headless Chromium from the repository's pinned Playwright, Vite dev server), offline (every non-loopback request aborted), deterministic fixtures. **This is not Raspberry Pi evidence and not site evidence.** No backend, database, Modbus device, Device Agent or production system was contacted or modified.

The harness renders the _real_ production components (`DashboardLiveView`, `ChartShell`, `EChartsRendererAdapter`, the state lanes, the Live channel picker, the XLSX/print export) with fixture telemetry, so rendering, interactions, exports and layout are measured in a real browser. Fixtures stand in for the REST API; API behaviour is covered by the repository CI (stack-based acceptance jobs), not by this harness.

## Result: 27 / 27 checks passed (current `main` + the open WP-Q slice)

| Area                          | Check                                                                                                         | Result | Evidence                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------- |
| Series count × width, offline | 1, 8 and 24 series at 360 / 1440 / 1920 px render one canvas, one statistics row per series, 5 state lanes    | PASS   | horizontal overflow 0 px, external requests 0, console/page errors 0 (all 9 combinations)            |
| 24 h history                  | statistics count _raw_ measurements while the chart is reduced                                                | PASS   | 85 220 raw vs 1 852 plotted (8 series); statistics valid count 8 521 per series (outage excluded)    |
| 7 d history                   | same contract on 7 days                                                                                       | PASS   | 603 620 raw vs 1 952 plotted; 60 361 valid per series                                                |
| Density                       | «2 500» keeps more points than «Авто» on 24 h and 7 d; status states shown / available                        | PASS   | 24 h: 1 852 → 5 593; 7 d: 1 952 → 5 984; «показано 4 768 із 68 168 вимірювань»                       |
| Interactions                  | shared cursor drives all state lanes (ON / OFF / Невідомо / Немає даних)                                      | PASS   | `OFF OFF ON OFF OFF` at the probed instant                                                           |
| Interactions                  | wheel zoom switches the statistics scope to «Видимий (збільшений) інтервал»; reset returns to the whole range | PASS   | scope headings read back from the DOM                                                                |
| Keyboard / assistive          | no unlabelled buttons, tables have headers, focus reaches density select and «Зберегти PNG»                   | PASS   | 0 unlabelled buttons                                                                                 |
| PNG export                    | a real PNG of the visible plot                                                                                | PASS   | 2748 × 640 px, 274 055 bytes                                                                         |
| XLSX export                   | the Saved Dashboard downloads a valid OOXML workbook (ZIP)                                                    | PASS   | 20 176 bytes                                                                                         |
| Print / PDF                   | print layout hides navigation and controls, shows the report header; Chromium prints a PDF offline            | PASS   | 373 440 bytes                                                                                        |
| Saved analysis view           | hidden series, range and density are captured; reopening restores the hidden series                           | PASS   | `{"hidden_items":["T-1\|temperature.probe"],"range_kind":"24h","density":1000}`; 3 of 4 rows visible |
| RBAC                          | a viewer without manage permission gets no save controls                                                      | PASS   | 0 save buttons                                                                                       |
| Live channel picker           | 32 channels: select-all stops at the 24-series limit with a message; search and operator names work           | PASS   | 24 selected, 1 group after search                                                                    |

## Measured timings (desktop only — do not read them as Pi numbers)

| Scenario (headless Chromium, desktop)                    | Measured                                    |
| -------------------------------------------------------- | ------------------------------------------- |
| Dashboard ready, 1 series, 25 566 raw samples            | ≈ 1.5 s (first page load of the run: 4.3 s) |
| Dashboard ready, 8 series, 85 220 raw samples            | ≈ 1.9 s                                     |
| Dashboard ready, 24 series, 221 572 raw samples          | ≈ 2.6 s                                     |
| Reduction + statistics build, 8 series × 24 h            | 352 ms                                      |
| Reduction + statistics build, 8 series × 7 d (604 k raw) | 2.7 s                                       |

The Raspberry Pi has **not** been measured. The existing `chart-density-benchmark-1620.md` extrapolation (×2.4) remains an extrapolation. Long-range × many-series loads are dominated by loading raw history per channel (client-side); server-side downsampling for very long ranges remains a backend decision and is not part of this programme.

## Not covered by this harness (still open, by design)

- A signed-in human review on the controlled Pi browser (LAN and HTTPS), including 390 px layouts on real hardware.
- Real hardware semantics: Embraco ×0.01 °C scale (#1603/#1625), real relay/defrost/alarm bit meaning, and digital lanes against real controller data. Lanes are only created for metrics the drivers really deliver (see `digital-channels.ts`); door and fan-contactor lanes are **not** invented where no source metric exists.
- Offline reboot / power-cycle (#1606), encrypted off-device DR (#1428), Docker/LAN CIDR overlap (#1409/#1399).
- The backend half of Saved Analysis Views (PR #1667): blocked, see the release-candidate document.

## Reproduction

The harness lives only under `node_modules/.nexolab-harness/` locally (outside lint/CI scope on purpose — an unclassified `tests/**` path fails the fail-closed Merge Gate classifier). Its sources are reproduced in the appendices. Recreate the four files in a directory with a Vite config that aliases `@` to `src` and run `node acceptance.mjs <outDir>`; fixtures are generated in `main.tsx`.

## Appendix A. vite.config.ts

```ts
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
  root: here,
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(here, "../../src") } },
  server: { host: "127.0.0.1", port: 5188, strictPort: true, fs: { allow: [path.resolve(here, "../..")] } },
  css: { postcss: path.resolve(here, "../..") },
});
```

## Appendix B. index.html

```html
<!doctype html>
<html lang="uk">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NEXOLAB acceptance harness</title>
  </head>
  <body class="bg-[#06142a] text-slate-100">
    <div id="root"></div>
    <script type="module" src="/main.tsx"></script>
  </body>
</html>
```

## Appendix C. main.tsx (fixtures and mount)

```tsx
import "../../src/app/globals.css";

import { createRoot } from "react-dom/client";
import { useMemo, useState } from "react";

import { DashboardLiveView } from "@/components/live-dashboards/dashboard-live-view";
import { LiveChannelPicker } from "@/components/live/live-channel-picker";
import {
  appendIntervalSample,
  computeIntervalStatistics,
  createIntervalSampleColumns,
  type IntervalSampleColumns,
} from "@/features/charts/interval-statistics";
import { resolveChartPointBudget, type ChartDensityMode } from "@/features/charts/density";
import { dashboardItemIdentity } from "@/features/live-dashboards/model";
import { reduceSavedDashboardHistory } from "@/features/live-dashboards/operator-history";
import type {
  LiveDashboard,
  LiveDashboardItem,
  LiveDashboardViewSettings,
} from "@/features/live-dashboards/types";
import type { LiveDashboardTelemetryModel } from "@/hooks/use-live-dashboard-telemetry";
import type { TelemetrySample } from "@/lib/telemetry/types";

const params = new URLSearchParams(location.search);
const scenario = params.get("scenario") ?? "dashboard";
const SERIES = Number(params.get("series") ?? 8);
const RANGE = (params.get("range") ?? "24h") as "1h" | "6h" | "24h" | "7d";
const CAN_MANAGE = params.get("manage") !== "0";
const CADENCE_MS = 10_000;
const RANGE_MS = { "1h": 3_600_000, "6h": 21_600_000, "24h": 86_400_000, "7d": 604_800_000 } as const;
const NOW = Date.now();

declare global {
  interface Window {
    harness: {
      savedViews: LiveDashboardViewSettings[];
      renderMs: number[];
      rawCount: number;
      reducedCount: number;
    };
  }
}
window.harness = { savedViews: [], renderMs: [], rawCount: 0, reducedCount: 0 };

function item(
  id: string,
  position: number,
  channel: string,
  metric: string,
  unit: string,
): LiveDashboardItem {
  return {
    id,
    position,
    channel_ref_id: `ref-${id}`,
    node_id: null,
    equipment_id: null,
    channel_id: channel,
    metric,
    native_unit: unit,
    visualization: "line",
    color: null,
    display_unit: unit === "degC" ? "°C" : unit,
  };
}

function sample(
  item_: LiveDashboardItem,
  timestampMs: number,
  value: number | null,
  quality: TelemetrySample["quality"],
) {
  return {
    event_id: `${item_.id}-${timestampMs}`,
    node_id: "edge-1",
    captured_at: new Date(timestampMs).toISOString(),
    metric: item_.metric,
    value,
    unit: item_.native_unit,
    quality,
    source: "harness",
    equipment_id: "K106",
    channel_id: item_.channel_id,
    alarm: null,
    raw_value: value,
    raw_status: null,
  } as TelemetrySample;
}

function build(seriesCount: number, rangeMs: number, density: ChartDensityMode) {
  const to = NOW;
  const from = to - rangeMs;
  const items: LiveDashboardItem[] = [];
  for (let index = 0; index < seriesCount; index += 1) {
    items.push(item(`s${index + 1}`, index + 1, `T-${index + 1}`, "temperature.probe", "degC"));
  }
  const digital = [
    item("d1", seriesCount + 1, "compressor", "compressor.state", "state"),
    item("d2", seriesCount + 2, "relays", "controller.relay_state_bits", "bitfield"),
  ];
  const all = [...items, ...digital];
  const resolution = resolveChartPointBudget(density, Math.max(1, seriesCount));
  const window = { from: new Date(from), to: new Date(to) };
  const columns = new Map<string, IntervalSampleColumns>();
  let raw = 0;
  let reducedTotal = 0;
  const series = all.map((entry, index) => {
    const samples: TelemetrySample[] = [];
    const cols = createIntervalSampleColumns();
    const isDigital = entry.metric.endsWith("state") || entry.metric.endsWith("bits");
    for (let at = from; at <= to; at += CADENCE_MS) {
      // A 20-minute outage in the middle of every series, one failed poll, one spike.
      const mid = from + rangeMs / 2;
      if (at > mid && at < mid + 20 * 60_000) continue;
      const step = Math.round((at - from) / CADENCE_MS);
      let value: number | null;
      let quality: TelemetrySample["quality"] = "valid";
      if (isDigital)
        value = entry.metric.endsWith("bits")
          ? Math.floor(step / 60) % 2
            ? 0b01
            : 0b10
          : Math.floor(step / 90) % 2;
      else value = 4 + Math.sin(step / 200 + index) * 2 + (step === 1_000 ? 30 : 0);
      if (step === 500) {
        value = null;
        quality = "communication_error";
      }
      samples.push(sample(entry, at, value, quality));
      appendIntervalSample(cols, at, quality === "valid" ? value : null);
    }
    raw += samples.length;
    columns.set(dashboardItemIdentity(entry), cols);
    const reduced = reduceSavedDashboardHistory(entry, samples, window, resolution.perSeries);
    reducedTotal += reduced.length;
    return { item: entry, latest: samples.at(-1) ?? null, history: reduced };
  });
  window_.harnessCounts = { raw, reduced: reducedTotal };
  return { all, series, columns, resolution, from, to };
}

const window_ = globalThis as unknown as { harnessCounts: { raw: number; reduced: number } };

function Dashboard() {
  const [density, setDensity] = useState<ChartDensityMode>("auto");
  const [range, setRange] = useState(RANGE);
  const [view, setView] = useState<LiveDashboardViewSettings | null>(null);
  const [instance, setInstance] = useState(0);
  const data = useMemo(() => {
    const start = performance.now();
    const result = build(SERIES, RANGE_MS[range], density);
    window.harness.renderMs.push(Math.round(performance.now() - start));
    window.harness.rawCount = window_.harnessCounts.raw;
    window.harness.reducedCount = window_.harnessCounts.reduced;
    return result;
  }, [density, range]);

  const dashboard: LiveDashboard = {
    id: "d1",
    organization_id: "org",
    name: "Приймальна перевірка",
    description: null,
    owner_subject: "operator",
    refresh_seconds: 5,
    time_window: range === "7d" ? "7d" : "24h",
    version: 1,
    status: "active",
    created_by: "operator",
    updated_by: "operator",
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    archived_by: null,
    archived_at: null,
    items: data.all,
    view_settings: view,
  };
  const rangeValue = {
    kind: range,
    from: new Date(data.from).toISOString(),
    to: new Date(data.to).toISOString(),
    label: range,
  };
  const telemetry = {
    status: "live",
    connectionState: "connected",
    series: data.series,
    lastCapturedAt: new Date(NOW).toISOString(),
    now: NOW,
    historyRange: rangeValue,
    historyWindow: rangeValue,
    historyStatus: "ready",
    historyError: null,
    exportStatus: "idle",
    exportError: null,
    selectHistoryPreset: (preset: "1h" | "6h" | "24h" | "7d" | "30d") => {
      if (preset !== "30d") setRange(preset);
    },
    applyCustomHistoryRange: () => undefined,
    exportCsv: async () => {
      const header = "timestamp_utc,timestamp_local,node,device,channel,metric,value,unit,quality,event_id";
      const rows = data.series
        .slice(0, 3)
        .flatMap((entry) =>
          entry.history
            .slice(0, 5)
            .map(
              (s) =>
                `${s.captured_at},${s.captured_at},${s.node_id},${s.equipment_id},${s.channel_id},${s.metric},${s.value ?? ""},${s.unit},${s.quality},${s.event_id}`,
            ),
        );
      return {
        blob: new Blob([[header, ...rows].join("\n") + "\n"], { type: "text/csv" }),
        filename: "live-dashboard-harness.csv",
        mediaType: "text/csv",
      };
    },
    retry: () => undefined,
    error: null,
    intervalStatistics: (identity: string, fromMs: number, toMs: number) => {
      const cols = data.columns.get(identity);
      return cols ? computeIntervalStatistics(cols, fromMs, toMs) : null;
    },
    intervalColumns: (identity: string) => data.columns.get(identity),
  } as unknown as LiveDashboardTelemetryModel;

  return (
    <div className="mx-auto max-w-[1700px] p-4">
      <nav data-testid="fake-nav" className="mb-3 rounded border border-white/10 p-2 text-xs print:hidden">
        Навігація (не друкується)
      </nav>
      <DashboardLiveView
        key={instance}
        dashboard={dashboard}
        telemetry={telemetry}
        density={density}
        densityResolution={data.resolution}
        onDensityChange={setDensity}
        canManage={CAN_MANAGE}
        onBack={() => undefined}
        onEdit={() => undefined}
        onSaveView={async (settings) => {
          window.harness.savedViews.push(...(settings ? [settings] : []));
          setView(settings);
        }}
      />
      <button
        type="button"
        data-testid="harness-remount"
        className="mt-4 rounded border border-white/10 px-3 py-1 text-xs print:hidden"
        onClick={() => setInstance((current) => current + 1)}
      >
        Перевідкрити Dashboard
      </button>
    </div>
  );
}

function Picker() {
  const [selected, setSelected] = useState<string[]>([]);
  const samples = useMemo(() => {
    const result: TelemetrySample[] = [];
    for (let device = 1; device <= 4; device += 1) {
      for (let channel = 1; channel <= 8; channel += 1) {
        result.push({
          event_id: `p-${device}-${channel}`,
          node_id: "edge-1",
          captured_at: new Date(NOW).toISOString(),
          metric: "temperature.probe",
          value: 4,
          unit: "degC",
          quality: "valid",
          source: "harness",
          equipment_id: `K10${device}`,
          channel_id: `10${device}-0${channel}`,
          alarm: null,
          raw_value: 4,
          raw_status: null,
        } as TelemetrySample);
      }
    }
    return result;
  }, []);
  return (
    <div className="mx-auto max-w-5xl p-4">
      <LiveChannelPicker
        samples={samples}
        selectedKeys={selected}
        names={{ "edge-1/101-01": "Вітрина верх" }}
        onChange={setSelected}
      />
      <output data-testid="picker-selected">{selected.length}</output>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(scenario === "picker" ? <Picker /> : <Dashboard />);
```

## Appendix D. acceptance.mjs (checks)

```js
// WP-S acceptance harness: real components in real headless Chromium with deterministic fixtures.
// usage: node .harness/acceptance.mjs <outDir>
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const out = process.argv[2];
mkdirSync(out, { recursive: true });
const root = fileURLToPath(new URL(".", import.meta.url));
const server = await createServer({ configFile: join(root, "vite.config.ts"), logLevel: "error" });
await server.listen();
const base = "http://127.0.0.1:5188/";
const browser = await chromium.launch();
const RANGE = { "24h": 86_400_000, "7d": 604_800_000 };
const results = [];
const record = (name, pass, detail = "") => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
};

async function open(query, { width = 1440, height = 1000, offline = true } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, acceptDownloads: true });
  const external = [];
  const errors = [];
  if (offline) {
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (
        url.hostname === "127.0.0.1" ||
        url.hostname === "localhost" ||
        url.protocol === "data:" ||
        url.protocol === "blob:"
      ) {
        return route.continue();
      }
      external.push(route.request().url());
      return route.abort();
    });
  }
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const start = Date.now();
  await page.goto(`${base}?${query}`);
  await page.waitForSelector(
    '[data-testid="saved-dashboard-chart-panel"], [data-testid="live-channel-picker"]',
    { timeout: 60_000 },
  );
  await page.waitForTimeout(800);
  return { context, page, external, errors, loadMs: Date.now() - start };
}

async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

try {
  // 1. 1 / 8 / 24 series × responsive widths × offline
  for (const series of [1, 8, 24]) {
    for (const width of [360, 1440, 1920]) {
      const { context, page, external, errors, loadMs } = await open(`series=${series}&range=24h`, { width });
      const panels = await page.locator('[data-testid="saved-dashboard-chart-panel"]').count();
      const canvases = await page.locator("canvas").count();
      const over = await overflow(page);
      const stats = await page.locator('[data-testid="dashboard-statistics-row"]').count();
      const lanes = await page.locator("[data-state-lane]").count();
      const counts = await page.evaluate(() => ({
        raw: window.harness.rawCount,
        reduced: window.harness.reducedCount,
      }));
      record(
        `series=${series} width=${width} renders`,
        panels >= 1 &&
          canvases >= 1 &&
          stats === series &&
          lanes === 5 &&
          over <= 1 &&
          external.length === 0 &&
          errors.length === 0,
        `panels=${panels} canvases=${canvases} statRows=${stats} lanes=${lanes} overflow=${over}px external=${external.length} errors=${errors.length} raw=${counts.raw} reduced=${counts.reduced} ready=${loadMs}ms`,
      );
      if (errors.length) console.log(errors.slice(0, 3));
      await context.close();
    }
  }

  // 2. 24 h and 7 d history, density budget, exact statistics vs reduced points
  for (const range of ["24h", "7d"]) {
    const { context, page } = await open(`series=8&range=${range}`);
    const counts = await page.evaluate(() => ({
      raw: window.harness.rawCount,
      reduced: window.harness.reducedCount,
      ms: window.harness.renderMs.at(-1),
    }));
    const firstRow = page.locator('[data-testid="dashboard-statistics-row"]').first();
    const countCell = await firstRow.locator("td").nth(3).innerText();
    const validCount = Number(countCell.split("(")[0].replace(/[^0-9]/g, ""));
    const expectedPerSeries = Math.round(RANGE[range] / 10_000) + 1;
    record(
      `history ${range}: statistics count raw measurements, chart is reduced`,
      counts.reduced < counts.raw / 4 &&
        Number.isFinite(validCount) &&
        validCount > expectedPerSeries * 0.9 &&
        validCount <= expectedPerSeries,
      `raw=${counts.raw} reduced=${counts.reduced} statValid=${validCount} (≈${expectedPerSeries} expected less the outage) build=${counts.ms}ms`,
    );
    // density: higher mode keeps more points
    await page.getByLabel("Деталізація / точок на лінію").selectOption("2500");
    await page.waitForTimeout(500);
    const higher = await page.evaluate(() => window.harness.reducedCount);
    record(
      `density 2500 keeps more points than Auto (${range})`,
      higher > counts.reduced,
      `auto=${counts.reduced} 2500=${higher}`,
    );
    const status = await page.getByTestId("chart-density-status").innerText();
    record(
      `density status shows shown/available (${range})`,
      /показано .* із /.test(status),
      status.replace(/\s+/g, " "),
    );
    await context.close();
  }

  // 3. interactions: cursor, wheel zoom → viewport scope, reset, keyboard
  {
    const { context, page } = await open("series=8&range=24h");
    const canvas = page.locator("canvas").first();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
    await page.waitForTimeout(500);
    const cursorLanes = await page.locator('[data-testid="state-lane-cursor-state"]').allInnerTexts();
    record(
      "shared cursor drives the state lanes",
      cursorLanes.length === 5 && cursorLanes.every((t) => /ON|OFF|Невідомо|Немає даних/.test(t)),
      cursorLanes.join(" | "),
    );
    const scopeBefore = await page.getByTestId("dashboard-interval-statistics-scope").innerText();
    await page.mouse.wheel(0, -600);
    await page.waitForTimeout(700);
    const scopeAfter = await page.getByTestId("dashboard-interval-statistics-scope").innerText();
    record(
      "wheel zoom switches statistics to the visible interval",
      /Весь/.test(scopeBefore) && /Видимий/.test(scopeAfter),
      `${scopeBefore.slice(0, 30)} → ${scopeAfter.slice(0, 30)}`,
    );
    await page.getByRole("button", { name: "Скинути масштаб" }).first().click();
    await page.waitForTimeout(500);
    const scopeReset = await page.getByTestId("dashboard-interval-statistics-scope").innerText();
    record("reset zoom returns to the whole interval", /Весь/.test(scopeReset), scopeReset.slice(0, 30));
    // keyboard: tab reaches the density select and Save PNG
    await page.keyboard.press("Tab");
    const focusable = await page.evaluate(() => {
      const seen = new Set();
      for (let i = 0; i < 60; i += 1) {
        const active = document.activeElement;
        if (active)
          seen.add(
            `${active.tagName}:${active.getAttribute("aria-label") ?? active.textContent?.trim().slice(0, 24) ?? ""}`,
          );
        document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
      }
      return seen.size;
    });
    const selectFocusable = await page
      .getByLabel("Деталізація / точок на лінію")
      .evaluate((el) => el.tabIndex >= 0 && !el.disabled);
    const buttonsLabelled = await page.evaluate(
      () =>
        [...document.querySelectorAll("button")].filter(
          (b) => !(b.textContent?.trim() || b.getAttribute("aria-label")),
        ).length,
    );
    const tables = await page.evaluate(() =>
      [...document.querySelectorAll("table")].every((t) => t.querySelector("caption, thead")),
    );
    record(
      "keyboard/screen-reader basics",
      selectFocusable && buttonsLabelled === 0 && tables,
      `unlabelled buttons=${buttonsLabelled} tablesHaveHeaders=${tables} focusProbe=${focusable}`,
    );
    await context.close();
  }

  // 4. PNG export in a real browser
  {
    const { context, page } = await open("series=8&range=24h");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("chart-export-png").first().click(),
    ]);
    const file = join(out, download.suggestedFilename());
    await download.saveAs(file);
    const bytes = readFileSync(file);
    const isPng = bytes.subarray(0, 8).toString("hex") === "89504e470d0a1a0a";
    const width = bytes.readUInt32BE(16);
    const height = bytes.readUInt32BE(20);
    record(
      "PNG export produces a real PNG of the visible plot",
      isPng && width > 600 && height > 300,
      `${download.suggestedFilename()} ${width}x${height} ${statSync(file).size} bytes`,
    );
    await context.close();
  }

  // 5. XLSX download
  {
    const { context, page } = await open("series=8&range=24h");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("dashboard-export-xlsx").click(),
    ]);
    const file = join(out, download.suggestedFilename());
    await download.saveAs(file);
    const bytes = readFileSync(file);
    record(
      "XLSX download is a zip workbook",
      bytes.subarray(0, 2).toString() === "PK" && download.suggestedFilename().endsWith(".xlsx"),
      `${download.suggestedFilename()} ${bytes.length} bytes`,
    );
    await context.close();
  }

  // 6. print to PDF
  {
    const { context, page } = await open("series=8&range=24h");
    await page.emulateMedia({ media: "print" });
    const navVisible = await page.getByTestId("fake-nav").isVisible();
    const headerVisible = await page.getByTestId("dashboard-print-header").isVisible();
    const controlsVisible = await page.getByLabel("Saved Dashboard history range and export").isVisible();
    const file = join(out, "dashboard-report.pdf");
    await page.pdf({ path: file, format: "A4", printBackground: true });
    const bytes = readFileSync(file);
    record(
      "print layout hides navigation and controls, shows the report header",
      !navVisible && headerVisible && !controlsVisible,
      `nav=${navVisible} header=${headerVisible} controls=${controlsVisible}`,
    );
    record(
      "PDF is generated offline by the browser",
      bytes.subarray(0, 4).toString() === "%PDF" && bytes.length > 20_000,
      `${bytes.length} bytes`,
    );
    await context.close();
  }

  // 7. saved analysis view round trip + RBAC
  {
    const { context, page } = await open("series=4&range=24h");
    await page
      .getByRole("button", { name: /Приховати/ })
      .first()
      .click();
    await page.getByLabel("Деталізація / точок на лінію").selectOption("1000");
    await page.getByText("Зберегти вигляд аналізу").click();
    await page.waitForTimeout(400);
    const saved = await page.evaluate(() => window.harness.savedViews.at(-1));
    record(
      "saved view captures hidden series, range and density",
      saved && saved.hidden_items.length === 1 && saved.range_kind === "24h" && saved.density === 1000,
      JSON.stringify(saved),
    );
    await page.getByTestId("harness-remount").click();
    await page.waitForTimeout(900);
    const rows = await page.locator('[data-testid="dashboard-statistics-row"]').count();
    record(
      "reopening restores the hidden series",
      rows === 3,
      `visible statistic rows after reopen=${rows} (4 series, 1 hidden)`,
    );
    await context.close();
    const readOnly = await open("series=4&range=24h&manage=0");
    const hasSave = await readOnly.page.getByText("Зберегти вигляд аналізу").count();
    record("viewer without manage permission cannot save a view", hasSave === 0, `save buttons=${hasSave}`);
    await readOnly.context.close();
  }

  // 8. Live device picker with 24 channels
  {
    const { context, page } = await open("scenario=picker", { width: 1440 });
    await page.getByText("Вибрати всі").click();
    const selected = await page.getByTestId("picker-selected").innerText();
    const message = await page.getByTestId("live-channel-picker-message").innerText();
    await page.getByRole("searchbox").fill("Вітрина");
    const found = await page.locator('[data-testid="live-channel-picker-group"]').count();
    record(
      "picker: 32 channels, select-all stops at 24 with a message, search and operator names work",
      selected === "24" && /ліміт 24/.test(message) && found === 1,
      `selected=${selected} groupsAfterSearch=${found}`,
    );
    await context.close();
  }
} finally {
  await browser.close();
  await server.close();
}

writeFileSync(join(out, "acceptance-results.json"), JSON.stringify(results, null, 2));
const failed = results.filter((entry) => !entry.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
```
