#!/usr/bin/env bash
set -euo pipefail
umask 077

repository=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ $EUID -eq 0 ]] || { printf 'Run as root on the production host.\n' >&2; exit 1; }
[[ "$repository" =~ ^/[A-Za-z0-9_./-]+$ ]] || { printf 'Repository path must be an absolute path without spaces or systemd specifiers.\n' >&2; exit 1; }
for binary in python3 systemctl docker openssl; do
  command -v "$binary" >/dev/null || { printf 'Required command missing: %s\n' "$binary" >&2; exit 1; }
done

# Installation pins only an entirely healthy, previously qualified deployment.
# Create the initial verified backup before installing timers.
python3 "$repository/scripts/operations/backup.py"
python3 "$repository/scripts/operations/check_health.py" --accept-models
for unit in flowcredit-backup.service flowcredit-backup.timer flowcredit-health.service flowcredit-health.timer; do
  pending=$(mktemp /etc/systemd/system/.flowcredit-unit.XXXXXX)
  sed "s|@ROOT@|$repository|g" "$repository/docker/systemd/$unit" > "$pending"
  chmod 644 "$pending"
  mv -- "$pending" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now flowcredit-backup.timer flowcredit-health.timer
printf 'FlowCredit nightly backups and five-minute health checks are installed. See docs/operations.md for journals, restoration checks and off-host storage.\n'
