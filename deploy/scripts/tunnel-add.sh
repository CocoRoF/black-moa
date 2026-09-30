#!/usr/bin/env bash
# One-time: add the memora hostname to the existing cloudflared tunnel (hr106) and create the DNS route.
set -euo pipefail
HOST=${1:-memora.hrletsgo.me}
PORT=${2:-58700}
CFG=/etc/cloudflared/config.yml
if sudo grep -q "hostname: $HOST" $CFG; then echo "ingress already present"; else
  sudo python3 - "$HOST" "$PORT" "$CFG" <<'PY'
import sys, re
host, port, cfg = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(cfg).read()
entry = f"  - hostname: {host}\n    service: http://localhost:{port}\n"
s = s.replace("  - service: http_status:404", entry + "  - service: http_status:404", 1)
open(cfg, "w").write(s)
print("ingress added")
PY
  sudo systemctl restart cloudflared
fi
cloudflared tunnel route dns hr106 "$HOST" || true
