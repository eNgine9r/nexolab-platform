# Issue #1236 — Python TLS HIGH review

The exact UX-27 candidate `0a74b67753ccb48d4af7734879ad00da96e059f4` passed report and rendered-report browser checks, backend tests and Core Quality/build, but Container Supply Chain run **36921474135** blocked release on newly discovered CVE-2026-19553. This independent prerequisite changes only eight exact HIGH decisions and repository evidence. The existing 92 decisions and their expiry are unchanged. It does not patch Python, lower severity, change the evaluator or claim that vulnerable packages are fixed.

## Fresh evidence

All five completed scan artifacts were downloaded and their Trivy reports compared with the existing registry. There are **100 HIGH, zero CRITICAL, eight new exact tuples, zero stale tuples**, with no fixed version on the eight new findings. The tuple-set digest is `a6a26eaf112c502e76da852ea0508364cb76d0659bd66fe41c369785b8bde403` (SHA-256 of UTF-8 compact JSON sorted unique `[image_id, package, CVE]` arrays).

| Image                 | Artifact ID | HIGH count | New tuples |
| --------------------- | ----------- | ---------- | ---------- |
| Device Agent          | 11191702528 | 26         | 4          |
| Telegram Gateway      | 11191842445 | 26         | 4          |
| Telemetry Service     | 11191479906 | 48         | 0          |
| MQTT dynamic security | 11192585692 | 0          | 0          |
| Object storage        | 11192141306 | 0          | 0          |

Each of Device Agent and Telegram Gateway has exactly these four new HIGH binary-package tuples for **CVE-2026-19553**, installed `3.13.5-2+deb13u5`: `libpython3.13-minimal`, `libpython3.13-stdlib`, `python3.13-minimal`, `python3.13-venv`. The affected package is required by the distroless Python runtime; removing it would remove the application interpreter. Telemetry's runtime/base differs; no new decision is assigned to that image.

## Fix status and affected path

[Debian's tracker](https://security-tracker.debian.org/tracker/CVE-2026-19553), reviewed 2026-10-01, lists Trixie `3.13.5-2+deb13u5` as vulnerable with no fixed source-package version. Debian marks the issue no-dsa/minor; the repository continues enforcing the scan's **HIGH** classification. [CPython issue #156793](https://github.com/python/cpython/issues/156793) and [the 3.13 patch](https://github.com/python/cpython/commit/f4e43ba525187282f2011da0e6ffc0d2b08d8062) address missing argument validation in `SSLContext.wrap_bio` / `SSLObject`. The defect permits omitted `server_hostname` to skip hostname verification even when `check_hostname=True`. A valid hostname preserves verification; `check_hostname=True` alone is not evidence of mitigation for a BIO caller.

This is a review of current accepted runtime paths, not a statement that every potential use of the installed Python library is safe:

- Device Agent uses pinned `paho-mqtt==2.1.0` (fresh package inventory confirms the version). NEXOLAB `mqtt_tls.py` requires a readable CA, `CERT_REQUIRED`, `check_hostname=True`, TLS 1.2 minimum and paired client-certificate/key material. [Pinned Paho `_ssl_wrap_socket`](https://github.com/eclipse-paho/paho.mqtt.python/blob/v2.1.0/src/paho/mqtt/client.py) was read via the GitHub contents API: it calls `SSLContext.wrap_socket(..., server_hostname=self._host)`, not `wrap_bio`. Its legacy no-SNI fallback also uses `wrap_socket`, which already enforces the hostname requirement when `check_hostname=True`. NEXOLAB does not call `tls_insecure_set`, disable certificate validation or implement a custom memory-BIO TLS transport. Existing seven MQTT TLS configuration tests pass.
- Gateway outbound requests use `app/http_transport.py` standard `urllib.request.urlopen`, without a custom insecure SSL context. Telegram configuration validates HTTPS production endpoints; backend transport derives its host from the configured URL. [CPython 3.13.5 HTTPSConnection](https://github.com/python/cpython/blob/v3.13.5/Lib/http/client.py) was read via the GitHub contents API: `connect()` passes the URL host or tunnel host into `SSLContext.wrap_socket`. Application source has no `wrap_bio`, `start_tls` or asyncio TLS-client implementation. The accepted Docker entry starts uvicorn HTTP without SSL parameters; merely having anyio installed does not establish an affected outbound TLS path.

The current reviewed paths therefore do not exercise the missing-hostname BIO behavior. No hostname verification was disabled to produce this conclusion. Acquisition and application source remain unchanged.

## Bounded decision and verification

Only the eight enumerated image/package/CVE tuples are temporarily owned by `platform-security` through **2026-10-02**, the already scheduled consolidated review boundary. Existing expiry is not extended. Remove any decision immediately when a compatible fixed base becomes consumable, the exact tuple disappears, runtime reachability changes or severity becomes CRITICAL. New versions or new TLS call sites require review; this is not a wildcard package-family decision.

Local evidence: seven existing Device Agent TLS tests; all five fresh report policy evaluations and exact tuple match; inventory/exception validation and canonical state/format checks. Local pytest policy regressions could not run because this runtime has no pytest; the routed CI must run them. Fresh exact-head no-cache Container Supply Chain, routed Core/Merge Gate/backend workflows and review are required before merge. PR #1234 must then reconcile with merged main and repeat product exact-head acceptance. No deployment, restart, data/volume mutation, Modbus or hardware write is scoped.

Fresh run 36923177734 first reproduced three historical registry-test failures (46 other cases passed): September cohort filters counted the newly added October CVE. Those exact historical filters now exclude only CVE-2026-19553 while preserving their 90/80/92 tuple and provenance assertions. A separate October guard checks the exact eight new tuples, owner and unchanged expiry. All four functions pass through direct stdlib execution; the full pytest suite remains required in CI. The production evaluator/severity gates are unchanged.
