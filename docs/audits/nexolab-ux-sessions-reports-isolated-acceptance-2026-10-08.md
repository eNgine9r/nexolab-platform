# NEXOLAB — Sessions/Reports isolated operator acceptance (#1304)

Date: 2026-10-08. Related: #1191, #1300, #1302. PR: #1305.

## Intended evidence

- Playwright `e2e/test-sessions.production.e2e.ts`: Tab/Shift+Tab/Escape focus, filter navigation, 360/390/430/1440 layout, draft with no report action and archived session with a report action.
- Playwright `e2e/reports.production.e2e.ts`: completed reader link, Enter navigation to session-scoped reports, keyboard return, generation permissions, running session without report action, invalid/foreign organization contexts without usable generation or back-link, and no browser mutating requests during read-only steps.
- Rendered-report integrity and organization isolation remain in existing specialized test coverage; this Work Package does not modify report data or add production fixtures.

## Verification boundary

Assertions and CI workflows must be evaluated on the exact final PR head. A queued/in-progress run or a GREEN run for an older head is not acceptance. This report records expected coverage, not a claim of completed CI.

No live-site browser credentials, production session changes, report generation, Modbus/hardware write, deployment or site cutover. Previously consumed one-time #1300 service credentials must not be reused. Physical acceptance and rollout of sources newer than deployed `75d9c75f8d1901d6b639ec711bf3784e22ed0642` remain separately gated.

## Pre-final source validation

On code head `65631e4f6381cb5f567e580db9db6b27232186b0`: Core Quality/build and NEXOLAB Merge Gate (run 37746833296), Reports Browser Acceptance (run 37746833321), and Test Sessions Browser Acceptance (run 37746833286) all completed GREEN. This statement is scoped to that code head. A subsequent documentation/state checkpoint commit requires its own exact-head gate before merge. No actual-site or hardware acceptance is asserted.
