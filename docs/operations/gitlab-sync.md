# GitHub → corporate GitLab synchronization (#1713)

GitHub (`eNgine9r/nexolab-platform`, public) stays the canonical repository and the only merge authority. A bounded systemd timer on `nexolab-edge-01` copies `main`, and explicitly approved release tags, to the existing corporate GitLab project by **fast-forward only**. Native GitLab pull mirroring is not available on the corporate instance, so this is the fallback described in #1713.

This is a development-infrastructure service. It does not touch the production stack, Docker, devices or production data, and the core runtime does not depend on it.

The corporate GitLab address is configured only in `/etc/nexolab-gitlab-sync/sync.env` on the host. It is deliberately absent from this public repository; examples below use `gitlab.example.invalid`.

## Safety contract

- **Source**: only `https://github.com/eNgine9r/nexolab-platform.git`, fetched anonymously. Any other source URL is refused. GitHub never receives a credential.
- **Destination writes**: `main` by fast-forward only, plus tags listed in `/etc/nexolab-gitlab-sync/approved-tags` that are absent on GitLab and reachable from source `main`. No `--force`, `--mirror`, deletion or pruning; other GitLab branches and tags are never touched.
- **Fail closed** (nothing is written) when GitLab `main` is ahead of or diverged from GitHub, GitLab `main` is missing, GitHub history was rewritten since the last successful run, an approved tag already exists on GitLab with a different object, free disk is below 20 GiB, host `MemAvailable` is below 400 MiB, or authentication, network or verification fails.
- **Verification**: after a push, the GitLab `main` SHA (and each pushed tag object) is read back and must equal the source.
- **Pipelines**: pushes carry GitLab's `ci.skip` push option, so mirror pushes do not start GitLab pipelines until that is reviewed separately (#1633). Set `GITLAB_SYNC_CI_SKIP=0` only after that review.
- **Credential**: the GitLab project access token stays in the root-owned `/etc/nexolab-gitlab-sync/gitlab-token`. systemd passes it to the service with `LoadCredential`; only the askpass helper reads it, and only answers a prompt whose host exactly equals the configured GitLab host. The token never appears in arguments, environment variables, logs or the repository. The approved-tags list is delivered the same way (`LoadCredential=approved-tags`), so `/etc/nexolab-gitlab-sync/` can stay closed to the service identity.
- **Logging**: one JSON line per run (result, mode, SHAs, relation, commit counts, reason). URLs are reduced to the host name; Git error text is stripped of URL user information and truncated to 400 characters.
- **Isolation and limits**: `DynamicUser` (no permanent account), `ProtectSystem=strict`, `ProtectHome=yes`, private `/tmp` and devices, no capabilities, production paths and the Docker socket inaccessible; `MemoryMax=256M`, `CPUQuota=25%`, `TasksMax=32`, low CPU and I/O weight, 15-minute timeout. The working copy is one small bare repository in `/var/lib/private/nexolab-gitlab-sync/`.

## Files

| Repository file                                              | Installed as                                                                     |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `docs/operations/gitlab-sync/nexolab-gitlab-sync.py`         | `/usr/local/lib/nexolab-gitlab-sync/nexolab-gitlab-sync.py` (root, 0755)         |
| `docs/operations/gitlab-sync/nexolab-gitlab-sync-askpass.sh` | `/usr/local/lib/nexolab-gitlab-sync/nexolab-gitlab-sync-askpass.sh` (root, 0755) |
| `docs/operations/gitlab-sync/nexolab-gitlab-sync.service`    | `/etc/systemd/system/nexolab-gitlab-sync.service` (root, 0644)                   |
| `docs/operations/gitlab-sync/nexolab-gitlab-sync.timer`      | `/etc/systemd/system/nexolab-gitlab-sync.timer` (root, 0644)                     |
| (owner-written)                                              | `/etc/nexolab-gitlab-sync/sync.env` (root, 0640)                                 |
| (owner-written)                                              | `/etc/nexolab-gitlab-sync/approved-tags` (root, 0644)                            |
| (owner-provisioned, never read by agents)                    | `/etc/nexolab-gitlab-sync/gitlab-token` (root, 0600)                             |

The timer runs the service 10 minutes after boot and then 5 minutes after each run finishes, so it resumes automatically after a reboot. A run that is interrupted leaves nothing half-written on GitLab: every run starts again from a fresh comparison, and a lock prevents overlapping runs.

## Owner installation

Run from a checkout of `main` on the Pi, in the operator account with `sudo`. Do not print the token.

1. Check the token file without reading it:

   ```bash
   sudo stat -c '%U:%G %a %s bytes' /etc/nexolab-gitlab-sync/gitlab-token   # expect root:root 600 and a non-zero size
   ```

   The project access token needs the `write_repository` scope and a role allowed to push to the protected `main` branch in GitLab.

2. Write the configuration (replace the placeholder with the real project URL, `https://`, no user name or token in it):

   ```bash
   sudo install -d -o root -g root -m 0750 /etc/nexolab-gitlab-sync
   printf '%s\n' \
     'GITLAB_SYNC_DEST_URL=https://gitlab.example.invalid/<namespace>/nexolab-platform.git' \
     'GITLAB_SYNC_MODE=check' | sudo tee /etc/nexolab-gitlab-sync/sync.env >/dev/null
   sudo chmod 0640 /etc/nexolab-gitlab-sync/sync.env
   sudo install -o root -g root -m 0644 /dev/null /etc/nexolab-gitlab-sync/approved-tags
   ```

3. Install the program and units:

   ```bash
   sudo install -d -o root -g root -m 0755 /usr/local/lib/nexolab-gitlab-sync
   sudo install -o root -g root -m 0755 docs/operations/gitlab-sync/nexolab-gitlab-sync.py \
     docs/operations/gitlab-sync/nexolab-gitlab-sync-askpass.sh /usr/local/lib/nexolab-gitlab-sync/
   sudo install -o root -g root -m 0644 docs/operations/gitlab-sync/nexolab-gitlab-sync.service \
     docs/operations/gitlab-sync/nexolab-gitlab-sync.timer /etc/systemd/system/
   sudo systemd-analyze verify /etc/systemd/system/nexolab-gitlab-sync.service /etc/systemd/system/nexolab-gitlab-sync.timer
   sudo systemctl daemon-reload
   ```

## First authenticated run: compare histories (no push)

`GITLAB_SYNC_MODE=check` fetches both sides, compares them and reports, but never pushes. It proves that the token can read the GitLab project.

```bash
sudo systemctl start nexolab-gitlab-sync.service
journalctl -u nexolab-gitlab-sync.service -n 3 -o cat
```

Read the JSON line:

| `relation`          | Meaning                                      | Next step                                                                      |
| ------------------- | -------------------------------------------- | ------------------------------------------------------------------------------ |
| `equal`             | GitLab `main` equals GitHub `main`           | enable push mode                                                               |
| `fast_forward`      | GitLab is behind by `ahead_source` commits   | enable push mode                                                               |
| `destination_ahead` | GitLab has `ahead_destination` extra commits | **stop**; GitLab-only work must be reviewed and brought to GitHub first        |
| `diverged`          | both sides have their own commits            | **stop**; never overwrite GitLab-only changes; decide reconciliation on GitHub |

`destination_only_refs` counts GitLab branches other than `main`; they are left untouched. `result: failed` with `reason` such as `git_ls-remote_failed` means authentication or network trouble; check the token scope and that the host resolves.

## Enable synchronization

Only after a successful check run with `equal` or `fast_forward`:

```bash
sudo sed -i 's/^GITLAB_SYNC_MODE=check$/GITLAB_SYNC_MODE=push/' /etc/nexolab-gitlab-sync/sync.env
sudo systemctl start nexolab-gitlab-sync.service
journalctl -u nexolab-gitlab-sync.service -n 3 -o cat
```

The first push run must report `result: synchronized` (or `up_to_date`) and `destination_sha_after` equal to `source_sha`. Compare that SHA with GitHub `main` and with the GitLab project page. Only then enable the timer:

```bash
sudo systemctl enable --now nexolab-gitlab-sync.timer
systemctl list-timers nexolab-gitlab-sync.timer
```

Synchronization is operational only after this authenticated push and SHA comparison succeed.

## Operation

- Status: `journalctl -u nexolab-gitlab-sync.service -o cat -n 20`; last success `sudo cat /var/lib/private/nexolab-gitlab-sync/last-status.json`; last failure `.../last-failure.json`.
- Approve a release tag: append the exact tag name (for example `v1.4.0`) to `/etc/nexolab-gitlab-sync/approved-tags`. It is pushed on the next run if it exists on GitHub, is reachable from `main` and does not exist on GitLab.
- Pause: `sudo systemctl stop nexolab-gitlab-sync.timer`. Resume: `sudo systemctl start nexolab-gitlab-sync.timer`.
- Divergence: the service keeps failing with exit code 4 and changes nothing. Review the GitLab-only commits, bring wanted changes to GitHub through a normal Pull Request, and resolve GitLab `main` by an owner decision. The service never does this automatically.

Exit codes: `0` success or skipped, `2` configuration, `3` disk or memory reserve, `4` divergence or rewritten source, `5` network, authentication or Git failure, `6` approved-tag problem or collision, `7` verification failure.

## Rollback

```bash
sudo systemctl disable --now nexolab-gitlab-sync.timer
sudo rm /etc/systemd/system/nexolab-gitlab-sync.service /etc/systemd/system/nexolab-gitlab-sync.timer
sudo rm -r /usr/local/lib/nexolab-gitlab-sync
sudo systemctl daemon-reload
```

Then revoke the project access token in GitLab. The state directory (`/var/lib/private/nexolab-gitlab-sync`) holds only a disposable copy of public history and can be removed. Commits already on GitLab stay there.

## Verification performed in the repository

`tests/test_ci_gitlab_sync.py` (run in CI) exercises the real program against local bare repositories, without network or credentials: equal, fast-forward with SHA verification, check mode, GitLab ahead, diverged, rewritten source, missing GitLab `main`, disk reserve, approved and unapproved tags, tag collision, concurrent runs, untouched GitLab-only branches, the `ci.skip` push option, configuration validation, log redaction, the askpass host check (including look-alike hosts and plain `http://`), and static checks that the program has no force, mirror, delete or prune path and that the units keep isolation, the credential and the limits.

Not verified by the repository tests, and therefore owner steps: the systemd sandbox on the host, the real token's scope and the protected-branch permission, and the first authenticated check and push against the corporate GitLab.
