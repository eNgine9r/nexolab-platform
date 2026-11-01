# NEXOLAB #1453 — Canonical LOCAL_LAN Punycode URL validation

The offline bundle build's local package URL gate is intentionally network-free.
WHATWG `new URL(raw)` canonicalizes HTTP/WS origins and ASCII DNS hostnames;
it does **not** by itself prove that an `xn--` A-label decodes to valid IDNA
text. Explicit `node:url.domainToUnicode(host)` verification now rejects
invalid A-labels with a fail-closed error before release artifact creation.

Accepted examples: canonical `xn--bcher-kva.local`, `xn--zca.local` and
nested `lab.xn--bcher-kva.local`. Rejected examples:
`xn--a.local`, `xn--rv6q.local`, `lab.xn--rv6q.local`.
The original same-host requirement, valid LOCAL_LAN-only IP/DNS, canonical
URLs and no-credentials/query/fragment restriction remain unchanged.

2026-11-01 source-only evidence: isolated Raspberry Pi ARM64 engineering
worktree at verified main `528ff5256d379ffd4a8ec77d831264db9180a47f`;
official Node v22.23.1 Linux ARM64 archive validated against Node SHASUMS256;
30/30 targeted workflow contract tests and 383/383 `test_ci_*.py`
tests successful (one built-in skip). No DNS lookup, production runtime
mutation, site package change, Modbus or hardware write. GitHub exact-head
checks are the merge authority. Independent supply-chain HIGH exception
approval #1447 remains outside this PR; do not waive or merge RED.
