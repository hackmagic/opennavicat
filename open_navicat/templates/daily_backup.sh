#!/usr/bin/env bash
# Daily backup template — OpenNavicat
# Usage: bash daily_backup.sh

set -euo pipefail

CONN_NAME="${1:-default}"
BACKUP_DIR="${2:-./backups}"
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

echo "=== Daily backup: $CONN_NAME ==="
opennavicat backup create "$CONN_NAME" --output "$BACKUP_DIR"

echo "=== Rotating backups older than $RETENTION_DAYS days ==="
find "$BACKUP_DIR" -name "*.sql" -mtime +$RETENTION_DAYS -delete

echo "=== Done ==="
opennavicat backup list "$CONN_NAME"
