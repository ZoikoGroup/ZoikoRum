#!/usr/bin/env bash
# Deploy one release on the production VM (run by .github/workflows/release.yml over IAP SSH, or by hand).
#   sudo ZK_RELEASE=2026.10.14-1 ZK_REGISTRY=asia-south1-docker.pkg.dev/<project>/zoikorum/ ./backend/deploy/gcp/deploy.sh
#
# 1. Settings come from Google Secret Manager (fetch-secrets.sh) into a file readable by root only, in memory (/run).
# 2. The images' signatures are verified (cosign, keyless: signed by this repository's Release workflow) when cosign is
#    installed on the VM; ZK_COSIGN_REQUIRED=true makes a missing cosign or a bad signature stop the deploy. Then the new
#    images are pulled; the settings and outside services are checked; migrations run.
# 3. Canary: the new API starts next to the running one and must answer /ready before anything is switched.
# 4. Switch: the services restart on the new release and must answer /ready through the web app. If they do not, the
#    previous release is started again automatically (migrations only ever add, so it runs on the newer schema).
# 5. The settings file is removed again: running containers keep their environment, nothing stays on disk.
# Any failure before step 4 leaves the running version untouched. Values are never printed.
set -euo pipefail

: "${ZK_RELEASE:?set ZK_RELEASE to the version to deploy}"
: "${ZK_REGISTRY:?set ZK_REGISTRY to the Artifact Registry path ending in /}"
cd "$(dirname "$0")/../../.."

STATE=/var/lib/zoikorum/release  # the release that is live now (written after every successful switch)
ENV_FILE=/run/zoikorum/.env.production
CANARY="zk-canary-$$"
mkdir -p /run/zoikorum /var/lib/zoikorum && chmod 700 /run/zoikorum
trap 'docker rm -f "$CANARY" >/dev/null 2>&1 || true; rm -f "$ENV_FILE" backend/.env.production' EXIT
PREVIOUS="$(cat "$STATE" 2>/dev/null || true)"

./backend/deploy/gcp/fetch-secrets.sh "$ENV_FILE"
echo "ZK_REGISTRY=$ZK_REGISTRY" >> "$ENV_FILE"
install -m 600 "$ENV_FILE" backend/.env.production  # compose reads env_file from here
export ZK_RELEASE ZK_REGISTRY  # the shell's ZK_RELEASE picks the image tag (it wins over --env-file)

DC=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)
gcloud auth configure-docker "${ZK_REGISTRY%%/*}" --quiet >/dev/null

# Signature check before pulling (best effort unless ZK_COSIGN_REQUIRED=true).
verify_signatures() {
  local repo="${ZK_COSIGN_REPOSITORY:-}" image
  if ! command -v cosign >/dev/null 2>&1; then
    if [ "${ZK_COSIGN_REQUIRED:-false}" = true ]; then echo "cosign is not installed and signatures are required." >&2; return 1; fi
    echo "cosign is not installed on this VM: image signatures not checked." >&2
    return 0
  fi
  if [ -z "$repo" ]; then
    if [ "${ZK_COSIGN_REQUIRED:-false}" = true ]; then echo "ZK_COSIGN_REPOSITORY (owner/name) is needed to check signatures." >&2; return 1; fi
    echo "ZK_COSIGN_REPOSITORY not set: image signatures not checked." >&2
    return 0
  fi
  for image in zoikorum-backend zoikorum-web zoikorum-web-staff; do
    if ! cosign verify "${ZK_REGISTRY}${image}:${ZK_RELEASE}"         --certificate-identity-regexp "^https://github.com/${repo}/\.github/workflows/release\.yml@"         --certificate-oidc-issuer https://token.actions.githubusercontent.com >/dev/null; then
      echo "The signature of ${image}:${ZK_RELEASE} could not be verified; nothing was deployed." >&2
      return 1
    fi
  done
  echo "Image signatures verified."
}
verify_signatures
"${DC[@]}" pull api worker migrate web web-staff
"${DC[@]}" run --rm api python -m zoikorum.cli check-config --connect
"${DC[@]}" run --rm migrate

# Canary: the new API image, started beside the live one (same network, settings and database), must become ready.
"${DC[@]}" run -d --no-deps --name "$CANARY" api >/dev/null
ready=0
for _ in $(seq 1 24); do
  if docker exec "$CANARY" python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).status == 200 else 1)" 2>/dev/null; then
    ready=1; break
  fi
  sleep 5
done
if [ "$ready" != 1 ]; then
  echo "Canary of $ZK_RELEASE did not become ready; nothing was switched. Its last log lines:" >&2
  docker logs --tail 40 "$CANARY" >&2 || true
  exit 1
fi
docker rm -f "$CANARY" >/dev/null

switch_to() {
  ZK_RELEASE="$1" "${DC[@]}" up -d --remove-orphans api worker clamav redis web web-staff
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8080/ready >/dev/null && curl -fsS http://127.0.0.1:8081/ready >/dev/null; then return 0; fi
    sleep 5
  done
  return 1
}

if switch_to "$ZK_RELEASE"; then
  echo "$ZK_RELEASE" > "$STATE"
  echo "Release $ZK_RELEASE is live."
  exit 0
fi
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$ZK_RELEASE" ]; then
  echo "Release $ZK_RELEASE did not become ready after the switch; rolling back to $PREVIOUS." >&2
  if switch_to "$PREVIOUS"; then echo "Rolled back: $PREVIOUS is live again." >&2; exit 1; fi
  echo "The rollback to $PREVIOUS did not become ready either. Check: ${DC[*]} logs api" >&2
else
  echo "Release $ZK_RELEASE did not become ready and there is no earlier release on record to roll back to." >&2
fi
exit 1
