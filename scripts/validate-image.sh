#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="hermes-agent-jregeimbal-homelab"
REGISTRY="ghcr.io"
OWNER="jregeimbal"
TAG="local-dev"
IMAGE="${REGISTRY}/${OWNER}/${IMAGE_NAME}:${TAG}"

echo "=== Building ${IMAGE} ==="
docker build -t "${IMAGE}" .

echo ""
echo "=== Verifying claude CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" claude --version

echo ""
echo "=== Verifying discord package ==="
docker run --rm --entrypoint "" -e PYTHONPATH=/opt/data/py-global "${IMAGE}" python3 -c "import discord; print(discord.__version__)"

echo ""
echo "=== Verifying gh CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" gh --version

echo ""
echo "=== Verifying opencode ==="
docker run --rm --entrypoint "" "${IMAGE}" opencode --help 2>&1 | head -5

echo ""
echo "=== All checks passed ==="
