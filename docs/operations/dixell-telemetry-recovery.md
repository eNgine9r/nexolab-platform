# Replacement Dixell telemetry recovery

Issue #1577. This is a source correction and read-only diagnostic, not a site update.

## Observed fault boundaries

On 2026-11-16 the protected UI listed two active section-profile XJP60D modules:
Unit 1 with six inputs and Unit 7 with two inputs. Their eight latest samples were
stale at approximately 11:40 Europe/Kyiv while other telemetry still advanced.
The general Live banner therefore did not establish Dixell acquisition health.
The Live page did not finish the requested 24-hour history window during inspection.

Overview's classifier recognized only legacy two/three-digit numeric channel IDs.
It rejected both single-digit legacy IDs and commissioned section identities such
as `rs485-sdm120:1-S01` belonging to `XJP60D-S:rs485-sdm120:1`.
The correction preserves the full bus/module identity and metric/quality handling.
It does not change storage identifiers or rewrite historical samples.

Separately, Monitoring and cadence returned the server-session-unavailable message.
The Next.js handlers emit that message when resolving the private API origin or
fetching its auth session throws. Do not change user permissions or remove RBAC to
hide this failure. Missing private origin, failed network access and server process
configuration must be distinguished on the actual host.

The existing Overview monitoring set uses legacy Device Agent `active_points`.
Section-profile enrollment/selection must be reconciled with the actual running
agent before claiming Overview acceptance; classifier changes alone are insufficient.
Main's Device Agent does not contain the section-profile implementation observed on
the site. Do not replace that agent with a generic main build.

## Read-only host diagnostic

Run these reads as the ordinary `nexolab` user. No service restart or controller
operation is included. Do not print full environment or authentication material.

```bash
python3 - <<'PYTHON'
import json, subprocess, urllib.request
from pathlib import Path
pid = subprocess.check_output([
    'systemctl', '--user', 'show', 'nexolab-external-ui-1569.service',
    '-p', 'MainPID', '--value'], text=True).strip()
if pid.isdigit() and int(pid):
    env = dict(x.split(b'=', 1) for x in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in x)
    for key in ('NEXOLAB_SERVER_API_BASE_URL', 'NEXOLAB_EXTERNAL_HTTPS_STAGE', 'NEXOLAB_DEVICE_AGENT_BASE_URL'):
        value = env.get(key.encode(), b'<missing>').decode()
        print(key, '<redacted-invalid>' if any(c in value for c in '@?#') else value)
else:
    print('frontend PID unavailable')
for path in ('/health', '/api/v1/xjp60d/configuration'):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8081'+path, timeout=4) as response:
            body = json.loads(response.read(1048576))
        keys = ('status', 'device_mode', 'mqtt_connected', 'queue_depth', 'active_points', 'registry_revision')
        print(path, json.dumps({k: body[k] for k in keys if k in body}))
    except Exception as error:
        print(path, type(error).__name__)
PYTHON
```

Commander health/file reads worked but execution returned `EXECUTION_HANDLER_FAILED`
during this investigation. The owner console is required for the diagnostic until
the existing execution channel works. Do not substitute an unrelated control plane
or bypass read/privilege policies.

## Remaining acceptance

1. Resolve the frontend private API connection from actual diagnostic evidence.
2. Inspect the section-profile scheduler, adapter ownership and persistent registry;
   restore approved read-only polling while preserving the installed custom agent.
3. Confirm two increasing persisted sample timestamps on all eight connected inputs.
4. Verify the configured section channels appear in Overview's display selection
   and that both Overview and Live can render their stored history.
5. Retire only obsolete polling targets using the canonical registry lifecycle;
   retain old measurements. Inspect current eligibility before any mutation.
6. Enroll the next seven modules with unique, non-overlapping profile section
   addresses after physical connection and read-only preflight. A software test of
   54 inputs is not real RS-485 capacity or nine-device hardware acceptance.

Any site activation requires a matching artifact, rollback and separate scoped
owner authorization. No green update signal is justified by the source fix alone.

## Owner recovery and current acceptance (2026-11-16)

The owner read confirms revision 45 had two `discovery_only` parents with eight
active section targets and four reserve targets. Parent activation through the
canonical registry produced revision 46 with six/two eligible inputs. Do not rerun
the revision-45 command. The previous state and guarded inverse payload were
saved on the owner host before the change.

Telemetry listens on `172.18.48.66:8082`; loopback 8082 refuses connections. With
explicit owner approval, a new user-service drop-in sets only
`NEXOLAB_SERVER_API_BASE_URL` to that actual private origin. Only
`nexolab-external-ui-1569.service` restarted. Preflight checked API401, original
frontend503 and current source/build identity. The post-check returned the expected
unauthenticated frontend401 and identical build. Journal:
`/home/nexolab/nexolab-1577-ui-e86e61no`; result `FRONTEND_API_FIXED`.
This is not installation of PR1578 or permission for another source deployment.

After the owner signed in again, all eight live timestamps advanced by ten seconds;
a saved Dashboard displayed six persisted Unit1 lines in its one-hour chart.
The earlier history fetch failure disappeared after login. Full Unit7 persisted
history and Overview acceptance remain open. The future seven devices are not
hardware-accepted by any software fixture.

The source candidate projects Overview eligibility from canonical registry GET:
active XJP60D parent, active target, explicit eligibility, read-only bus/FC03,
matching bus/unit/section or legacy identity. It neither activates targets nor
falls back to all historical temperatures. The legacy GET remains for node/diagnostic
metadata only. Legacy POST/PUT is refused when section modules are registered,
because replacement of numeric `active_points` cannot safely express that enrollment.
The canonical registry and commissioning interfaces retain their existing permissions.
Cadence also recognizes the already-supported `waveshare_8ai` family; unknown
families remain rejected. These source changes still need a matched approved rollout.
