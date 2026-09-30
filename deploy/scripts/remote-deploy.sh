#!/usr/bin/env bash
# Redeploy on the server: git pull + rebuild changed services. Usage: ./remote-deploy.sh [services...]
set -euo pipefail
cd "$(dirname "$0")/.."
git -C .. pull --ff-only

if [ "$#" -gt 0 ]; then
  services=("$@")
else
  services=(backend worker frontend)
fi

sudo docker compose -p memora up -d --build "${services[@]}"
sudo docker compose -p memora ps
sleep 5
curl -fsS "http://127.0.0.1:${NGINX_PORT:-58700}/health" && echo
