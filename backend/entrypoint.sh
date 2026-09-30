#!/usr/bin/env bash
set -euo pipefail

# Named volumes from older releases may still be root-owned. Repair them once,
# then replace PID 1 with an unprivileged tini supervisor. gosu performs only a
# one-way privilege drop; application processes never regain root.
if [ "$(id -u)" -eq 0 ]; then
  mkdir -p /data /home/memora/.claude /home/memora/.cache
  marker=/data/.owner-uid-10001
  if [ ! -f "$marker" ]; then
    echo "[entrypoint] migrating /data ownership to memora (uid 10001)"
    chown -R 10001:10001 /data
    touch "$marker"
    chown 10001:10001 "$marker"
  else
    # 한 번 찍고 마는 표시로는 모자랐다. 어떤 경로 하나가 root 소유로 생기면 그
    # 표시 때문에 영영 고쳐지지 않고, 앱은 거기에 쓰지 못한다 — 금고 폴더 하나가
    # 그렇게 되어 그 비서와는 대화 자체가 안 됐다(2026-09-23).
    #
    # 그래서 **틀어진 것만** 볼 때마다 되돌린다. 멀쩡하면 find 한 번으로 끝난다.
    strays=$(find /data ! -user 10001 -print -quit 2>/dev/null || true)
    if [ -n "$strays" ]; then
      echo "[entrypoint] repairing paths not owned by memora (uid 10001)"
      find /data ! -user 10001 -exec chown 10001:10001 {} + 2>/dev/null || true
    fi
  fi
  chown -R 10001:10001 /home/memora/.claude /home/memora/.cache
  exec gosu memora /usr/bin/tini -- "$0" "$@"
fi

cd /app
case "${1:-api}" in
  api)
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
    echo "[entrypoint] starting api"
    exec uvicorn memora.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75
    ;;
  worker)
    echo "[entrypoint] waiting for schema"
    attempt=0
    while [ "$attempt" -lt 60 ]; do
      if alembic current 2>/dev/null | grep -q '(head)'; then
        break
      fi
      attempt=$((attempt + 1))
      sleep 2
    done
    if ! alembic current 2>/dev/null | grep -q '(head)'; then
      echo "[entrypoint] schema did not reach alembic head" >&2
      exit 1
    fi
    exec python -m memora.worker
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  shell)
    exec bash
    ;;
  *)
    exec "$@"
    ;;
esac
