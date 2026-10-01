#!/usr/bin/env bash
# One-time: put the black-moa hostname on the host's cloudflared tunnel and point DNS at it.
#
#   ./tunnel-add.sh <host> [port] [config] [unit]
#   e.g. ./tunnel-add.sh black.memo-ora.com 58710 ~/.cloudflared/config.yml cloudflared-memora
#
# DNS is a CNAME to <tunnel id>.cfargotunnel.com (proxied). `cloudflared tunnel route dns` only works
# when the tunnel's cert.pem belongs to the hostname's zone — for any other zone it silently creates
# "<host>.<cert zone>" instead. So when CF_API_TOKEN (Zone:DNS:Edit) and CF_ZONE_ID are set, the record
# is made through the API; otherwise the script prints what to create.
set -euo pipefail
HOST=${1:?host, e.g. black.memo-ora.com}
PORT=${2:-58710}
CFG=${3:-$HOME/.cloudflared/config.yml}
UNIT=${4:-}

if grep -q "hostname: $HOST\$" "$CFG"; then echo "ingress already present"; else
  python3 - "$HOST" "$PORT" "$CFG" <<'PY'
import sys
host, port, cfg = sys.argv[1:4]
s = open(cfg).read()
entry = f"  - hostname: {host}\n    service: http://localhost:{port}\n"
marker = "  - service: http_status:404"
assert marker in s, "catch-all rule not found"
open(cfg, "w").write(s.replace(marker, entry + "\n" + marker, 1))
print("ingress added")
PY
  [ -n "$UNIT" ] && sudo systemctl restart "$UNIT"
fi

TUNNEL=$(awk '/^tunnel:/ {print $2}' "$CFG")
TARGET="$TUNNEL.cfargotunnel.com"
if [ -n "${CF_API_TOKEN:-}" ] && [ -n "${CF_ZONE_ID:-}" ]; then
  curl -fsS -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H 'content-type: application/json' \
    -d "{\"type\":\"CNAME\",\"name\":\"$HOST\",\"content\":\"$TARGET\",\"proxied\":true}" | head -c 300; echo
else
  echo "Create DNS: CNAME $HOST -> $TARGET (proxied)"
fi
