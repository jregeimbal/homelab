# Docker Image Validation CI Check

## Overview

Add a `validate-image` job to the Docker build workflow that pulls the published image from GHCR and verifies Claude Code CLI and the discord Python package are available inside the container.

## Design

### Job: validate-image

**File:** `.github/workflows/docker-build.yml`

**Trigger:** Runs only on push events (`github.event_name == 'push'`) after `build-push` succeeds. Does not run on PR dry-runs since the image is not yet published.

**Steps:**
1. Checkout repository (needed for Dockerfile reference)
2. Log in to GHCR using `${{ secrets.GITHUB_TOKEN }}`
3. Extract the version tag from the `build-push` job output
4. Pull the image from GHCR
5. Run `claude --version` inside the container
6. Run `python3 -c "import discord"` with `PYTHONPATH=/opt/data/py-global` inside the container

**Failure behavior:** Job fails, `bump-version` does not run (via `needs` dependency chain). Developer must fix the Dockerfile and re-push.

## Data Flow

```
Push to main → build-push (build + push) → validate-image (pull + verify) → bump-version
```
