import type { LayoutCatalogItem } from "./layout-catalog";

export interface SchemeNavigation {
  schemeEntry: boolean;
  editRequested: boolean;
  returnHref: string | null;
}

export function catalogReturnHref(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    value.length > 2048 ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\u0000-\u0020\u007f]/.test(value)
  ) {
    return null;
  }
  try {
    const url = new URL(value, "http://nexolab.invalid");
    return url.origin === "http://nexolab.invalid" && url.pathname === "/equipment-layouts" && !url.hash
      ? `${url.pathname}${url.search}`
      : null;
  } catch {
    return null;
  }
}

export function readSchemeNavigation(query: Record<string, string | string[] | undefined>): SchemeNavigation {
  const schemeEntry = query.tab === "scheme";
  return {
    schemeEntry,
    editRequested: schemeEntry && query.mode === "edit",
    returnHref: catalogReturnHref(query.returnTo),
  };
}

export function canEditCatalogScheme(
  item: LayoutCatalogItem,
  canEditDraft: boolean,
  canManageEquipment = false,
): boolean {
  return (
    canEditDraft &&
    (!(item.equipment.climateChamberId || item.equipment.nodeId) || canManageEquipment) &&
    item.equipment.lifecycleStatus !== "retired" &&
    item.kind === "ready" &&
    item.draft.image !== null
  );
}

export function schemeEntryHref(equipmentId: string, returnTo: string, editRequested: boolean): string {
  const query = new URLSearchParams({
    tab: "scheme",
    returnTo: catalogReturnHref(returnTo) ?? "/equipment-layouts",
  });
  if (editRequested) query.set("mode", "edit");
  return `/refrigeration/${encodeURIComponent(equipmentId)}?${query.toString()}`;
}
