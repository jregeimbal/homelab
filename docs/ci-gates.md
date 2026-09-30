# Pre-Merge CI Gates (Hermes Image Bumps)

Two checks gate any PR or push touching `Dockerfile`, `requirements.txt`, or `assets/**` (the only paths that trigger the Docker Build workflow). They exist because a base-image bump can silently change runtime behavior (e.g. the 0.21.5 dashboard auth gate that crash-looped the desktop container).

## What the gates do

### Contract Tests (manifest replay)
Runs after the image build. For each agent manifest (`flux/apps/hermes-jon.yaml`, `hermes-ana.yaml`, `hermes-wander.yaml`): extracts the HelmRelease `values`, `helm template`s them against the pinned upstream chart commit (resolved dynamically from `flux/cluster/helmrepositories.yaml`), then replays every rendered container in Docker against the freshly built image — init containers in order (must exit 0), service containers for a 45 s survival window with port probes. Secrets are replaced with dummy values (`ci-dummy-<NAME>`); PVCs become fresh empty directories (fresh-PVC worst case); configMaps are rendered from the chart. Foreign images (e.g. browserless) are skipped, not run. Also asserts `hermes --version` in our image equals the upstream base image's.

### Upstream Changelog Diff
Fully parallel, no dependencies. Compares the Dockerfile's current base tag (`FROM ...`) against the oldest base tag across the three manifests via the GitHub compare API, and always posts a PR comment with the commit list. Fails the check only when a breaking marker (`BREAKING`, `removed`, `no longer`, `requires` — case-insensitive) appears in a commit message or in the patch of a `*changelog*`-named file.

## Triage

### Contract-test failure
1. Download the `contract-test-logs` artifact from the failed run.
2. Find the `FAIL <manifest>/<container>` line; open the matching log file (same name, `.log`).
3. Judge the cause:
   - Traceback / missing module / unrecognized argument → **upstream behavior change** (or an image-build bug). The changelog comment usually names the commits.
   - Config-driven failure (auth gates, volume layout) → **our config**; fix the manifest and re-run.
   - A container that exited because channel connections fail on `ci-dummy-*` credentials is **passed by design** (the classifier only fails on contract-failure signatures) — don't chase those.
4. If you're confident it's a false positive you can override the merge (admin) — read the log tail first.

### Changelog-gate failure
Read the posted PR comment. Judge each quoted breaking line:
- True positive → adapt the manifests/config to the new behavior (the point of the gate), or hold the base bump.
- False positive (e.g. "removed" describing an *old* version in the changelog) → override with `/merge` authority. There is deliberately no allowlist; the marker scan is dumb on purpose (fail = human review).

## Updating the pins

- **Chart pin:** edit the `spec.ref.commit` of the `hermes-agent` GitRepository in `flux/cluster/helmrepositories.yaml`. The gates resolve it dynamically; nothing is hardcoded.
- **Base image tag:** edit the `FROM nousresearch/hermes-agent:<tag>` line in `Dockerfile`. After a push to main, the workflow's `bump-version` job updates all three manifests' image tags automatically; the changelog gate diffs the old manifest tags against the new `FROM` tag.

## Housekeeping

- **GHCR tag accumulation:** every build (push, PR, or manual dispatch) publishes the content-addressed `:sha-<sha7>` tag so the gates can pull it; `version-sha`, date, and `latest` tags are push-to-main only. Sha tags accumulate and are never GC'd. To list/delete:

  ```bash
  # list container package ids (token needs read:packages)
  curl -s -H "Authorization: Bearer $TOKEN" \
    "https://api.github.com/user/packages?package_type=container&package_owner=jregeimbal&per_page=100" \
    | jq -r '.[] | "\(.id) \(.name)"'
  # list versions of one package, then delete
  curl -s -H "Authorization: Bearer $TOKEN" \
    "https://api.github.com/packages/container/<package-id>/versions?per_page=100" \
    | jq -r '.[] | "\(.id) \(.tags | join(","))"'
  curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
    "https://api.github.com/packages/container/<package-id>/versions/<version-id>"
  ```
- **PR comments:** the changelog job posts one comment per PR event (a re-sync posts a fresh comment — no dedup). PRs that don't change the base get a "No upstream base change" comment.
- **Known limitation:** the GitHub compare API truncates at 250 commits / 300 files, and upstream moves fast (~5,000 commits in one week, 2026-09-14 → 09-21), so in practice **most bumps are only partially scanned** (possible false negative). The comment flags this with a ⚠️ "only N of M commits" line; when you see it, skim the upstream release notes yourself.
- **Manual dispatch:** `workflow_dispatch` runs the full pipeline including both gates (all builds push their sha tag).
- **Fork PRs:** if you ever accept fork PRs, the build push fails at registry login (fork tokens can't write your packages), so the gates can't run for forks.

## Branch protection

Both checks must be **required** on `main`: Settings → Branches → branch protection rule → *Require status checks to pass before merging* → search for **"Contract Tests"** and **"Upstream Changelog"** (check "Require branches to be up to date" if you like). Until then the gates run and report, but don't block merges.
