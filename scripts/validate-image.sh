#!/bin/bash
set -euo pipefail

IMAGE="${1:-ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev}"

echo "=== Building ${IMAGE} ==="
docker build -t "${IMAGE}" .

echo ""
echo "=== Verifying claude CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" claude --version

echo ""
echo "=== Verifying discord package ==="
docker run --rm --entrypoint "" "${IMAGE}" python3 -c "import discord; print('discord package version:', discord.__version__)"

echo ""
echo "=== Verifying gh CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" gh --version

echo ""
echo "=== Verifying opencode ==="
docker run --rm --entrypoint "" "${IMAGE}" opencode --version

echo ""
echo "=== Verifying zeroshot CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" zeroshot --version

echo ""
echo "=== Verifying config-defaults: gitconfig ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /opt/config-defaults/git/gitconfig \
  || { echo "ERROR: Missing /opt/config-defaults/git/gitconfig"; exit 1; }
echo "gitconfig present"

echo ""
echo "=== Verifying config-defaults: claude settings ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /opt/config-defaults/claude/settings.json \
  || { echo "ERROR: Missing /opt/config-defaults/claude/settings.json"; exit 1; }
echo "claude settings present"

echo ""
echo "=== Verifying config-defaults: opencode config ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /opt/config-defaults/opencode/opencode.json \
  || { echo "ERROR: Missing /opt/config-defaults/opencode/opencode.json"; exit 1; }
echo "opencode config present"

echo ""
echo "=== All checks passed ==="
