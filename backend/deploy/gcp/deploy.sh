#!/usr/bin/env bash
# Deploy one release on the production VM (run by .github/workflows/release.yml over IAP SSH, or by hand).
#   sudo ZK_RELEASE=2026.10.14-1 ZK_REGISTRY=asia-south1-docker.pkg.dev/<project>/zoikorum/ ./backend/deploy/gcp/deploy.sh
#
# 1. Settings come from Google Secret Manager (fetch-secrets.sh) into a file readable by root only, in memory (/run).
# 2. The new images are pulled; the settings and outside services are checked; migrations run; services restart.
# 3. The settings file is removed again: running containers keep their environment, nothing stays on disk.
# Any failure stops the deploy before the running version is replaced. Values are never printed.
set -euo pipefail

: "${ZK_RELEASE:?set ZK_RELEASE to the version to deploy}"
: "${ZK_REGISTRY:?set ZK_REGISTRY to the Artifact Registry path ending in /}"
cd "$(dirname "$0")/../../.."

ENV_FILE=/run/zoikorum/.env.production
mkdir -p /run/zoikorum && chmod 700 /run/zoikorum
trap 'rm -f "$ENV_FILE" backend/.env.production' EXIT
./backend/deploy/gcp/fetch-secrets.sh "$ENV_FILE"
{ echo "ZK_RELEASE=$ZK_RELEASE"; echo "ZK_REGISTRY=$ZK_REGISTRY"; } >> "$ENV_FILE"
install -m 600 "$ENV_FILE" backend/.env.production  # compose reads env_file from here

DC=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)
gcloud auth configure-docker "${ZK_REGISTRY%%/*}" --quiet >/dev/null
"${DC[@]}" pull api worker migrate web web-staff
"${DC[@]}" run --rm api python -m zoikorum.cli check-config --connect
"${DC[@]}" run --rm migrate
"${DC[@]}" up -d --remove-orphans api worker clamav redis web web-staff
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/ready >/dev/null; then echo "Release $ZK_RELEASE is live."; exit 0; fi
  sleep 5
done
echo "The API did not become ready; previous containers were replaced. Roll back: ZK_RELEASE=<previous> $0" >&2
exit 1
