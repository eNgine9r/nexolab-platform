# Issue #978 — libexpat1 HIGH CVE review

Date: 2026-09-09

## Trigger

Issue #933 / PR #976 exact head `6764370ce89ac0b81aa839a6cc0941bc90509ac4` triggered fresh no-cache Container Supply Chain run `34307375095`. Image build, OCI-label validation, CycloneDX/SPDX SBOM generation and Trivy report generation succeeded. Vulnerability policy then failed closed only for Device Agent and Telegram Gateway.

The new exact findings are:

| Image              | Package     | Installed         | CVE              | Severity | Scanner fixed version |
| ------------------ | ----------- | ----------------- | ---------------- | -------- | --------------------- |
| `device-agent`     | `libexpat1` | `2.8.3-1~deb13u1` | `CVE-2026-76956` | HIGH     | none                  |
| `device-agent`     | `libexpat1` | `2.8.3-1~deb13u1` | `CVE-2026-76957` | HIGH     | none                  |
| `telegram-gateway` | `libexpat1` | `2.8.3-1~deb13u1` | `CVE-2026-76956` | HIGH     | none                  |
| `telegram-gateway` | `libexpat1` | `2.8.3-1~deb13u1` | `CVE-2026-76957` | HIGH     | none                  |

Telemetry Service and MQTT dynamic-security passed the same policy run. The failure is therefore a cross-image base-runtime security interrupt rather than a regression in the Issue #933 SQLite changes.

## Upstream and Debian status

On 2026-09-09 the Debian Security Tracker reports Trixie/security `expat 2.8.3-1~deb13u1` as vulnerable/no-DSA for both CVEs. Expat `2.8.4-1` is available in forky/sid, not in stable Trixie. The exact no-cache Debian 13/distroless build used by CI still contains `libexpat1 2.8.3-1~deb13u1`, so there is no compatible stable package currently consumable by these final images.

Authoritative references:

- Debian `CVE-2026-76956`: <https://security-tracker.debian.org/tracker/CVE-2026-76956>
- Debian `CVE-2026-76957`: <https://security-tracker.debian.org/tracker/CVE-2026-76957>
- Debian `expat` source status: <https://security-tracker.debian.org/tracker/source-package/expat>
- Upstream Expat PR #1326 / `CVE-2026-76956`: <https://github.com/libexpat/libexpat/pull/1326>
- Upstream Expat PR #1322 / `CVE-2026-76957`: <https://github.com/libexpat/libexpat/pull/1322>

Upstream associates both fixes with Expat 2.8.4. `CVE-2026-76956` is an entropy/hash-flooding weakness requiring crafted XML to be parsed by Expat. `CVE-2026-76957` protects application-provided custom encoding `convert`/`release` callbacks from same-parser re-entry.

## Device Agent reachability

The final image is `gcr.io/distroless/python3-debian13:nonroot`, runs as `USER nonroot`, exposes port 8081, and production Compose publishes it only on `127.0.0.1:8081`. Its declared Python dependencies are exactly `paho-mqtt==2.1.0` and `pyserial==3.5`.

A runtime-source search across Device Agent Python files found no `pyexpat`, `xml.parsers`, `xml.etree`, SAX, `lxml`, `XMLParser`, `from xml`, or `import xml` path. Application-controlled inputs are JSON HTTP control/configuration, MQTT payloads and read-only Modbus RTU. SQLite persistence stores JSON payloads but does not invoke XML parsing. An inspected current Device Agent Python runtime reports Expat 2.8.3 while exposing no `UnknownEncodingHandler` on the `pyexpat` parser surface.

Therefore the crafted-XML hash-flood path for `CVE-2026-76956` and the custom-encoding callback/re-entry path for `CVE-2026-76957` are not reachable through the Device Agent application contract at this review point.

## Telegram Gateway reachability

The final image is also `gcr.io/distroless/python3-debian13:nonroot` and runs as `USER nonroot`. Production Compose publishes port 8090 only on `127.0.0.1:8090`; state is a dedicated data volume and Telegram secrets are mounted read-only. Declared dependencies are FastAPI, Uvicorn, Pydantic and pydantic-settings.

A runtime-source search found no XML/pyexpat parser import. FastAPI/Mini App input is handled by Pydantic JSON models plus URL-encoded Telegram `initData`; its embedded Telegram user field is decoded with `json.loads`. Telegram API and NEXOLAB backend requests/responses are JSON, and local configuration/identity artifacts are JSON or SQLite. No application-provided Expat custom encoding callback exists.

Therefore neither reviewed Expat path is reachable through the Telegram Gateway application contract at this review point.

## Decision

The repository policy allows a temporary HIGH decision only when there is no fixed stable package and the affected path is concretely unreachable or mitigated. Four exact exceptions are therefore added for the image/package/CVE tuples above with owner `platform-security` and expiry `2026-09-12`, matching the already scheduled consolidated exception review.

The decision is fail-closed and must be removed immediately when any of these conditions becomes true:

- the Debian 13/Trixie base consumes a fixed Expat package;
- a tuple disappears from a fresh scanner report;
- XML parsing or the affected custom-encoding path becomes reachable in either application;
- the finding becomes Critical.

No wildcard or Critical exception is introduced. No production deployment, service restart, Modbus/controller write, hardware write, product-data deletion or Docker named-volume deletion belongs to Issue #978.

## Required merge gate

The exceptions are not accepted merely because this review exists. The exact candidate must pass:

1. supply-chain inventory/exception schema validation;
2. focused policy regression tests and exact tuple reconciliation;
3. State Model v2 and diff hygiene;
4. a fresh exact-head no-cache Container Supply Chain run for all controlled images;
5. exact-head Core CI / NEXOLAB Merge Gate;
6. final Team Lead diff/review with no unresolved blocker.

Only after #978 merges may Issue #933 update to current `main` and repeat its own complete exact-head verification matrix.
