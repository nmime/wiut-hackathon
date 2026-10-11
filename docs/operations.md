# Production operations

Install the repository's operations on the Ubuntu production host after `scripts/deploy.sh` has completed successfully:

```sh
cd /opt/flowcredit/repo
bash scripts/install-operations.sh
```

Run this as root. It requires the host's existing Docker/Compose installation, Python 3.11 or later, `openssl`, and systemd. It creates one verified private backup and accepts the currently healthy scorer identities before enabling four units belonging only to this application. It does not alter nginx, certificates, firewall rules, unrelated services, or other applications' schedules. Installation stops if the initial backup or health checks fail.

`flowcredit-backup.timer` runs nightly at 02:15 Asia/Tashkent with up to 15 minutes of randomized delay. Missed scheduled backups run after the timer resumes. `flowcredit-health.timer` runs every five minutes, starting two minutes after boot, with up to 30 seconds of randomized delay. Both services are bounded oneshot operations, not additional public endpoints.

## Backups and retention

Scheduled backups are stored in the ignored `artifacts/scheduled-backups/` directory. Directories have permissions `700`, and archives and status files have permissions `600`. Each archive contains:

- A PostgreSQL custom-format dump of `wiut`, made with a transaction-consistent `pg_dump` without stopping application writes.
- The exact complete JSONL prefix of each existing ML audit volume, including the optional teammate volume even if its container is stopped. The separate snapshot helper resolves the stack's already built `flowcredit-ml` image to its complete immutable image ID and uses read-only volumes, no network, no capabilities, and the audit owner's numeric UID. It runs only standard-library Python, without starting or evaluating a model, and does not depend on the running container's old image metadata remaining present.
- `.env.production`, including database and authentication-encryption credentials. These are secrets: the archive is private but is **not encrypted**.
- A manifest with SHA-256 checksums and audit snapshot lengths/record counts. The script reads and verifies every archive member before atomically publishing the archive.

Both scorer writers persist their records with `fsync`. The teammate writer and snapshot coordinate with a file lock. The default writer appends a record in one write; the snapshot fixes its initial file size and validates every complete JSON record. If it captures a concurrent incomplete final record, it retains the preceding complete bytes and reports the omitted tail length. An invalid complete record, truncated source, oversized record, database failure, or checksum failure aborts archive publication and prevents retention.

The database and the two logs have independent snapshot boundaries. This is not a single atomic snapshot spanning all three resources: an in-flight assessment may be present in one log before its related database attempt completes. Preserve the input/result hashes and correlate records when investigating. Snapshotting does not make a local audit log tamper-proof or externally anchored.

Retention removes only regular, non-symlink archives matching `flowcredit-scheduled-YYYYMMDDTHHMMSSZ-<16 hex characters>.tar.gz` older than 14 days, and only after a newly created archive passes verification. Manual dumps, deployment backups, unrelated files, and symlinks are preserved. To run a backup manually or choose a bounded retention period:

```sh
python3 scripts/operations/backup.py
python3 scripts/operations/backup.py --keep-days 30
```

Backups and deploys use the same nonblocking lock so migrations cannot run during a snapshot. A competing operation exits without proceeding. Archives on the same machine do not protect against host loss. Copy them to a secured location controlled by the operator, using SSH or an equivalent encrypted transport; do not upload them to an unapproved service or repository. For example, from the maintainer's Mac, replace the archive basename below with the one reported by a successful backup:

```sh
umask 077
mkdir -p artifacts/off-host-backups
chmod 700 artifacts/off-host-backups
scp -i /Users/nmi/.ssh/nmi -o UseKeychain=yes -o IdentitiesOnly=yes -o BatchMode=yes \
  root@142.132.231.156:/opt/flowcredit/repo/artifacts/scheduled-backups/ARCHIVE.tar.gz \
  artifacts/off-host-backups/
chmod 600 artifacts/off-host-backups/ARCHIVE.tar.gz
```

Configure separate encrypted off-host storage and confirm its retention independently before relying on unattended disaster recovery. No off-host destination or third-party credentials are guessed by these scripts.

## Restore verification

Select a trusted archive created by this application and run:

```sh
python3 scripts/operations/verify_backup.py artifacts/scheduled-backups/ARCHIVE.tar.gz
```

The verifier checks archive structure and every checksum, restores the database into a newly generated `flowcredit_restore_check_<random hex>` database, and counts the essential account, workspace, business, assessment, decision, and audit tables. It always attempts to drop that generated database afterward, including when restoration fails. Its command line accepts an archive path only; callers cannot choose the live database as a restoration target. It leaves a private `artifacts/operations/restore-status.json` summary without transaction contents. If PostgreSQL becomes unavailable during cleanup, inspect for the generated database and remove it deliberately after recovery.

Verification consumes extra PostgreSQL storage and CPU. Only restore trusted archives: their self-contained checksums detect accidental corruption, not a malicious archive whose payload and manifest were both replaced. A real recovery requires an explicit operator decision, a stopped application, restored database/audit volumes, and the matching private environment file. Do not rotate or discard `AUTH_ENCRYPTION_KEY` independently of stored MFA secrets; retain its secured copy with every backup. Verify recovery in isolation before changing the running database.

## Health checks and model identities

The monitor checks:

- Loopback API/database health and public HTTPS API/database health, with normal TLS verification.
- Anonymous business-list access remains protected by HTTP `401`.
- Every installed FlowCredit container is running and healthy, and the selected scorer is available.
- Scorer version and complete artifact SHA-256 match the accepted baseline. The teammate baseline additionally preserves its actual full source-archive and bridge-source SHA-256 values. No nonexistent source digest is invented for the default scorer.
- At least 5 GiB disk headroom and less than 90% usage on the repository filesystem.
- The origin certificate matches the configured hostname, remains valid for at least 14 days, and the host's existing `certbot.timer` is active.
- A scheduled backup exists within the previous 26 hours and the most recent backup operation succeeded.

Status and baseline files live under the private `artifacts/operations/` directory. Checks refresh `health-status.json` on every run but write their journal message only when the check state, selected scorer, or model identity changes. Failure returns a nonzero exit status so systemd records a failed check. During a deploy or backup lock, the health status reports maintenance and resumes checking on the next run. No customer data, environment values, upstream error bodies, email, or third-party notifications are included.

Run a check or inspect schedules and journals:

```sh
python3 scripts/operations/check_health.py
systemctl list-timers flowcredit-backup.timer flowcredit-health.timer
systemctl status flowcredit-backup.service flowcredit-health.service --no-pager
journalctl -u flowcredit-backup.service -u flowcredit-health.service --since today --no-pager
```

After a deliberately qualified model or bridge update, inspect the actual serving artifact against the frozen validation evidence, then accept its new identity:

```sh
python3 scripts/operations/check_health.py --accept-models
```

Acceptance succeeds only when all other checks pass. Switching to the private teammate scorer or rebuilding an artifact does not automatically erase the previous identity baseline. The accepted baseline is operational evidence, not a new accuracy evaluation.

These are local monitoring and recovery controls. Someone must inspect failures; a host outage cannot report itself through its own journal. External uptime checks, paging delivery, an off-host backup destination, and a periodically rehearsed disaster recovery procedure still require operator-managed services. The app remains an MVP, not a claim of certified banking infrastructure.
