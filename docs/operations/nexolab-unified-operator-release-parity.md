# NEXOLAB — one operator release across LAN and Funnel (#1592)

**Status:** source-only, read-only parity gate. **Not a production update or permission to switch traffic.**

## Operator outcome

The laboratory LAN frontend and the primary Tailscale Funnel frontend must expose the same approved NEXOLAB product release, the same compatible local Telemetry API/data and the same equipment-onboarding workflow. The custom on-site acquisition configuration is preserved, not overwritten with the generic source Device Agent.

The diagnostic/inspection Tailscale ports are not canonical operator entrypoints and must remain explicitly distinguished.

## Observed active topology — 2026-11-18 (read only)

| Operator surface                 | Backend route                                 | `source_commit` from `/api/runtime-identity` | `build_id`              |
| -------------------------------- | --------------------------------------------- | -------------------------------------------- | ----------------------- |
| Local Docker dashboard           | `172.18.48.66:3000`                           | `4be678f6aa2581ad7fc79bcc22c26cd520c94272`   | `CoZ2mvfZvFe67uyyeRe7a` |
| Primary Funnel HTTPS             | Funnel → `127.0.0.1:18790` → `127.0.0.1:3105` | `75ceb4654afbc0e7ae8b59ee5cbbb76917eb1045`   | `u5qAvkW0BUJHwhOMa6pHr` |
| `lab.nexolab` private LAN bridge | `nexolab-lab-http.service` → `127.0.0.1:3104` | `08f1c8a4ed9212c25697d338583845bed5218ee5`   | `MCPKmYsrQCxN9zwMwDDnV` |

The Docker image **tag** includes `ffdefc4550d7`, which differs from the Docker frontend's runtime-reported source `4be678f6`. Resolve this against the verified build manifest and mounted source before declaring an authority, not by assuming the tag is the running source.

The running edge container is `nexolab/quick-agent:1490` (protected on-site commissioning lineage). Existing read-only evidence: registry revision 46; live Dixell Unit 1 channels 1–6 and Unit 7 channels 1–2, four reserve Unit 7 channels; old devices must not masquerade as live. The main branch source must not automatically replace this agent.

## Safe source/build parity preflight

The new verification command reads **only** local/private HTTP upstreams. It requires an explicitly approved merged-main SHA and fails closed on missing identity, redirects, unreachable ports, source drift or different build IDs. It does **not** follow the public OAuth redirect or need authentication credentials.

Select `APPROVED_SHA` from the exact reviewed/approved release manifest. Do not derive it from an arbitrary feature branch.

```bash
python3 scripts/check-frontend-entrypoint-parity.py \
  --expected-source "$APPROVED_SHA" \
  --entrypoint docker=http://172.18.48.66:3000 \
  --entrypoint funnel=http://127.0.0.1:3105 \
  --entrypoint lab=http://127.0.0.1:3104
```

Exit codes: `0=PASS`, `1=FAIL parity or unavailable upstream`, `2=INVALID arguments`. The current installation is **expected to FAIL**. The script has no write path and intentionally rejects public, hostname or link-local targets. It reports only selected identity fields, never the full upstream payload.

The default gate is deliberately **stricter than merely matching a Git source revision**: matching source with differing build IDs fails. This is correct if a single compiled frontend binary can safely serve every origin.

### Approved origin-specific builds (same version, different binaries)

The current `getTelemetryRuntimeConfig()` requires **absolute HTTP and WebSocket URLs** (`NEXT_PUBLIC_NEXOLAB_API_BASE_URL` and `NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL`). LAN/offline and protected HTTPS therefore may require distinct compiled frontend binaries even when both are built from the **same exact merged-main source**. Do not force the LAN client to require public/Tailscale HTTPS just to make build IDs equal.

For this case, accept multiple build IDs **only** with an explicit, separately reviewed offline release manifest. A minimal example (substitute actual approved values, do not use placeholders in production):

```json
{
  "schema_version": 1,
  "source_commit": "<approved-merged-main-40-char-sha>",
  "entrypoint_builds": {
    "docker": "<approved-lan-build-id>",
    "funnel": "<approved-https-build-id>",
    "lab": "<approved-private-lan-build-id>"
  }
}
```

The release authority must attest each build's complete package/archive SHA256, origin-bound API/auth configuration, expected source SHA and ARM64 platform independently. Copy the exact SHA256 of the **manifest bytes** from that reviewed release package. Run:

```bash
python3 scripts/check-frontend-entrypoint-parity.py \
  --expected-source "$APPROVED_SHA" \
  --build-manifest /path/to/verified/frontend-builds.json \
  --manifest-sha256 "$APPROVED_MANIFEST_SHA256" \
  --entrypoint docker=http://172.18.48.66:3000 \
  --entrypoint funnel=http://127.0.0.1:3105 \
  --entrypoint lab=http://127.0.0.1:3104
```

This optional manifest mode requires every observed frontend to declare the **same approved source commit** and its own **exactly approved build ID**, with a complete set of entrypoints and a matching manifest digest. An unexpected build, missing source, extra entrypoint, wrong digest or unavailable upstream fails closed. The checksum is **not a digital signature** and must not be treated as release authority by itself. Source/build parity does not establish functional equivalence: authenticated LAN/HTTPS browser flows, API/schema compatibility, offline behavior and equipment onboarding must still pass #1587 acceptance.

## Protected commissioning and operator-flow regression gates

Before release #1587, establish evidence for:

1. Exact **merged-main source**, Next build artifact, local Telemetry API/schema revision and installed Device Agent lineage, together with read-only health, storage and rollback authority.
2. Browser flows: Devices → Registry → add/identify an RS-485 instrument → choose physical bus/Modbus address from existing validated workflow → commissioned channels → Live Data / charts, with no obligatory refrigeration-chamber association. Do not run an invasive scan or change device addresses for acceptance.
3. Persisted names and original technical channel IDs, historical charts, offline/stale distinction and permissions across all operator origins.
4. Live read-only checks on the existing connected two Dixell groups and energy/analog devices; distinguish observed software results from physical hardware evidence. **No Modbus or hardware write.**
5. Original auth/OAuth routes, websocket API, local LAN operation without internet, and no new paid/cloud runtime dependency.
6. Approved off-device backup/isolated restore and protected migration `20261118_0040` continuity, measured disk/RAM headroom, exact-target ARM64 package and independently verified rollback. Blockers #1428 and #1409 are not implicitly resolved.

## Release sequencing

- #1586 is merged. #1589 and #1591 require their own exact-head checks and independent merge decisions. Pin the **target** only after selected source PRs merge into main and final CI/review are GREEN.
- #1592 is read-only/source work: prove the drift, prepare the parity check and publish this release handoff.
- #1587 owns the full protected site update. Its verified package and post-update acceptance must be explicitly authorized by the Product Owner for that **specific** source/build/migration/route change. No automatic site action.
- After the release, rerun source/build parity and authenticated operator checks on all three entrypoints. Only then can the operator see `🟢 Оновлюйся` for an approved, ready update.

**No runtime change, daemon restart, Docker compose recreation, production database migration, Tailscale route edit, hardware operation or data deletion is part of #1592.**
