import { createGzip } from "node:zlib";
import { pipeline } from "node:stream/promises";
import { createReadStream } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import { PassThrough } from "node:stream";
import { spawn } from "node:child_process";

import { chromium } from "playwright";

const DIST = "/tmp/nexolab-chart-benchmark-dist";
const BASELINE_DIST = "/tmp/nexolab-chart-benchmark-baseline";
const BASE_URL = "http://127.0.0.1:4173";

async function runViteBuild(config) {
  await new Promise((resolve, reject) => {
    const build = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--config", config], {
      stdio: "inherit",
    });
    build.once("error", reject);
    build.once("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Vite build failed for ${config} with exit code ${code}`));
    });
  });
}

async function files(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (
    await Promise.all(
      entries.map((entry) => {
        const path = `${directory}/${entry.name}`;
        return entry.isDirectory() ? files(path) : Promise.resolve([path]);
      }),
    )
  ).flat();
}

async function gzipSize(path) {
  let bytes = 0;
  const counter = new PassThrough();
  counter.on("data", (chunk) => {
    bytes += chunk.length;
  });
  await pipeline(createReadStream(path), createGzip({ level: 9 }), counter);
  return bytes;
}

async function javascriptBundle(directory) {
  const javascript = (await files(directory)).filter((path) => path.endsWith(".js"));
  const items = await Promise.all(
    javascript.map(async (path) => ({
      file: path.slice(directory.length + 1),
      bytes: (await stat(path)).size,
      gzipBytes: await gzipSize(path),
    })),
  );
  return {
    javascriptFiles: items,
    totalBytes: items.reduce((sum, item) => sum + item.bytes, 0),
    totalGzipBytes: items.reduce((sum, item) => sum + item.gzipBytes, 0),
  };
}

async function bundleEvidence() {
  const renderer = await javascriptBundle(DIST);
  const domainBaseline = await javascriptBundle(BASELINE_DIST);
  return {
    renderer,
    domainBaseline,
    rendererDeltaBytes: renderer.totalBytes - domainBaseline.totalBytes,
    rendererDeltaGzipBytes: renderer.totalGzipBytes - domainBaseline.totalGzipBytes,
  };
}

async function waitForServer(processHandle) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (processHandle.exitCode !== null) throw new Error("Vite preview exited before benchmark start");
    try {
      const response = await fetch(BASE_URL);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Timed out waiting for the local benchmark bundle");
}

await runViteBuild("tests/chart-benchmark/vite.config.ts");
await runViteBuild("tests/chart-benchmark/vite.baseline.config.ts");

const preview = spawn(
  process.execPath,
  [
    "node_modules/vite/bin/vite.js",
    "preview",
    "--config",
    "tests/chart-benchmark/vite.config.ts",
    "--host",
    "127.0.0.1",
    "--port",
    "4173",
  ],
  { stdio: ["ignore", "pipe", "pipe"] },
);

let browser;
try {
  await waitForServer(preview);
  browser = await chromium.launch({ headless: true, args: ["--js-flags=--expose-gc"] });
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  const publicRequests = [];
  const allRequests = [];
  page.on("request", (request) => {
    const url = request.url();
    allRequests.push(url);
    if (!url.startsWith(BASE_URL)) publicRequests.push(url);
  });
  await page.route("**/*", async (route) => {
    if (!route.request().url().startsWith(BASE_URL)) return route.abort("blockedbyclient");
    return route.continue();
  });

  await page.setViewportSize({ width: 1_440, height: 1_000 });
  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await page.waitForFunction(() => Boolean(window.nexolabChartBenchmark));

  const oneBy240 = await page.evaluate(() => window.nexolabChartBenchmark.runInitial(1, 10));
  const eightBy240 = await page.evaluate(() => window.nexolabChartBenchmark.runInitial(8, 10));
  const synchronizedGroups = await page.evaluate(() => window.nexolabChartBenchmark.runSynchronizedGroups());
  const gapsAndEvidence = await page.evaluate(() => window.nexolabChartBenchmark.runGapAndEvidence());
  const incremental = await page.evaluate(() => window.nexolabChartBenchmark.runIncremental(100));
  const resize = await page.evaluate(() => window.nexolabChartBenchmark.runResize());
  const remount = await page.evaluate(() => window.nexolabChartBenchmark.runRemount());

  const cdp = await context.newCDPSession(page);
  await page.evaluate(() => globalThis.gc?.());
  const heapBefore = await cdp.send("Runtime.getHeapUsage");
  const longLived = await page.evaluate(() => window.nexolabChartBenchmark.runLongLived(1_000));
  await page.evaluate(() => globalThis.gc?.());
  const heapAfter = await cdp.send("Runtime.getHeapUsage");

  const responsive = [];
  for (const viewport of [
    { name: "narrow-mobile", width: 360, height: 800 },
    { name: "normal-desktop", width: 1_280, height: 900 },
    { name: "desktop-1440", width: 1_440, height: 1_000 },
    { name: "operator-1920", width: 1_920, height: 1_080 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.evaluate(() => window.nexolabChartBenchmark.runInitial(8, 1));
    const result = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      legendButtons: document.querySelectorAll(".legend-item").length,
      chartCanvases: document.querySelectorAll("canvas").length,
    }));
    responsive.push({ ...viewport, ...result, horizontalOverflow: result.scrollWidth > result.clientWidth });
  }

  await page.keyboard.press("Tab");
  const accessibility = await page.evaluate(() => {
    const focused = document.activeElement;
    const focusStyle = focused ? getComputedStyle(focused) : null;
    return {
      chartControlButtons: document.querySelectorAll(".actions button").length,
      legendButtons: document.querySelectorAll(".legend-item").length,
      screenReaderSummary: document.querySelector(".sr-only")?.textContent ?? "",
      exactInspector: document.querySelector(".benchmark-inspector")?.textContent ?? "",
      rendererAriaLabels: [...document.querySelectorAll("canvas[aria-label], svg[aria-label]")].map((item) =>
        item.getAttribute("aria-label"),
      ),
      visibleKeyboardFocus:
        focused instanceof HTMLButtonElement &&
        (focusStyle?.outlineStyle !== "none" || focusStyle?.boxShadow !== "none"),
      reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
      nonColorStateText: document.body.textContent?.includes("valid · live") ?? false,
    };
  });

  const output = {
    generatedAt: new Date().toISOString(),
    environment: {
      userAgent: await page.evaluate(() => navigator.userAgent),
      runtimeArchitecture: process.arch,
      viewportBenchmark: "Chromium headless in pinned Playwright container; classify the host separately",
    },
    scenarios: {
      oneBy240,
      eightBy240,
      synchronizedGroups,
      gapsAndEvidence,
      incremental,
      resize,
      remount,
      longLived,
    },
    memory: {
      usedBytesBefore: heapBefore.usedSize,
      usedBytesAfter: heapAfter.usedSize,
      deltaBytes: heapAfter.usedSize - heapBefore.usedSize,
      note: "Single forced-GC Chromium observation; trend evidence, not a proof of zero leaks.",
    },
    responsive,
    accessibility,
    network: {
      requestCount: allRequests.length,
      publicRequestCount: publicRequests.length,
      publicRequests,
      allRequests: [...new Set(allRequests)],
      disconnectedGate: publicRequests.length === 0,
    },
    bundle: await bundleEvidence(),
  };
  console.log(`NEXOLAB_CHART_BENCHMARK_RESULT=${JSON.stringify(output)}`);
} finally {
  if (browser) await browser.close();
  preview.kill("SIGTERM");
}
