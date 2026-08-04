import type { EquipmentLifecycleStatus, RefrigerationEquipment } from "@/data/refrigeration";
import type {
  LayoutRepositoryError,
  PublishedLayoutRevision,
  RefrigerationLayoutDraft,
  RefrigerationLayoutRepository,
} from "@/features/refrigeration/layout-repository";
import type { RefrigerationEquipmentRepository } from "@/features/refrigeration/equipment-repository";

export type LayoutCatalogState =
  | "published-current"
  | "published-with-draft"
  | "draft-only"
  | "no-image"
  | "empty"
  | "failed";

export type LayoutCatalogFilters = {
  search: string;
  laboratory: string;
  zone: string;
  chamber: string;
  lifecycle: EquipmentLifecycleStatus | "all";
  layout: LayoutCatalogState | "all";
};

export type LayoutCatalogReadyItem = {
  kind: "ready";
  equipment: RefrigerationEquipment;
  draft: RefrigerationLayoutDraft;
  published: PublishedLayoutRevision | null;
  layoutState: Exclude<LayoutCatalogState, "failed">;
};

export type LayoutCatalogFailedItem = {
  kind: "failed";
  equipment: RefrigerationEquipment;
  layoutState: "failed";
  error: string;
};

export type LayoutCatalogItem = LayoutCatalogReadyItem | LayoutCatalogFailedItem;

export type LayoutCatalogOptions = {
  laboratories: string[];
  zones: string[];
  chambers: string[];
};

export type LoadLayoutCatalogOptions = {
  equipmentRepository: RefrigerationEquipmentRepository;
  layoutRepository: RefrigerationLayoutRepository;
  concurrency?: number;
  signal?: AbortSignal;
};

const DEFAULT_CONCURRENCY = 4;
const MAX_CONCURRENCY = 8;

export function defaultLayoutCatalogFilters(): LayoutCatalogFilters {
  return {
    search: "",
    laboratory: "all",
    zone: "all",
    chamber: "all",
    lifecycle: "all",
    layout: "all",
  };
}

export function deriveLayoutCatalogState(
  draft: RefrigerationLayoutDraft,
  published: PublishedLayoutRevision | null,
): Exclude<LayoutCatalogState, "failed"> {
  if (published) {
    return layoutsMatch(draft, published) ? "published-current" : "published-with-draft";
  }
  if (!draft.imageId && draft.placements.length === 0) return "empty";
  if (!draft.imageId) return "no-image";
  return "draft-only";
}

export function layoutsMatch(
  draft: RefrigerationLayoutDraft,
  published: PublishedLayoutRevision,
): boolean {
  if (draft.imageId !== published.imageId) return false;
  if (draft.placements.length !== published.placements.length) return false;

  const publishedBySensor = new Map(
    published.placements.map((placement) => [placement.sensorId, placement] as const),
  );
  return draft.placements.every((placement) => {
    const publishedPlacement = publishedBySensor.get(placement.sensorId);
    return (
      publishedPlacement !== undefined &&
      publishedPlacement.x === placement.x &&
      publishedPlacement.y === placement.y
    );
  });
}

export function sortLayoutCatalogItems(items: readonly LayoutCatalogItem[]): LayoutCatalogItem[] {
  return [...items].sort((first, second) => {
    const code = compareText(first.equipment.code, second.equipment.code);
    return code === 0 ? compareText(first.equipment.name, second.equipment.name) : code;
  });
}

export function filterLayoutCatalog(
  items: readonly LayoutCatalogItem[],
  filters: LayoutCatalogFilters,
): LayoutCatalogItem[] {
  const search = normalizeSearch(filters.search);
  return sortLayoutCatalogItems(
    items.filter((item) => {
      const equipment = item.equipment;
      const haystack = normalizeSearch(
        [
          equipment.code,
          equipment.name,
          equipment.location,
          equipment.laboratory,
          equipment.zone,
          equipment.climateChamberId,
          equipment.type,
          equipment.manufacturer,
          equipment.model,
        ]
          .filter(Boolean)
          .join(" "),
      );
      return (
        (!search || haystack.includes(search)) &&
        (filters.laboratory === "all" || equipment.laboratory === filters.laboratory) &&
        (filters.zone === "all" || equipment.zone === filters.zone) &&
        (filters.chamber === "all" || equipment.climateChamberId === filters.chamber) &&
        (filters.lifecycle === "all" || equipment.lifecycleStatus === filters.lifecycle) &&
        (filters.layout === "all" || item.layoutState === filters.layout)
      );
    }),
  );
}

export function collectLayoutCatalogOptions(items: readonly LayoutCatalogItem[]): LayoutCatalogOptions {
  return {
    laboratories: uniqueSorted(items.map((item) => item.equipment.laboratory)),
    zones: uniqueSorted(items.map((item) => item.equipment.zone)),
    chambers: uniqueSorted(items.map((item) => item.equipment.climateChamberId)),
  };
}

export async function loadLayoutCatalog({
  equipmentRepository,
  layoutRepository,
  concurrency = DEFAULT_CONCURRENCY,
  signal,
}: LoadLayoutCatalogOptions): Promise<LayoutCatalogItem[]> {
  throwIfAborted(signal);
  const equipment = await equipmentRepository.list();
  throwIfAborted(signal);

  const sortedEquipment = [...equipment].sort((first, second) => {
    const code = compareText(first.code, second.code);
    return code === 0 ? compareText(first.name, second.name) : code;
  });
  const items = new Array<LayoutCatalogItem>(sortedEquipment.length);
  const workerCount = Math.min(normalizeConcurrency(concurrency), Math.max(1, sortedEquipment.length));
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (true) {
      throwIfAborted(signal);
      const index = nextIndex;
      nextIndex += 1;
      if (index >= sortedEquipment.length) return;

      const current = sortedEquipment[index];
      const [draftResult, publishedResult] = await Promise.all([
        layoutRepository.getDraft(current.id),
        layoutRepository.getPublished(current.id),
      ]);
      throwIfAborted(signal);

      if (!draftResult.ok || !publishedResult.ok) {
        items[index] = {
          kind: "failed",
          equipment: current,
          layoutState: "failed",
          error: layoutRepositoryErrorMessage(
            !draftResult.ok ? draftResult.error : publishedResult.error,
          ),
        };
        continue;
      }

      items[index] = {
        kind: "ready",
        equipment: current,
        draft: draftResult.value,
        published: publishedResult.value,
        layoutState: deriveLayoutCatalogState(draftResult.value, publishedResult.value),
      };
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  throwIfAborted(signal);
  return items;
}

export function isLayoutCatalogAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function layoutRepositoryErrorMessage(error: LayoutRepositoryError): string {
  switch (error.code) {
    case "LAYOUT_NOT_FOUND":
      return "Чернетку схеми обладнання не знайдено.";
    case "LAYOUT_VERSION_CONFLICT":
      return `Версія схеми змінилася: очікувалася v${error.expectedVersion}, актуальна v${error.actualVersion}.`;
    case "LAYOUT_REVISION_NOT_FOUND":
      return "Запитану ревізію схеми не знайдено.";
    case "LAYOUT_VALIDATION_FAILED":
      return error.issues[0]?.message ?? "Сервер схем повернув помилку перевірки.";
  }
}

function normalizeConcurrency(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_CONCURRENCY;
  return Math.min(MAX_CONCURRENCY, Math.max(1, Math.floor(value)));
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw new DOMException("Layout catalog load aborted", "AbortError");
}

function uniqueSorted(values: readonly (string | null)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value?.trim())))]
    .sort(compareText);
}

function compareText(first: string, second: string): number {
  return first.localeCompare(second, "uk", { numeric: true, sensitivity: "base" });
}

function normalizeSearch(value: string): string {
  return value.trim().toLocaleLowerCase("uk");
}
