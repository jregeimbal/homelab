# Custom Hermes Agent Image with Claude Code CLI

## Overview

Build and publish a custom Docker image based on `nousresearch/hermes-agent:v2026.5.29.2` with Claude Code CLI pre-installed. The image is published to GitHub Container Registry (ghcr) and automatically referenced by both hermes agent Kubernetes deployments.

## Design Decisions

### Base Image
- **Image:** `nousresearch/hermes-agent:v2026.5.29.2`
- Pinned version matching jon's current deployment for stability

### Claude Code CLI
- Installed at Docker build time via the official installer
- No additional packages beyond Claude Code

### Publishing Target
- **Registry:** ghcr.io
- **Image name:** `jregeimbal/hermes-agent-jregeimbal-homelab`
- **Tags:** version tag (`v2026.5.29.2`), date tag (`YYYY-MM-DD`), and `latest`

### Architecture
- Multi-arch: `linux/amd64` + `linux/arm64`
- Built using Docker Buildx with QEMU emulation

## Components

### 1. Dockerfile

Located at the repository root. Single-layer install for simplicity:

```dockerfile
FROM nousresearch/hermes-agent:v2026.5.29.2

RUN curl -fsSL https://github.com/anyscale/claude-code/releases/latest/download/install.sh | sh
```

- One `RUN` instruction to minimize layers
- No architecture-specific assumptions
- Follows existing image's user/security context

### 2. GitHub Actions Workflow

**File:** `.github/workflows/docker-build.yml`

**Trigger:**
- `push` and `pull_request` events on the `main` branch, scoped to the `Dockerfile` path only
- Concurrency group to cancel in-progress builds on the same ref

**Jobs:**

**Build & Push:**
1. Checkout repository
2. Set up Docker Buildx with QEMU for multi-arch support
3. Log in to ghcr using `${{ secrets.GITHUB_TOKEN }}`
4. Build and push multi-arch image with 3 tags: version, date, `latest`

**Version Bump (depends on successful build):**
1. Parse the version tag from the workflow context
2. Update `image.tag` in both `hermes-jon.yaml` and `hermes-ana.yaml` under the HelmRelease spec
3. Commit changes back to `main` with message: `chore: bump hermes image to <version>`

### 3. Kubernetes Manifest Updates

Both deployments will have their `image.tag` field updated automatically:

- `flux/apps/hermes-jon.yaml` — currently uses `v2026.5.29.2`
- `flux/apps/hermes-ana.yaml` — currently uses `main`

After the update, Flux CD's 5-minute reconciliation interval will pick up the new image reference and roll out the updated pods.

## Data Flow

```
Dockerfile change → GitHub Actions trigger → Multi-arch build → Push to ghcr → Update K8s manifests → Flux CD rolls out
```

## Error Handling

- Build failure: workflow fails, no manifest updates occur, developer must fix and re-push
- Manifest update failure: build succeeded but commit fails — image is published but K8s still references old version. Developer must manually update manifests or re-run the workflow job
- Concurrency: `cancel-in-progress` prevents duplicate builds on rapid pushes

## Testing Strategy

- CI workflow runs on pull requests before merge (dry-run build)
- Production builds only trigger on pushes to `main`
- Flux CD validation already in existing CI (`k8s-validation` job) ensures manifest changes are valid
