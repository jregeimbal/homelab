# CI Checks Design

## Problem

The homelab repo has no automated CI checks beyond a single security review workflow. YAML manifests, JSON, and other files have no automated validation, making it easy to introduce formatting errors, invalid K8s manifests, or accidental secrets.

## Scope

CI checks for: YAML lint, K8s manifest validation, secret scanning, JSON lint. Git hooks (pre-commit) are configured alongside CI.

## Architecture

### Single GitHub Actions workflow

One workflow file at `.github/workflows/ci.yml` that runs on every PR. This keeps CI a single gate and ensures CI matches what developers run locally.

Checks run sequentially with fail-fast: if one check fails, the workflow stops. This gives clear, fast feedback.

### Pre-commit config

A `.pre-commit-config.yaml` at the repo root with the same checks. Developers run these locally before committing. CI runs the same tools directly (no pre-commit framework) to avoid framework overhead.

### Tool selection

| Check | Tool | Rationale |
|-------|------|-----------|
| YAML lint | `yamllint` | Lightweight, well-configurable, standard for YAML validation |
| K8s manifest validation | `kubeconform` | Validates against K8s API schemas, catches structural errors |
| Secret scanning | `gitleaks` | Detects secrets in tracked files, configurable rules |
| JSON lint | `check-json` | Validates JSON syntax in Grafana dashboards and other JSON files |

## File structure

```
.github/workflows/ci.yml          # GitHub Actions workflow
.pre-commit-config.yaml           # Pre-commit hooks config
.pre-commit-hooks.yaml            # Custom hook definitions
```

## CI workflow design

The workflow runs on `pull_request` and `push` to `main`.

### Steps

1. **Checkout** with fetch-depth 2 for efficient diffs
2. **YAML lint** - Run `yamllint` on all `.yaml` and `.yml` files, excluding `.pre-commit-config.yaml` and `.pre-commit-hooks.yaml` from strict rules
3. **K8s manifest validation** - Run `kubeconform` on all files under `flux/`
4. **Secret scanning** - Run `gitleaks` on all tracked files, excluding `secrets/encrypted/`, `venv/`, and `images/`
5. **JSON lint** - Run `check-json` on `assets/grafana-dashboards/`

## Pre-commit hooks design

Hooks mirror CI checks but use pre-commit's framework:

- `yamllint` on `**/*.yaml`, `**/*.yml`
- Custom `kubeconform` hook on `flux/**/*.yaml`
- `gitleaks` on all files with same exclusions
- `check-json` on `assets/**/*.json`

## Error handling

- Each check exits non-zero on failure, stopping the workflow
- `yamllint` uses a permissive default config that catches real issues without nitpicking
- `kubeconform` skips validation for files that reference external resources (e.g., sealed secrets CRDs)
- `gitleaks` excludes known false-positive paths

## Testing

Local testing via `pre-commit run --all-files` before committing. CI provides the same validation on PRs.
