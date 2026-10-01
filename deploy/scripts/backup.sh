#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE=(docker compose -p blackmoa -f "$DEPLOY_DIR/docker-compose.yml" --env-file "$DEPLOY_DIR/.env")
BACKUP_ENV="${BLACKMOA_BACKUP_ENV:-$DEPLOY_DIR/backup.env}"

if [ ! -f "$DEPLOY_DIR/.env" ]; then
  echo "missing $DEPLOY_DIR/.env" >&2
  exit 1
fi
if [ ! -f "$BACKUP_ENV" ]; then
  echo "missing $BACKUP_ENV (copy backup.env.example and configure it)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090,SC1091
. "$DEPLOY_DIR/.env"
# shellcheck disable=SC1090,SC1091
. "$BACKUP_ENV"
set +a

: "${BLACKMOA_BACKUP_DIR:?set BLACKMOA_BACKUP_DIR in backup.env}"
: "${BLACKMOA_BACKUP_AGE_RECIPIENT:?set BLACKMOA_BACKUP_AGE_RECIPIENT in backup.env}"
: "${POSTGRES_DB:=blackmoa}"
: "${POSTGRES_USER:=blackmoa}"
: "${BLACKMOA_BACKUP_RETENTION_DAYS:=28}"

for cmd in docker age sha256sum tar; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "required command missing: $cmd" >&2; exit 1; }
done
if [ -n "${BLACKMOA_BACKUP_OFFSITE_SSH:-}" ]; then
  command -v rsync >/dev/null 2>&1 || { echo "required command missing: rsync (off-site copy is enabled)" >&2; exit 1; }
fi

mkdir -p "$BLACKMOA_BACKUP_DIR"
chmod 700 "$BLACKMOA_BACKUP_DIR"
lock_dir="$BLACKMOA_BACKUP_DIR/.backup.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "another black-moa backup is already running ($lock_dir exists)" >&2
  exit 1
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/blackmoa-backup.XXXXXX")"
cleanup() {
  rm -rf "$tmp" "$lock_dir"
}
trap cleanup EXIT INT TERM
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BLACKMOA_BACKUP_DIR/blackmoa-$stamp.tar.gz.age"

cd "$DEPLOY_DIR"
echo "[backup] PostgreSQL custom dump"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$tmp/db.dump"
[ -s "$tmp/db.dump" ] || { echo "database dump is empty" >&2; exit 1; }

echo "[backup] application data (uploads, vaults, memory; cache excluded)"
"${COMPOSE[@]}" exec -T backend sh -c "tar -C /data --exclude='./cache' -czf - ." > "$tmp/data.tar.gz"

echo "[backup] Claude Code credentials/state"
# The path moved between releases (/root/.claude -> /home/blackmoa/.claude) and is empty
# until an admin has completed the device login, so resolve it from the running
# container and never fail the whole backup over it.
# shellcheck disable=SC2016  # $HOME/$BLACKMOA_CLAUDE_HOME expand in the container, not here.
claude_home="$("${COMPOSE[@]}" exec -T backend sh -c 'printf %s "${BLACKMOA_CLAUDE_HOME:-$HOME/.claude}"' 2>/dev/null | tr -d "\r")"
[ -n "$claude_home" ] || claude_home="/root/.claude"
if "${COMPOSE[@]}" exec -T backend sh -c "[ -d '$claude_home' ]" >/dev/null 2>&1; then
  "${COMPOSE[@]}" exec -T backend sh -c "tar -C '$claude_home' -czf - ." > "$tmp/claude.tar.gz"
else
  echo "[backup] warning: $claude_home is absent in the backend container (no Claude Code login yet) - archiving empty" >&2
  tar -czf "$tmp/claude.tar.gz" -T /dev/null
fi

cat > "$tmp/METADATA.txt" <<EOF
format=blackmoa-backup-v2
created_utc=$stamp
postgres_db=$POSTGRES_DB
claude_home=$claude_home
includes=db.dump,data.tar.gz,claude.tar.gz
excludes=/data/cache,deploy/.env,backup.env
EOF
(
  cd "$tmp"
  sha256sum db.dump data.tar.gz claude.tar.gz METADATA.txt > SHA256SUMS
  tar -czf - db.dump data.tar.gz claude.tar.gz METADATA.txt SHA256SUMS
) | age -r "$BLACKMOA_BACKUP_AGE_RECIPIENT" -o "$out"

[ -s "$out" ] || { echo "encrypted backup is empty" >&2; exit 1; }
echo "[backup] encrypted archive: $out"

# Delete local archives only after a new encrypted archive exists.
find "$BLACKMOA_BACKUP_DIR" -maxdepth 1 -type f -name 'blackmoa-*.tar.gz.age' \
  -mtime "+$BLACKMOA_BACKUP_RETENTION_DAYS" -delete

# An encrypted archive that only ever lives on the machine it was taken from is not a
# backup: the disk that loses the database loses it too. This copies the archive to a
# second machine over ssh, and keeps the far side trimmed the same way.
#
# It is deliberately the archive that travels, never the plaintext: the far side holds
# age ciphertext and cannot read it without the identity, which does not live there.
if [ -n "${BLACKMOA_BACKUP_OFFSITE_SSH:-}" ]; then
  : "${BLACKMOA_BACKUP_OFFSITE_DIR:?set BLACKMOA_BACKUP_OFFSITE_DIR when BLACKMOA_BACKUP_OFFSITE_SSH is enabled}"
  offsite_keep="${BLACKMOA_BACKUP_OFFSITE_KEEP:-14}"
  ssh_cmd="ssh${BLACKMOA_BACKUP_OFFSITE_PORT:+ -p $BLACKMOA_BACKUP_OFFSITE_PORT}${BLACKMOA_BACKUP_OFFSITE_KEY:+ -i $BLACKMOA_BACKUP_OFFSITE_KEY} -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
  echo "[backup] copying to $BLACKMOA_BACKUP_OFFSITE_SSH:$BLACKMOA_BACKUP_OFFSITE_DIR"
  # A copy that half-arrived is worse than none, because it looks like a backup. rsync
  # writes to a temporary name and renames only on success.
  rsync -e "$ssh_cmd" --partial --inplace --timeout=600 "$out" \
        "$BLACKMOA_BACKUP_OFFSITE_SSH:$BLACKMOA_BACKUP_OFFSITE_DIR/.$(basename "$out").part"
  # shellcheck disable=SC2029  # the remote side is meant to expand these.
  $ssh_cmd "$BLACKMOA_BACKUP_OFFSITE_SSH" "set -e
    mkdir -p '$BLACKMOA_BACKUP_OFFSITE_DIR'
    mv '$BLACKMOA_BACKUP_OFFSITE_DIR/.$(basename "$out").part' '$BLACKMOA_BACKUP_OFFSITE_DIR/$(basename "$out")'
    ls -1t '$BLACKMOA_BACKUP_OFFSITE_DIR'/blackmoa-*.tar.gz.age 2>/dev/null | tail -n +$((offsite_keep + 1)) | xargs -r rm -f"
  echo "[backup] off-site copy done"
fi

if [ -n "${RESTIC_REPOSITORY:-}" ]; then
  command -v restic >/dev/null 2>&1 || { echo "RESTIC_REPOSITORY set but restic is missing" >&2; exit 1; }
  : "${RESTIC_PASSWORD_FILE:?set RESTIC_PASSWORD_FILE when RESTIC_REPOSITORY is enabled}"
  echo "[backup] copying encrypted archive to restic repository"
  restic backup "$out" --tag blackmoa
  restic forget --tag blackmoa --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune
fi

echo "[backup] done"
