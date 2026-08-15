export type TelemetryPointHierarchyIdentity = {
  id: string;
  label: string;
};

export type TelemetryPointDescriptor = {
  organizationId: string;
  laboratory: TelemetryPointHierarchyIdentity;
  zone: TelemetryPointHierarchyIdentity;
  equipmentType: TelemetryPointHierarchyIdentity;
  equipment: TelemetryPointHierarchyIdentity;
  nodeId: string;
  channelId: string;
  channelLabel: string;
  metric: string;
  metricLabel?: string;
  unit: string;
};

export type TelemetryPointBranchKind = "laboratory" | "zone" | "equipment-type" | "equipment";
export type TelemetryPointSelectionState = "checked" | "unchecked" | "mixed";

export type TelemetryPointLeafNode = {
  kind: "point";
  id: string;
  parentId: string;
  label: string;
  searchText: string;
  pointKey: string;
  point: TelemetryPointDescriptor;
};

export type TelemetryPointBranchNode = {
  kind: TelemetryPointBranchKind;
  id: string;
  parentId: string | null;
  label: string;
  searchText: string;
  children: TelemetryPointNode[];
  leafKeys: string[];
};

export type TelemetryPointNode = TelemetryPointBranchNode | TelemetryPointLeafNode;

export type TelemetryPointHierarchy = {
  organizationId: string;
  roots: TelemetryPointBranchNode[];
  orderedLeafKeys: string[];
  nodesById: ReadonlyMap<string, TelemetryPointNode>;
  nodeCount: number;
  leafCount: number;
  deduplicatedPointCount: number;
};

export type TelemetryPointSearchResult = {
  roots: TelemetryPointBranchNode[];
  visitedNodes: number;
  matchingLeafKeys: string[];
};

export type TelemetryPointTreeRow = {
  node: TelemetryPointNode;
  level: number;
};

export type TelemetryPointVisibleRows = {
  rows: TelemetryPointTreeRow[];
  truncated: boolean;
};

export type TelemetryPointSelectionResult = {
  selected: string[];
  changed: boolean;
  reason: "selected" | "removed" | "limit";
};

const LEVELS: Array<{
  kind: TelemetryPointBranchKind;
  identity: (point: TelemetryPointDescriptor) => TelemetryPointHierarchyIdentity;
}> = [
  { kind: "laboratory", identity: (point) => point.laboratory },
  { kind: "zone", identity: (point) => point.zone },
  { kind: "equipment-type", identity: (point) => point.equipmentType },
  { kind: "equipment", identity: (point) => point.equipment },
];

const DEFAULT_VISIBLE_NODE_LIMIT = 400;
const MAX_VISIBLE_NODE_LIMIT = 2_000;

function compareText(left: string, right: string): number {
  return left.localeCompare(right, "uk-UA", { numeric: true, sensitivity: "base" });
}

function normalizeSearch(value: string): string {
  return value.trim().toLocaleLowerCase("uk-UA");
}

function required(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`TelemetryPointSelector requires ${field}.`);
  return normalized;
}

function normalizeIdentity(
  identity: TelemetryPointHierarchyIdentity,
  field: string,
): TelemetryPointHierarchyIdentity {
  return {
    id: required(identity.id, `${field}.id`),
    label: required(identity.label, `${field}.label`),
  };
}

function normalizePoint(point: TelemetryPointDescriptor): TelemetryPointDescriptor {
  return {
    organizationId: required(point.organizationId, "organizationId"),
    laboratory: normalizeIdentity(point.laboratory, "laboratory"),
    zone: normalizeIdentity(point.zone, "zone"),
    equipmentType: normalizeIdentity(point.equipmentType, "equipmentType"),
    equipment: normalizeIdentity(point.equipment, "equipment"),
    nodeId: required(point.nodeId, "nodeId"),
    channelId: required(point.channelId, "channelId"),
    channelLabel: required(point.channelLabel, "channelLabel"),
    metric: required(point.metric, "metric"),
    metricLabel: point.metricLabel?.trim() || undefined,
    unit: required(point.unit, "unit"),
  };
}

function encoded(parts: readonly string[]): string {
  return parts.map((part) => encodeURIComponent(part)).join("|");
}

export function telemetryPointSelectionKey(point: TelemetryPointDescriptor): string {
  return encoded([point.nodeId, point.equipment.id, point.channelId, point.metric, point.unit]);
}

function branchId(
  organizationId: string,
  kind: TelemetryPointBranchKind,
  path: readonly string[],
): string {
  return `telemetry-selection:${kind}:${encoded([organizationId, ...path])}`;
}

function leafId(organizationId: string, pointKey: string): string {
  return `telemetry-selection:point:${encoded([organizationId, pointKey])}`;
}

function pointSearchText(point: TelemetryPointDescriptor): string {
  return normalizeSearch(
    [
      point.laboratory.id,
      point.laboratory.label,
      point.zone.id,
      point.zone.label,
      point.equipmentType.id,
      point.equipmentType.label,
      point.equipment.id,
      point.equipment.label,
      point.nodeId,
      point.channelId,
      point.channelLabel,
      point.metric,
      point.metricLabel ?? "",
      point.unit,
    ].join(" "),
  );
}

function pointLabel(point: TelemetryPointDescriptor): string {
  return `${point.channelLabel} · ${point.metricLabel ?? point.metric} · ${point.unit}`;
}

function comparePoints(left: TelemetryPointDescriptor, right: TelemetryPointDescriptor): number {
  for (const level of LEVELS) {
    const leftIdentity = level.identity(left);
    const rightIdentity = level.identity(right);
    const label = compareText(leftIdentity.label, rightIdentity.label);
    if (label !== 0) return label;
    const id = compareText(leftIdentity.id, rightIdentity.id);
    if (id !== 0) return id;
  }
  return (
    compareText(left.channelLabel, right.channelLabel) ||
    compareText(left.channelId, right.channelId) ||
    compareText(left.metricLabel ?? left.metric, right.metricLabel ?? right.metric) ||
    compareText(left.metric, right.metric) ||
    compareText(left.unit, right.unit) ||
    compareText(left.nodeId, right.nodeId)
  );
}

function collectLeafKeys(nodes: readonly TelemetryPointNode[]): string[] {
  return nodes.flatMap((node) => (node.kind === "point" ? [node.pointKey] : node.leafKeys));
}

function buildLevel(
  organizationId: string,
  points: readonly TelemetryPointDescriptor[],
  levelIndex: number,
  path: readonly string[],
  parentId: string | null,
): TelemetryPointNode[] {
  if (levelIndex >= LEVELS.length) {
    return points.map((point) => {
      const pointKey = telemetryPointSelectionKey(point);
      return {
        kind: "point" as const,
        id: leafId(organizationId, pointKey),
        parentId: parentId ?? "",
        label: pointLabel(point),
        searchText: pointSearchText(point),
        pointKey,
        point,
      };
    });
  }

  const level = LEVELS[levelIndex];
  const grouped = new Map<string, TelemetryPointDescriptor[]>();
  for (const point of points) {
    const identity = level.identity(point);
    const group = grouped.get(identity.id) ?? [];
    group.push(point);
    grouped.set(identity.id, group);
  }

  return [...grouped.entries()]
    .map(([identityId, group]) => {
      const sortedGroup = [...group].sort(comparePoints);
      const identity = level.identity(sortedGroup[0]);
      const id = branchId(organizationId, level.kind, [...path, identityId]);
      const children = buildLevel(
        organizationId,
        sortedGroup,
        levelIndex + 1,
        [...path, identityId],
        id,
      );
      return {
        kind: level.kind,
        id,
        parentId,
        label: identity.label,
        searchText: normalizeSearch(`${identity.id} ${identity.label}`),
        children,
        leafKeys: collectLeafKeys(children),
      } satisfies TelemetryPointBranchNode;
    })
    .sort((left, right) => compareText(left.label, right.label) || compareText(left.id, right.id));
}

function indexNodes(nodes: readonly TelemetryPointNode[], target: Map<string, TelemetryPointNode>): void {
  for (const node of nodes) {
    target.set(node.id, node);
    if (node.kind !== "point") indexNodes(node.children, target);
  }
}

export function buildTelemetryPointHierarchy(
  points: readonly TelemetryPointDescriptor[],
  organizationId: string,
): TelemetryPointHierarchy {
  const scopedOrganizationId = required(organizationId, "organizationId");
  const scoped = points
    .map(normalizePoint)
    .filter((point) => point.organizationId === scopedOrganizationId)
    .sort(comparePoints);
  const uniqueByKey = new Map<string, TelemetryPointDescriptor>();

  for (const point of scoped) {
    const key = telemetryPointSelectionKey(point);
    if (!uniqueByKey.has(key)) uniqueByKey.set(key, point);
  }

  const uniquePoints = [...uniqueByKey.values()].sort(comparePoints);
  const roots = buildLevel(scopedOrganizationId, uniquePoints, 0, [], null).filter(
    (node): node is TelemetryPointBranchNode => node.kind === "laboratory",
  );
  const nodesById = new Map<string, TelemetryPointNode>();
  indexNodes(roots, nodesById);

  return {
    organizationId: scopedOrganizationId,
    roots,
    orderedLeafKeys: uniquePoints.map(telemetryPointSelectionKey),
    nodesById,
    nodeCount: nodesById.size,
    leafCount: uniquePoints.length,
    deduplicatedPointCount: scoped.length - uniquePoints.length,
  };
}

function cloneFilteredBranch(
  node: TelemetryPointBranchNode,
  children: TelemetryPointNode[],
): TelemetryPointBranchNode {
  return {
    ...node,
    children,
    leafKeys: collectLeafKeys(children),
  };
}

export function searchTelemetryPointHierarchy(
  hierarchy: TelemetryPointHierarchy,
  query: string,
): TelemetryPointSearchResult {
  const normalizedQuery = normalizeSearch(query);
  if (!normalizedQuery) {
    return {
      roots: hierarchy.roots,
      visitedNodes: 0,
      matchingLeafKeys: hierarchy.orderedLeafKeys,
    };
  }

  let visitedNodes = 0;

  const visit = (node: TelemetryPointNode): TelemetryPointNode | null => {
    visitedNodes += 1;
    if (node.searchText.includes(normalizedQuery)) return node;
    if (node.kind === "point") return null;
    const children = node.children
      .map(visit)
      .filter((child): child is TelemetryPointNode => child !== null);
    return children.length > 0 ? cloneFilteredBranch(node, children) : null;
  };

  const roots = hierarchy.roots
    .map(visit)
    .filter((node): node is TelemetryPointBranchNode => node?.kind === "laboratory");

  return {
    roots,
    visitedNodes,
    matchingLeafKeys: collectLeafKeys(roots),
  };
}

export function canonicalizeTelemetryPointSelection(
  hierarchy: TelemetryPointHierarchy,
  selected: readonly string[],
): string[] {
  const selectedSet = new Set(selected);
  return hierarchy.orderedLeafKeys.filter((key) => selectedSet.has(key));
}

export function telemetryPointNodeSelectionState(
  node: TelemetryPointNode,
  selected: ReadonlySet<string>,
): TelemetryPointSelectionState {
  const leafKeys = node.kind === "point" ? [node.pointKey] : node.leafKeys;
  const selectedCount = leafKeys.reduce((count, key) => count + (selected.has(key) ? 1 : 0), 0);
  if (selectedCount === 0) return "unchecked";
  if (selectedCount === leafKeys.length) return "checked";
  return "mixed";
}

function normalizedSelectionLimit(limit: number): number {
  if (!Number.isFinite(limit)) return Number.POSITIVE_INFINITY;
  return Math.max(0, Math.floor(limit));
}

export function toggleTelemetryPointNodeSelection(
  hierarchy: TelemetryPointHierarchy,
  node: TelemetryPointNode,
  selected: readonly string[],
  limit = Number.POSITIVE_INFINITY,
): TelemetryPointSelectionResult {
  const current = canonicalizeTelemetryPointSelection(hierarchy, selected);
  const currentSet = new Set(current);
  const nodeKeys = node.kind === "point" ? [node.pointKey] : node.leafKeys;
  const allSelected = nodeKeys.length > 0 && nodeKeys.every((key) => currentSet.has(key));

  if (allSelected) {
    const remove = new Set(nodeKeys);
    const next = current.filter((key) => !remove.has(key));
    return { selected: next, changed: next.length !== current.length, reason: "removed" };
  }

  const additions = nodeKeys.filter((key) => !currentSet.has(key));
  const maximum = normalizedSelectionLimit(limit);
  if (current.length + additions.length > maximum) {
    return { selected: current, changed: false, reason: "limit" };
  }

  for (const key of additions) currentSet.add(key);
  const next = hierarchy.orderedLeafKeys.filter((key) => currentSet.has(key));
  return { selected: next, changed: additions.length > 0, reason: "selected" };
}

export function collectTelemetryPointBranchIds(hierarchy: TelemetryPointHierarchy): string[] {
  return [...hierarchy.nodesById.values()]
    .filter((node): node is TelemetryPointBranchNode => node.kind !== "point")
    .map((node) => node.id);
}

export function flattenTelemetryPointHierarchy(
  roots: readonly TelemetryPointBranchNode[],
  expandedIds: ReadonlySet<string>,
  options: { forceExpanded?: boolean; maxVisibleNodes?: number } = {},
): TelemetryPointVisibleRows {
  const requestedLimit = options.maxVisibleNodes ?? DEFAULT_VISIBLE_NODE_LIMIT;
  const maximum = Math.min(
    MAX_VISIBLE_NODE_LIMIT,
    Math.max(1, Math.floor(Number.isFinite(requestedLimit) ? requestedLimit : DEFAULT_VISIBLE_NODE_LIMIT)),
  );
  const rows: TelemetryPointTreeRow[] = [];
  let truncated = false;

  const visit = (nodes: readonly TelemetryPointNode[], level: number): void => {
    for (const node of nodes) {
      if (rows.length >= maximum) {
        truncated = true;
        return;
      }
      rows.push({ node, level });
      if (
        node.kind !== "point" &&
        (options.forceExpanded === true || expandedIds.has(node.id))
      ) {
        visit(node.children, level + 1);
        if (truncated) return;
      }
    }
  };

  visit(roots, 1);
  return { rows, truncated };
}
