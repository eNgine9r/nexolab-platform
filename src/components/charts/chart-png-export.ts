import type { ChartRendererAdapter } from "@/features/charts/renderer-adapter";

function slug(value: string): string {
  const cleaned = value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return cleaned.slice(0, 60) || "chart";
}

/** `nexolab-<title>-20261122T053000Z.png`; the UTC stamp keeps names unique and sortable. */
export function chartPngFilename(title: string, now: Date = new Date()): string {
  const stamp = now
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z");
  return `nexolab-${slug(title)}-${stamp}.png`;
}

/**
 * Downloads the visible plot as PNG using the renderer that is already mounted (local Canvas, no
 * network, no telemetry access). Returns false when the renderer cannot export.
 */
export function downloadChartPng(
  adapter: Pick<ChartRendererAdapter, "exportImage">,
  title: string,
  doc: Document = document,
  now: Date = new Date(),
): boolean {
  const url = adapter.exportImage?.();
  if (!url) return false;
  const link = doc.createElement("a");
  link.href = url;
  link.download = chartPngFilename(title, now);
  link.rel = "noopener";
  doc.body.append(link);
  link.click();
  link.remove();
  return true;
}
