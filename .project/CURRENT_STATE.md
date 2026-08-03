# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `33224e148c733e50896fe68c13c53130e0a7afac`
Active Work Package: Issue #243 / PR #249 — Lucide operator-semantics compatibility review
Status confidence: high for repository inventory, package metadata, release-impact analysis and accessibility contracts; exact-head GitHub workflows are pending for the final focused-test head.

## Completed dependency baseline

- Issue #242 / PR #248 is merged as `33224e148c733e50896fe68c13c53130e0a7afac`.
- Optional Supabase resolved graph is `2.112.0` and LOCAL_LAN local authentication remains primary and fail-closed.

## Issue #243 decision

Decision: **retain the current Lucide manifest/lockfile pair; no dependency update**.

Current dependency state:

```text
package.json: lucide-react ^1.25.0
package-lock.json resolved: lucide-react 1.26.0
runtime dependencies: none
peer compatibility: React 16.5.1 through React 19
```

Published npm candidate reviewed: `1.27.0`.

Rationale:

- no published Lucide security advisory or required React 19/runtime compatibility fix was identified;
- the 1.27.0 release primarily adds icons and changes selected SVG geometry;
- NEXOLAB imports `Zap`, whose SVG changed in 1.27.0;
- `Zap` is the persistent navigation symbol for **Енергомоніторинг** and the page-level energy icon;
- changing that operator-facing symbol without a security, runtime or product requirement creates visual regression risk with no compensating benefit;
- the repository lockfile remains deterministic at 1.26.0, so no online runtime dependency or package delivery change is needed.

## Import and operator-control inventory

Repository search captured **52 source files** importing Lucide and **103 distinct icon exports**:

```text
Activity, AlertCircle, AlertTriangle, Archive, ArrowLeft, ArrowRight, ArrowUpRight,
BadgeCheck, Ban, Bell, BellRing, Bolt, Box, Boxes, CalendarDays, Camera,
ChartNoAxesCombined, Check, CheckCircle2, ChevronDown, ChevronRight, CircleCheck,
CircleDashed, CircleDot, CircleOff, ClipboardCheck, Clock3, Cloud, Construction,
Copy, CopyPlus, Cpu, Database, Download, Expand, Eye, FileCheck2, FileClock,
FileJson2, FileOutput, FileSpreadsheet, FileText, Fingerprint, Gauge, Grid3X3,
History, Home, ImageIcon, ImagePlus, Info, KeyRound, Layers3, Link2, LoaderCircle,
LockKeyhole, LogIn, LogOut, Maximize2, Menu, MessageSquarePlus, Minimize2, Minus,
MousePointer2, Network, Pause, PauseCircle, Pencil, Play, PlayCircle, Plus, Radio,
RadioTower, Redo2, RefreshCcw, RefreshCw, RotateCcw, RotateCw, Save, Scan, Search,
Server, ServerCog, Settings, Settings2, ShieldAlert, ShieldCheck, Shrink, Siren,
SlidersHorizontal, Snowflake, Square, Thermometer, Timer, Trash2, TriangleAlert,
Undo2, Upload, UploadCloud, Wifi, WifiOff, Wrench, X, Zap
```

Release-sensitive intersection for npm 1.27.0:

```text
Zap
```

No NEXOLAB import was found for the other changed 1.27.0 icons such as `ZapOff`, `Toolbox`, `SquareScissors`, `Feather`, `Barrel`, `Trophy` or `Podcast`.

## Accessibility and regression evidence

- Topbar icon-only controls have explicit labels: menu, notifications and sign-out.
- Refrigeration icon-only controls use `RefrigerationIconButton`, which requires a non-optional `label` and applies both `aria-label` and `title`.
- Refrigeration icon-button size tokens remain deterministic at `32 px`, `40 px` and `44 px` with `focus-visible` outlines.
- Session, alert, node, security and report actions retain visible action text or explicit accessible names.
- Status meaning is not carried by icon or color alone.
- `lucide-operator-semantics.test.tsx` locks the `Zap → Енергомоніторинг → /energy` mapping.
- The focused test also proves the icon-only refrigeration button retains its accessible name, title, button type, `40 px` default size and keyboard focus outline.
- No production component, import, layout, styling or operator meaning changed.

## Files changed

```text
src/components/dashboard/lucide-operator-semantics.test.tsx
.project/CURRENT_STATE.md
.project/ACTIVE_SPRINT.json
.project/BLOCKERS.md
.project/LAST_CHECKPOINT.json
```

`package.json`, `package-lock.json` and all production UI components remain byte-for-byte unchanged from main.

## Verification and next action

Pending on the final branch head:

- focused Lucide operator-semantics Vitest;
- repository formatting, ESLint, strict TypeScript, full Vitest and production build;
- Refrigeration Browser;
- Security Browser;
- Authenticated Dashboard;
- Nodes Browser;
- Test Sessions Browser;
- Alerts Browser;
- Reports and Rendered Reports Browser;
- Offline Bundle disconnected startup and update/rollback volume preservation;
- review audit and expected-head merge.

After GREEN, merge PR #249, close Issue #243, reconcile parent Issue #203 and resume the next Ready software Work Package. Actual Raspberry Pi acceptance for Issue #245 remains separate and hardware-unverified.
