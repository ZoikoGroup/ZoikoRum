#!/usr/bin/env bash
# Write the production settings from Google Secret Manager into one env file (mode 600). Never prints a value.
#   ./fetch-secrets.sh /run/zoikorum/.env.production
#
# Every line of secrets.list names a setting (ZK_...). Its value is the latest version of the secret with the same name
# in lower case with dashes, e.g. ZK_JWT_SECRET -> secret "zk-jwt-secret". Plain, non-secret settings can be stored the
# same way so the server needs nothing else. The VM's service account needs roles/secretmanager.secretAccessor on them.
set -euo pipefail
OUT="${1:?usage: fetch-secrets.sh <output file>}"
LIST="$(dirname "$0")/secrets.list"
umask 077
: > "$OUT"
missing=0
while read -r name; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  secret="$(echo "$name" | tr '[:upper:]_' '[:lower:]-')"
  if value="$(gcloud secrets versions access latest --secret="$secret" 2>/dev/null)"; then
    printf '%s=%s\n' "$name" "$value" >> "$OUT"
  else
    echo "Missing in Secret Manager: $secret" >&2
    missing=1
  fi
done < "$LIST"
[[ $missing -eq 0 ]] || { rm -f "$OUT"; echo "Stopped: create the missing secrets first." >&2; exit 1; }
echo "Settings written ($(wc -l < "$OUT") values)."
