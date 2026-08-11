import { createBenchmarkScene } from "@/features/charts/fixtures";

const root = document.querySelector<HTMLElement>("#baseline-root");
if (!root) throw new Error("Baseline root is missing");
const scene = createBenchmarkScene(8, { withGap: true, withEvidence: true });
root.textContent = `${scene.series.length} series · ${scene.series.flatMap((series) => series.segments.flatMap((segment) => segment.points)).length} points`;
