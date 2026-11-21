interface SparklineProps {
  points: number[];
  stroke?: string;
}

function createPath(input: number[]) {
  const points = input.filter((point) => Number.isFinite(point));
  if (points.length === 0) return "";
  // A single point has no span on the x axis; draw it flat instead of producing NaN.
  if (points.length === 1) return "M0 16 L88 16";
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = Math.max(max - min, 1);
  return points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 88;
      const y = 26 - ((point - min) / span) * 20;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export function Sparkline({ points, stroke = "#0077ff" }: SparklineProps) {
  const path = createPath(points);
  return (
    <svg viewBox="0 0 88 30" className="h-7 w-[88px]" aria-hidden="true">
      <path d="M0 26H88" stroke="rgba(148,163,184,.18)" strokeWidth="1" />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
