# Bake GitHub CLI (gh) into Docker Container

## Problem
The Docker container (`nousresearch/hermes-agent:v2026.5.29.2`) does not include the GitHub CLI (`gh`), which is needed for interacting with GitHub from within the container.

## Solution
Add `gh` to the Docker image using GitHub's official apt repository, alongside the existing packages.

### Changes
1. Add GitHub CLI GPG key and apt repository in a new `RUN` layer
2. Add `gh` to the existing `apt-get install` package list

### Why apt?
- Uses GitHub's official repository for up-to-date versions
- Integrates with existing apt-based dependency management
- Follows the pattern already established in the Dockerfile
