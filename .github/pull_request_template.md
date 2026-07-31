## Outcome

<!-- Який завершений результат для оператора, лабораторії або системи дає цей PR? -->

Closes #

## Scope completed

- ...

## Out of scope

- ...

## Changed areas

- [ ] Frontend/UI
- [ ] Telemetry service/API
- [ ] Device agent/edge
- [ ] Database/migrations
- [ ] MQTT/infrastructure
- [ ] Operations/deployment
- [ ] Documentation/process only

## Software verification actually run

<!-- Позначайте лише перевірки, які реально запускались на цій гілці. -->

- [ ] `npm run format:check`
- [ ] `npm run lint`
- [ ] `npm run typecheck`
- [ ] `npm test`
- [ ] `npm run build`
- [ ] Telemetry-service compile/tests
- [ ] Device-agent compile/tests
- [ ] Compose config validation

Commands and results:

```text
...
```

## Offline and hardware evidence

- [ ] Core runtime remains independent of internet and paid services.
- [ ] No mandatory CDN, remote font, cloud auth or hidden external API was added.
- [ ] No Modbus write path was added or executed.
- [ ] Missing real-hardware evidence is marked unverified, not passed.
- [ ] Offline startup was tested or is explicitly not affected.
- [ ] Backup/restore/update/rollback impact is documented.

Evidence:

```text
...
```

## UI

<!-- Додайте скриншоти для візуальних змін: desktop/mobile, loading, stale, offline, error. -->

## State continuity

- [ ] `.project/CURRENT_STATE.md` updated when project state changed.
- [ ] `.project/ACTIVE_SPRINT.json` task status updated.
- [ ] `.project/LAST_CHECKPOINT.json` updated.
- [ ] Blockers and risks recorded.

## Risks and rollback

- Risk:
- Rollback:

## Next Ready Work Package

- ...
