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
echo "=== Verifying zeroshot skill file ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /root/.hermes/skills/software-development/zeroshot/SKILL.md && echo "Skill file present at /root/.hermes/skills/software-development/zeroshot/SKILL.md"

echo ""
echo "=== All checks passed ==="
