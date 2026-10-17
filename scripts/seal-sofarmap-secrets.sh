#!/usr/bin/env bash
# Create and seal everything the sofarmap deploy needs. Run once, with kubectl access to the cluster
# (kubeseal only fetches the public certificate), from the root of this repo, then commit the result.
#
#   - flux/apps/sofarmap-secrets.sealedsecret.yaml   generated passwords/keys + the map keys you enter
#   - flux/apps/authentik-oidc-clients.sealedsecret.yaml   gains SOFARMAP_OIDC_CLIENT_SECRET (merged in
#                                                    without touching the existing keys)
#   - flux/apps/sofarmap-ghcr-pull.sealedsecret.yaml read:packages token for the private images
#
# Plaintext lives only in memory and a mode-600 temp file that is removed on exit. The same OIDC client
# secret goes into both namespaces. GOOGLE_MAPS_API_KEY and ORS_API_KEY may be left empty (the editor
# then runs without the basemap / directions).
set -euo pipefail
cd "$(dirname "$0")/.."

seal() { kubeseal --controller-namespace flux-system --controller-name sealed-secrets-controller --format yaml "$@"; }
umask 077
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT

read -r -s -p "GitHub token with read:packages only (for the private images): " ghcr; echo
read -r -p  "GOOGLE_MAPS_API_KEY (browser key; referrer-restrict it to https://sofarmap.hartley-gray.ts.net/*): " gmaps
read -r -p  "ORS_API_KEY (openrouteservice.org; optional): " ors
[ -n "$ghcr" ] || { echo "no token entered" >&2; exit 1; }

pg=$(openssl rand -hex 24)
oidc=$(openssl rand -hex 32)
cat > "$tmp" <<ENV
POSTGRES_PASSWORD=$pg
DATABASE_URL=postgres://sofarmap:$pg@sofarmap-postgres.sofarmap.svc.cluster.local:5432/sofarmap?sslmode=disable
SESSION_SECRET=$(openssl rand -base64 32)
TOKEN_ENCRYPTION_KEY=$(openssl rand -base64 32)
OIDC_CLIENT_SECRET=$oidc
GOOGLE_MAPS_API_KEY=$gmaps
ORS_API_KEY=$ors
ENV
kubectl create secret generic sofarmap-secrets -n sofarmap --from-env-file="$tmp" --dry-run=client -o yaml \
  | seal > flux/apps/sofarmap-secrets.sealedsecret.yaml

printf 'SOFARMAP_OIDC_CLIENT_SECRET=%s\n' "$oidc" > "$tmp"
kubectl create secret generic authentik-oidc-clients -n authentik --from-env-file="$tmp" --dry-run=client -o yaml \
  | seal --merge-into flux/apps/authentik-oidc-clients.sealedsecret.yaml

kubectl create secret docker-registry ghcr-pull -n sofarmap --docker-server=ghcr.io \
  --docker-username="${GHCR_USER:-jregeimbal}" --docker-password="$ghcr" --dry-run=client -o yaml \
  | seal > flux/apps/sofarmap-ghcr-pull.sealedsecret.yaml

echo "Sealed. Review 'git status', commit the three files, and push."
