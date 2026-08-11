import type {
  ChartAlarmRegion,
  ChartCursorInspection,
  ChartEventMarker,
  ChartSeries,
  ChartThreshold,
  ChartXDomain,
} from "./domain";

export interface ChartRendererInitOptions {
  container: HTMLElement;
  renderer: "canvas" | "svg";
  reducedMotion: boolean;
  maximumLivePoints?: number;
  onCursor: (inspection: ChartCursorInspection | null) => void;
  onXDomainChange: (domain: ChartXDomain) => void;
}

export interface ChartRendererScene {
  series: readonly ChartSeries[];
  xDomain: ChartXDomain;
  thresholds?: readonly ChartThreshold[];
  events?: readonly ChartEventMarker[];
  alarmRegions?: readonly ChartAlarmRegion[];
}

export interface ChartRendererAdapter {
  initialize(options: ChartRendererInitOptions): void;
  setScene(scene: ChartRendererScene): void;
  appendLiveTail(
    seriesKey: string,
    points: readonly { segmentId: string; point: ChartSeries["segments"][number]["points"][number] }[],
  ): void;
  setSharedCursor(timestampMs: number | null): void;
  setSharedXDomain(domain: ChartXDomain): void;
  resize(): void;
  resetZoom(): void;
  dispose(): void;
  isDisposed(): boolean;
}

export type ChartViewMode = "live_follow" | "paused";

export interface ChartInteractionContract {
  viewMode: ChartViewMode;
  zoomEnabled: boolean;
  panEnabled: boolean;
  fullscreenEnabled: boolean;
  exportEnabled: boolean;
  legendMode: "show_hide" | "show_hide_and_solo";
}
