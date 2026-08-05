import {
  LIVE_DASHBOARD_DESCRIPTION_MAX_LENGTH,
  LIVE_DASHBOARD_MAX_ITEMS,
  LIVE_DASHBOARD_NAME_MAX_LENGTH,
  type LiveDashboard,
  type LiveDashboardDraft,
  type LiveDashboardDraftItem,
  type LiveDashboardInventoryFilters,
  type LiveDashboardInventoryItem,
  type LiveDashboardValidation,
  type LiveDashboardWrite,
} from "./types";

const SERIES_COLORS = [
  "#00C6E0",
  "#7ED321",
  "#0077FF",
  "#A855F7",
  "#F5B301",
  "#14B8A6",
  "#F97316",
  "#F43F5E",
] as const;

export function dashboardItemIdentity(item: Pick<LiveDashboardDraftItem, "channel_id" | "metric">): string {
  return `${encodeURIComponent(item.channel_id)}|${encodeURIComponent(item.metric)}`;
}

export function liveDashboardEtag(version: number): string {
  return `W/"live-dashboard-v${version}"`;
}

export function createEmptyLiveDashboardDraft(): LiveDashboardDraft {
  return {
    id: null,
    name: "",
    description: "",
    refresh_seconds: 5,
    time_window: "15m",
    items: [],
    version: null,
    etag: null,
  };
}

export function dashboardToDraft(dashboard: LiveDashboard, etag = liveDashboardEtag(dashboard.version)): LiveDashboardDraft {
  return {
    id: dashboard.id,
    name: dashboard.name,
    description: dashboard.description ?? "",
    refresh_seconds: dashboard.refresh_seconds,
    time_window: dashboard.time_window,
    items: dashboard.items.map((item) => ({
      channel_id: item.channel_id,
      metric: item.metric,
      visualization: item.visualization,
      color: item.color,
      display_unit: item.display_unit,
      native_unit: item.native_unit,
      node_id: null,
      equipment_id: null,
      source: null,
    })),
    version: dashboard.version,
    etag,
  };
}

export function duplicateDashboardDraft(dashboard: LiveDashboard): LiveDashboardDraft {
  const draft = dashboardToDraft(dashboard);
  return {
    ...draft,
    id: null,
    name: `${dashboard.name} — копія`.slice(0, LIVE_DASHBOARD_NAME_MAX_LENGTH),
    version: null,
    etag: null,
  };
}

export function draftToWrite(draft: LiveDashboardDraft): LiveDashboardWrite {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    refresh_seconds: draft.refresh_seconds,
    time_window: draft.time_window,
    items: draft.items.map((item) => ({
      channel_id: item.channel_id,
      metric: item.metric,
      visualization: item.visualization,
      color: item.color,
      display_unit: item.display_unit || null,
    })),
  };
}

export function validateLiveDashboardDraft(draft: LiveDashboardDraft): LiveDashboardValidation {
  const issues: string[] = [];
  const name = draft.name.trim();
  const description = draft.description.trim();

  if (!name) issues.push("Вкажіть назву Live Dashboard.");
  if (name.length > LIVE_DASHBOARD_NAME_MAX_LENGTH) {
    issues.push(`Назва не може перевищувати ${LIVE_DASHBOARD_NAME_MAX_LENGTH} символів.`);
  }
  if (description.length > LIVE_DASHBOARD_DESCRIPTION_MAX_LENGTH) {
    issues.push(`Опис не може перевищувати ${LIVE_DASHBOARD_DESCRIPTION_MAX_LENGTH} символи.`);
  }
  if (draft.items.length === 0) issues.push("Додайте щонайменше один канал.");
  if (draft.items.length > LIVE_DASHBOARD_MAX_ITEMS) {
    issues.push(`Dashboard може містити не більше ${LIVE_DASHBOARD_MAX_ITEMS} каналів.`);
  }

  const identities = draft.items.map(dashboardItemIdentity);
  if (new Set(identities).size !== identities.length) {
    issues.push("Один канал і показник не можна додати двічі.");
  }

  draft.items.forEach((item, index) => {
    if (!item.channel_id.trim() || !item.metric.trim()) {
      issues.push(`Елемент ${index + 1} не має каналу або показника.`);
    }
    if (item.display_unit && item.display_unit !== item.native_unit) {
      issues.push(`Для ${item.channel_id} дозволена лише базова одиниця ${item.native_unit}.`);
    }
    if (item.color && !/^#[0-9A-Fa-f]{6}$/.test(item.color)) {
      issues.push(`Колір ${item.channel_id} має бути у форматі #RRGGBB.`);
    }
  });

  return { valid: issues.length === 0, issues };
}

export function addDashboardDraftItem(
  draft: LiveDashboardDraft,
  inventory: LiveDashboardInventoryItem,
): { draft: LiveDashboardDraft; added: boolean; reason: "added" | "duplicate" | "limit" } {
  const candidate: LiveDashboardDraftItem = {
    channel_id: inventory.channel_id,
    metric: inventory.metric,
    visualization: "line",
    color: SERIES_COLORS[draft.items.length % SERIES_COLORS.length],
    display_unit: inventory.native_unit,
    native_unit: inventory.native_unit,
    node_id: inventory.node_id,
    equipment_id: inventory.equipment_id,
    source: inventory.source,
  };
  const identity = dashboardItemIdentity(candidate);
  if (draft.items.some((item) => dashboardItemIdentity(item) === identity)) {
    return { draft, added: false, reason: "duplicate" };
  }
  if (draft.items.length >= LIVE_DASHBOARD_MAX_ITEMS) {
    return { draft, added: false, reason: "limit" };
  }
  return {
    draft: { ...draft, items: [...draft.items, candidate] },
    added: true,
    reason: "added",
  };
}

export function removeDashboardDraftItem(draft: LiveDashboardDraft, index: number): LiveDashboardDraft {
  return { ...draft, items: draft.items.filter((_, itemIndex) => itemIndex !== index) };
}

export function moveDashboardDraftItem(
  draft: LiveDashboardDraft,
  index: number,
  direction: -1 | 1,
): LiveDashboardDraft {
  const nextIndex = index + direction;
  if (index < 0 || index >= draft.items.length || nextIndex < 0 || nextIndex >= draft.items.length) {
    return draft;
  }
  const items = [...draft.items];
  [items[index], items[nextIndex]] = [items[nextIndex], items[index]];
  return { ...draft, items };
}

export function defaultLiveDashboardInventoryFilters(): LiveDashboardInventoryFilters {
  return {
    search: "",
    node_id: "all",
    equipment_id: "all",
    metric: "all",
    quality: "all",
    alarm: "all",
  };
}

export function filterLiveDashboardInventory(
  inventory: readonly LiveDashboardInventoryItem[],
  filters: LiveDashboardInventoryFilters,
): LiveDashboardInventoryItem[] {
  const search = filters.search.trim().toLocaleLowerCase("uk-UA");
  return inventory.filter((item) => {
    if (filters.node_id !== "all" && item.node_id !== filters.node_id) return false;
    if (filters.equipment_id !== "all" && item.equipment_id !== filters.equipment_id) return false;
    if (filters.metric !== "all" && item.metric !== filters.metric) return false;
    if (filters.quality !== "all" && item.quality !== filters.quality) return false;
    if (filters.alarm === "active" && item.alarm === null) return false;
    if (filters.alarm === "none" && item.alarm !== null) return false;
    if (filters.alarm === "capable" && item.alarm === null) return false;
    if (!search) return true;
    return [
      item.node_id,
      item.equipment_id,
      item.channel_id,
      item.metric,
      item.native_unit,
      item.source,
    ].some((value) => value.toLocaleLowerCase("uk-UA").includes(search));
  });
}

export function timeWindowMilliseconds(window: LiveDashboardDraft["time_window"]): number {
  const multipliers: Record<LiveDashboardDraft["time_window"], number> = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "24h": 24 * 60 * 60_000,
    "7d": 7 * 24 * 60 * 60_000,
  };
  return multipliers[window];
}
