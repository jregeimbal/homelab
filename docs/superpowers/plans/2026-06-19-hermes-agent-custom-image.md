# Custom Hermes Agent Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Dockerfile and GitHub Actions workflow that builds a custom hermes-agent image with Claude Code CLI, publishes it to ghcr on Dockerfile changes, and auto-updates Kubernetes manifests.

**Architecture:** Single Dockerfile at repo root extends `nousresearch/hermes-agent:v2026.5.29.2` with Claude Code installed via npm. A GitHub Actions workflow triggers on Dockerfile changes, builds multi-arch images, pushes to ghcr, then bumps the image tag in both hermes deployment manifests.

**Tech Stack:** Docker Buildx (multi-arch), GitHub Actions, GitHub Container Registry, YAML manifest editing via shell tools.

---

### Task 1: Create Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

Create `Dockerfile` at the repository root with this exact content:

```dockerfile
FROM nousresearch/hermes-agent:v2026.5.29.2

RUN npm install -g @anthropic-ai/claude-code && \
    claude --version
```

This extends the base hermes-agent image and installs Claude Code CLI globally via npm. The `claude --version` run ensures the binary is functional at build time (fail-fast if installation is broken).

- [ ] **Step 2: Verify Dockerfile syntax**

Run: `docker buildx imagetools inspect nousresearch/hermes-agent:v2026.5.29.2`

Expected: Image exists and is accessible. If this fails, the base image tag may need verification.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile for custom hermes agent with Claude Code"
```

---

### Task 2: Create GitHub Actions workflow - job structure

**Files:**
- Create: `.github/workflows/docker-build.yml`

- [ ] **Step 1: Write the workflow file skeleton**

Create `.github/workflows/docker-build.yml` with this exact content:

```yaml
---
name: Docker Build

on:
  push:
    branches: [main]
    paths: [Dockerfile]
  pull_request:
    branches: [main]
    paths: [Dockerfile]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

env:
  IMAGE_NAME: hermes-agent-jregeimbal-homelab
  REGISTRY: ghcr.io
  OWNER: jregeimbal

jobs:
  build-push:
    name: Build and Push
    runs-on: ubuntu-latest
    timeout-minutes: 30
    permissions:
      contents: read
      packages: write
    outputs:
      version-tag: ${{ steps.meta.outputs.tags }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.OWNER }}/${{ env.IMAGE_NAME }}
          tags: |
            type=sha,format=short
            type=raw,value={{version}},enable=${{ github.event_name == 'push' }}
            type=raw,value={{date 'YYYY-MM-DD'}},enable=${{ github.event_name == 'push' }}
            type=raw,value=latest,enable=${{ github.event_name == 'push' }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: ${{ github.event_name == 'push' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  validate-manifests:
    name: Validate K8s Manifests
    runs-on: ubuntu-latest
    timeout-minutes: 2
    needs: [build-push]
    if: github.event_name == 'push' && success()
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Cache kubeconform
        uses: actions/cache@v4
        with:
          path: /usr/local/bin/kubeconform
          key: kubeconform-${{ hashFiles('.github/workflows/docker-build.yml') }}

      - name: Install kubeconform
        run: |
          curl -sSfL https://github.com/yannh/kubeconform/releases/download/v0.7.0/kubeconform-linux-amd64.tar.gz | tar xz -C /usr/local/bin

      - name: Validate K8s manifests
        run: |
          kubeconform -summary -ignore-missing-schemas \
            -schema-location "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/" \
            flux/apps/hermes-jon.yaml \
            flux/apps/hermes-ana.yaml

  bump-version:
    name: Bump Image Version
    runs-on: ubuntu-latest
    timeout-minutes: 5
    needs: [build-push, validate-manifests]
    if: github.event_name == 'push' && success()
    env:
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Get base image version
        id: version
        run: |
          VERSION=$(grep '^FROM ' Dockerfile | awk '{print $2}' | sed 's/.*://')
          echo "version=$VERSION" >> "$GITHUB_OUTPUT"
          echo "Base image version: $VERSION"

      - name: Update hermes-jon.yaml
        run: |
          VERSION="${{ steps.version.outputs.version }}"
          sed -i "s|image: nousresearch/hermes-agent:${VERSION}|image: ${REGISTRY}/${OWNER}/${IMAGE_NAME}:${VERSION}|g" flux/apps/hermes-jon.yaml

      - name: Update hermes-ana.yaml
        run: |
          VERSION="${{ steps.version.outputs.version }}"
          sed -i "s|image: nousresearch/hermes-agent:main|image: ${REGISTRY}/${OWNER}/${IMAGE_NAME}:${VERSION}|g" flux/apps/hermes-ana.yaml
          sed -i 's|tag: main|tag: '"${VERSION}"'|g' flux/apps/hermes-ana.yaml

      - name: Commit and push manifest updates
        run: |
          VERSION="${{ steps.version.outputs.version }}"
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml
          git commit -m "chore: bump hermes image to ${VERSION}" || echo "No changes to commit"
          git push
```

Key design decisions in the workflow:
- **Trigger:** `push` and `pull_request` on `main` branch, scoped to `Dockerfile` path only (no unnecessary builds on unrelated changes)
- **Three jobs in sequence:** `build-push` → `validate-manifests` → `bump-version`. Each depends on the previous succeeding.
- **PR mode:** On pull requests, only `build-push` runs (pushes are disabled via `push: ${{ github.event_name == 'push' }}`). This gives a dry-run build to verify the Dockerfile before merging.
- **Production mode:** On pushes to `main`, all three jobs run: build multi-arch, validate K8s manifests with kubeconform, then bump version in manifests.
- **Tags on push:** version tag (e.g., `v2026.5.29.2`), date tag (`2026-06-19`), and `latest`. The sha tag is always included for traceability.
- **Multi-arch:** `linux/amd64` + `linux/arm64` via Docker Buildx with GitHub Actions cache for build speed.
- **GHCR auth:** Uses `${{ secrets.GITHUB_TOKEN }}` which has `packages: write` permission by default.
- **Manifest bot commit:** Uses a checkout with `token: ${{ secrets.GITHUB_TOKEN }}` so the push back to `main` doesn't re-trigger the workflow (the `[bot]` suffix on the actor prevents recursion).

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docker-build.yml
git commit -m "ci: add docker build workflow with auto version bump"
```

---

### Task 3: Verify the workflow runs correctly

**Files:**
- No file changes, verification only

- [ ] **Step 1: Create a test PR to validate the Dockerfile builds**

Create a branch from `main`, make a trivial change to the Dockerfile (e.g., add a comment), and open a PR:

```bash
git checkout -b test/dockerfile-build
# Edit Dockerfile to add a comment line
git add Dockerfile
git commit -m "test: verify docker build"
git push
# Create PR via gh CLI or GitHub UI
gh pr create --title "test: verify docker build" --body "Verify PR-mode build passes"
```

Expected: The `Docker Build` workflow runs on the PR, completes the `build-push` job successfully (with `push: false`, so no image is actually published), and the check passes.

- [ ] **Step 2: Merge the PR**

Merge the PR to `main`. This triggers the full workflow:
1. `build-push` runs with `push: true` — image is built multi-arch and pushed to ghcr
2. `validate-manifests` runs — kubeconform validates both hermes YAML files pass (they still reference the old image, which is fine for this test)
3. `bump-version` runs — reads the base version from the Dockerfile, updates both manifests

Expected: All three jobs pass. A new commit is pushed to `main` updating both `hermes-jon.yaml` and `hermes-ana.yaml` to reference `ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:<version>`.

Verify the pushed image exists:
```bash
docker buildx imagetools inspect ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.5.29.2
```

Expected: Image manifest shows both `linux/amd64` and `linux/arm64` platforms.

- [ ] **Step 3: Verify K8s manifests were updated**

Check the auto-committed changes:
```bash
git log --oneline -5
grep -n 'ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab' flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml
```

Expected: Both files contain the new ghcr image reference with the correct version tag. Init containers in `hermes-jon.yaml` are also updated to use the new image.

---

## File Summary

| File | Action | Purpose |
|------|--------|---------|
| `Dockerfile` | Create | Extends hermes-agent base with Claude Code CLI |
| `.github/workflows/docker-build.yml` | Create | Multi-arch build, push to ghcr, validate manifests, auto-bump version |
| `flux/apps/hermes-jon.yaml` | Modified (by workflow) | Image tag and init container images updated automatically |
| `flux/apps/hermes-ana.yaml` | Modified (by workflow) | Image tag and init container images updated automatically |

## Notes

- Claude Code requires an `ANTHROPIC_API_KEY` environment variable at runtime. This is not baked into the image — it must be provided via Kubernetes secrets or env vars in each deployment's config.
- The `bump-version` job reads the version from the Dockerfile's `FROM` line, so any base image change automatically propagates to the K8s manifests.
- Init containers in `hermes-jon.yaml` reference `nousresearch/hermes-agent:v2026.5.29.2` explicitly. The bump job replaces these with the custom image so init containers also have Claude Code available for source copying and pip install steps.
- Workflow recursion is prevented because the bot commit uses a `[bot]` actor suffix, which GitHub does not trigger `push` events for.
