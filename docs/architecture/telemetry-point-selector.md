# TelemetryPointSelector architecture

## Decision

NEXOLAB uses a reusable, descriptor-driven `TelemetryPointSelector` primitive for hierarchical telemetry selection. The selector is deliberately **not** a repository client, acquisition client, WebSocket owner, or route-specific dashboard editor.

Consumers provide a normalized `TelemetryPointDescriptor[]` for one organization. Each descriptor contains explicit hierarchy metadata and the canonical telemetry identity required for a leaf:

- laboratory;
- zone;
- equipment type;
- equipment;
- transport node;
- channel;
- metric;
- native unit.

The selector never infers laboratory, zone, or equipment type from `equipment_id`, channel names, or string conventions. If a consumer cannot provide required hierarchy metadata, the adapter is incomplete and must be fixed at the consumer boundary rather than hidden by selector heuristics.

## Canonical leaf identity

The leaf selection key uses the existing Live Data identity order:

```text
node_id | equipment_id | channel_id | metric | unit
```

Each part is URI-component encoded before joining. Organization scope is held separately by the hierarchy instance so a selector cannot accidentally mix points from different organizations while preserving compatibility with the existing Live Data selection identity.

Branch IDs include organization scope plus the stable hierarchy path. They are presentation/read-model identities and are never persisted as telemetry channel identifiers.

## Hierarchy

The canonical hierarchy is:

```text
laboratory
  → zone
    → equipment type
      → equipment
        → channel / metric / unit leaf
```

Input is normalized and sorted before construction. Duplicate leaf identities are deterministically deduplicated so one telemetry identity is rendered once. The hierarchy stores canonical leaf order and parent IDs for keyboard navigation.

## Selection semantics

Selection is draft-first:

- incoming `value` is the committed selection;
- browsing, search, expand/collapse, and checkbox/tree interactions mutate only internal draft state;
- `Cancel` restores the committed selection;
- `Confirm` emits one canonical, hierarchy-ordered list of leaf keys;
- selection limits are consumer-provided and are enforced atomically for branch selection;
- a partially selected branch exposes `aria-checked="mixed"`.

Search never deletes committed selection that is outside the current result set. When search narrows a branch, selection actions apply to the visible matching subtree while hidden committed leaves remain intact until explicitly changed or cancelled.

## Accessibility and keyboard model

The component uses an ARIA multi-select tree with roving `tabIndex`:

- `ArrowDown` / `ArrowUp`: next / previous visible item;
- `Home` / `End`: first / last visible item;
- `ArrowRight`: expand a collapsed branch, then move to its first visible child;
- `ArrowLeft`: collapse an expanded branch or move to its parent;
- `Space` / `Enter`: toggle the current leaf or branch selection;
- search input `ArrowDown`: move focus into the first visible tree item.

Each tree item exposes `aria-level`, branch `aria-expanded`, and boolean or mixed `aria-checked`. Selection state is represented by text/ARIA as well as color.

## Large inventory policy

Hierarchy construction and search are linear in the number of normalized nodes. Search reports how many nodes were visited so deterministic tests can assert that it never performs a quadratic tree scan.

Rendered visible rows are bounded. The default hard presentation budget is 400 nodes and the implementation refuses to render more than 2,000 nodes in one visible tree pass. Collapsed branches do not render descendants. If the visible budget is reached, the selector tells the operator to narrow search instead of expanding the document indefinitely.

## Consumer boundary

Issue #461 ships the reusable hierarchy/read-model and selector primitive only. A future consumer adapter is responsible for joining canonical equipment metadata with telemetry points. Existing repository evidence shows:

- `TelemetrySample` provides node/equipment/channel/metric/unit identity but no lab/zone/equipment-type metadata;
- existing equipment/catalog domains contain location, chamber, category/device type, laboratory and zone information in their own models.

The adapter must supply those fields explicitly. The selector itself must not call equipment catalogs, telemetry history, discovery, Device Agent, configuration APIs, or any physical acquisition path.

## Runtime and safety invariants

Opening, searching, expanding, selecting, confirming, or cancelling the selector:

- opens no WebSocket;
- performs no telemetry history request;
- performs no acquisition-registry/discovery/configuration mutation;
- performs no Modbus or hardware write;
- adds no mandatory public runtime dependency, CDN, remote font, cloud service, or external API.

Browser acceptance is performed without adding a product route: the actual React selector is server-rendered inside the existing production browser acceptance process and evaluated with production application CSS. Interactive keyboard/search/confirm/cancel behavior is covered by component tests against the same component implementation.

The production browser proof isolates React server rendering in a plain Node subprocess before markup is injected into Playwright. This keeps Playwright's module transform out of React element creation and remains acceptance tooling only; it adds no production runtime dependency or route.