#!/usr/bin/env bash
# Decrypt and structurally verify an Memora backup without touching the live stack.
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BACKUP_ENV="${MEMORA_BACKUP_ENV:-$DEPLOY_DIR/backup.env}"

if [ ! -f "$BACKUP_ENV" ]; then
  echo "missing $BACKUP_ENV" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090,SC1091
. "$BACKUP_ENV"
set +a

: "${MEMORA_BACKUP_DIR:?set MEMORA_BACKUP_DIR in backup.env}"
: "${MEMORA_BACKUP_AGE_IDENTITY:?set MEMORA_BACKUP_AGE_IDENTITY in backup.env}"
for cmd in age sha256sum tar pg_restore; do
  command -v "$cmd" >/dev/null 2>&1 || {
    # pg_restore is the one a fresh host does not have: it comes from postgresql-client,
    # which the stack itself never needed. Name the package rather than the binary alone.
    hint=""
    [ "$cmd" = "pg_restore" ] && hint=" (apt install postgresql-client-16)"
    echo "required command missing: $cmd$hint" >&2
    exit 1
  }
done
if [ ! -r "$MEMORA_BACKUP_AGE_IDENTITY" ]; then
  echo "age identity is not readable" >&2
  exit 1
fi

archive="${1:-}"
if [ -z "$archive" ]; then
  archive="$(find "$MEMORA_BACKUP_DIR" -maxdepth 1 -type f -name 'memora-*.tar.gz.age' -printf '%T@ %p\n' \
    | sort -nr | head -n1 | cut -d' ' -f2-)"
fi
if [ -z "$archive" ] || [ ! -r "$archive" ]; then
  echo "backup archive not found" >&2
  exit 1
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/memora-verify.XXXXXX")"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM

age -d -i "$MEMORA_BACKUP_AGE_IDENTITY" "$archive" > "$tmp/archive.tar.gz"
tar -xzf "$tmp/archive.tar.gz" -C "$tmp"
(
  cd "$tmp"
  sha256sum -c SHA256SUMS
)
pg_restore --list "$tmp/db.dump" >/dev/null
tar -tzf "$tmp/data.tar.gz" >/dev/null
tar -tzf "$tmp/claude.tar.gz" >/dev/null

echo "[verify] OK: $archive"
cat "$tmp/METADATA.txt"
