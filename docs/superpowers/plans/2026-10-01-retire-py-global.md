# Retire `/opt/data/py-global` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop every hermes agent from importing Python packages out of the per-agent `/opt/data/py-global` PVC directory, so the image's sealed venv is the only source of core packages and hermes's own lazy-install target handles optional extras.

**Architecture:** Hermes upstream already ships the right mechanism: a sealed venv (`HERMES_DISABLE_LAZY_INSTALLS=1`) plus a durable lazy-install target (`HERMES_LAZY_INSTALL_TARGET=/opt/data/lazy-packages`) that is *appended* to `sys.path`, so the venv wins every collision. Our `PYTHONPATH=/opt/data/py-global` *prepends* a hand-grown directory that overrides the venv. We canary the removal per agent with a reversible directory rename (no deploy needed), then delete the py-global layer from the image, manifests, and CI, and finally delete the retired directories after a soak.

**Tech Stack:** Dockerfile, Flux HelmRelease manifests, GitHub Actions, kubectl, hermes `tools/lazy_deps.py`.

## Global Constraints

- Agents and namespaces: Jon = `jon-agent` (HelmRelease `hermes`), Ana = `ana-agent` (`hermes-ana`), Wander = `wander-agent` (`hermes-wander`). Main container name: `hermes-agent`.
- Venv interpreter: `/opt/hermes/.venv/bin/python`. Run in-pod Python from `cd /tmp` (cwd must not shadow anything).
- Never delete PVC data in Tasks 1–4. Retire by renaming to `/opt/data/py-global.retired-20261001`; deletion happens only in Task 5, after a soak of at least 3 days.
- Lazy features to warm per agent (from each agent's `config.yaml` + env): all three need `stt.faster_whisper` (`stt.enabled: true`, no Groq/OpenAI STT key → local whisper); Jon and Wander need `search.firecrawl` (`web.backend: firecrawl`). Discord (`discord.py 2.7.1`) and Telegram (`python-telegram-bot 22.8`) are already in the venv.
- `main` is protected by the `main` ruleset: Contract Tests + Upstream Changelog Diff are required checks. Repo changes go through a PR.
- Do not remove apt packages (`gcc`, `libffi-dev`, `python3-pip`) from the Dockerfile in this plan; agents may build wheels at runtime. Out of scope.

## Inventory (2026-10-01, read-only, agents on `v2026.9.24-34e64f8`)

| | Jon | Ana | Wander |
|---|---|---|---|
| `/opt/data/py-global` | 604 MB, 114 dists | 373 MB, 42 dists | absent |
| dists that shadow a venv dist | 93 (35 at a different version) | 27 (13 different) | 0 |
| duplicate dist-infos (old versions left by repeated `pip --target`) | 18 (e.g. `huggingface-hub` ×5, `tqdm` ×4, `filelock` ×4) | 12 | 0 |
| major-version overrides of the venv | `protobuf` 7.35 vs 6.33.5, `mcp` 1.26 vs 2.0.0, `cryptography` 48 vs 50, `websockets` 16 vs 15, `rich` 15 vs 14, `attrs`, `pytz`, `rpds-py` | `protobuf` 7.35 vs 6.33.5, `rich` 15 vs 14, `attrs` | — |
| downgrades of the venv | `starlette` 1.0.1 < 1.3.1, `mcp`, `cryptography`, `google-auth`, `pyjwt`, `aiohttp`, `python-telegram-bot` 22.7 < 22.8, … | `aiohttp`, `click` | — |
| `/opt/data/lazy-packages` (hermes-managed) | 14 MB (`edge_tts` + deps) | 14 MB (`edge_tts` + deps) | 348 MB (`edge_tts`, `faster_whisper` + deps) |
| other | `py-global-stale-hermes-20260928.tar` (45 MB, 2026-09-28 incident backup) | — | — |

Findings:

1. **The image's own py-global is never used.** The pod mounts the `/opt/data` PVC over the image's `/opt/data`, hiding the 378 MB / 45 dists the Dockerfile installs there. Production imports whatever accumulated on each PVC.
2. **Every `requirements.txt` entry is already covered upstream.** `discord.py`, `python-telegram-bot`, `python-dotenv` (1.2.2) are in the venv; `faster-whisper` and `firecrawl-py` (`==4.17.0`, same pin) are in hermes's `LAZY_DEPS` allowlist (`stt.faster_whisper`, `search.firecrawl`).
3. **Jon's unexplained root dists are leftovers, not agent installs.** `croniter`, `fastapi`, `fire`, `openai`, `prompt-toolkit`, `psutil`, `simple-term-menu`, … are hermes-agent's own dependencies from the old `hermes-agent[all]` install; they became roots when that dist was removed on 2026-09-28. All but `simple-term-menu`, `sounddevice` and `pip` are in the venv at the same version; `sounddevice` is part of `stt.faster_whisper`; the other two are unused. No install date is later than 2026-07-04.
4. **Skills mention `pip install` but don't depend on py-global.** Ana's skills (and presumably Jon's; the scan timed out on Jon's large PVC) contain `pip install X` hints for optional skill deps; none reference `/opt/data/py-global`.
5. **py-global already breaks hermes's own lazy installer.** On Ana, `lazy_deps.ensure("stt.faster_whisper")` fails today: `numpy==2.4.3` (hermes pin) vs `numpy 2.5.0` (py-global) is unsatisfiable. Ana's voice works only because py-global carries its own `faster_whisper`. Once py-global is off `sys.path`, the pin resolves.
6. **The CI gates can't see this class of bug.** Contract tests mount a fresh empty PVC, so py-global is empty there; they only exercise the image.

Rollback for Tasks 1–2 (per agent): `mv /opt/data/py-global.retired-20261001 /opt/data/py-global` in the pod, then `kubectl rollout restart deployment -n <ns>`. Rollback for Task 3: revert the PR; PYTHONPATH returns and still points at the (renamed, hence absent) directory until Task 1/2's rename is reversed.

---

### Task 1: Canary on Ana (rename, restart, verify)

Ana has the smallest py-global and no Firecrawl, so it is the lowest-risk canary. No repo change: with the directory renamed, `PYTHONPATH` points at a missing path, which Python ignores, so Ana runs exactly the target configuration.

**Files:** none (cluster-only).

**Interfaces:**
- Produces: the verification script `/private/tmp/.../scratchpad/verify-agent.sh` reused verbatim by Tasks 2 and 4.

- [ ] **Step 1: Write the per-agent verification script**

Save as `scratchpad/verify-agent.sh` (scratchpad = the session scratchpad directory; not committed):

```bash
#!/usr/bin/env bash
# usage: verify-agent.sh <namespace> <lazy-feature>...   e.g. verify-agent.sh ana-agent stt.faster_whisper
set -uo pipefail
NS=$1; shift
P=$(kubectl get pods -n "$NS" -l app.kubernetes.io/name=hermes-agent -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$P" ] || P=$(kubectl get pods -n "$NS" -o jsonpath='{.items[0].metadata.name}')
echo "== $NS/$P"
kubectl get pod -n "$NS" "$P" -o jsonpath='{range .status.containerStatuses[*]}{.name} ready={.ready} restarts={.restartCount}{"\n"}{end}'
[ $# -gt 0 ] || { echo "usage: $0 <namespace> <lazy-feature>..."; exit 2; }
# sh -c's first trailing arg becomes $0, so pass a dummy "sh" before the features.
kubectl exec -i -n "$NS" "$P" -c hermes-agent -- sh -c 'cd /tmp && /opt/hermes/.venv/bin/python - "$@"' sh "$@" <<'EOF'
import importlib, os, sys
print("py-global present:", os.path.isdir("/opt/data/py-global"))
leaks = [p for p in sys.path if "py-global" in p and os.path.isdir(p)]
print("py-global on sys.path:", leaks or "no")
for mod in ["discord", "telegram", "dotenv", "google.protobuf", "starlette", "websockets", "mcp"]:
    try:
        f = importlib.import_module(mod).__file__ or ""
        print("  %-16s %s" % (mod, "py-global!" if "py-global" in f else ("venv" if "/opt/hermes/.venv" in f else f)))
    except Exception as e:
        print("  %-16s MISSING (%s)" % (mod, type(e).__name__))
sys.path.insert(0, "/opt/hermes")
from tools import lazy_deps
lazy_deps.activate_durable_lazy_target()
bad = 0
for feat in sys.argv[1:]:
    try:
        lazy_deps.ensure(feat)
        print("  lazy %-22s OK" % feat)
    except Exception as e:
        bad += 1
        print("  lazy %-22s FAIL %s: %s" % (feat, type(e).__name__, e))
sys.exit(1 if bad or leaks else 0)
EOF
rc=$?
echo "-- hermes version:"; kubectl exec -n "$NS" "$P" -c hermes-agent -- hermes --version 2>&1 | head -1
echo "-- gateway log tail (connect/errors):"
kubectl logs -n "$NS" "$P" -c hermes-agent --since=10m 2>&1 | grep -iE "connected|ready|logged in|error|traceback|exception" | tail -15
exit $rc
```

Note: `python -` reads the script from stdin, and the features after the dummy `sh` become `sys.argv[1:]`. Each requested feature must print a `lazy <feature> OK` line; a run with no `lazy` lines means the arguments were lost.

- [ ] **Step 2: Record Ana's baseline**

Run: `bash verify-agent.sh ana-agent stt.faster_whisper`
Expected (observed 2026-10-01): `py-global present: True`, `py-global on sys.path: ['/opt/data/py-global']`, `discord py-global!`, `google.protobuf py-global!`, `lazy stt.faster_whisper FAIL … numpy==2.4.3 and numpy==2.5.0 … unsatisfiable`, exit code 1. This proves the script detects the problem; the failed resolve installs nothing.

- [ ] **Step 3: Rename Ana's py-global**

```bash
P=$(kubectl get pods -n ana-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n ana-agent "$P" -c hermes-agent -- mv /opt/data/py-global /opt/data/py-global.retired-20261001
kubectl exec -n ana-agent "$P" -c hermes-agent -- ls -d /opt/data/py-global.retired-20261001
```

Expected: the `ls` prints the retired path.

- [ ] **Step 4: Restart Ana and wait for Ready**

```bash
kubectl rollout restart deployment -n ana-agent
kubectl rollout status deployment -n ana-agent --timeout=10m
```

Expected: `successfully rolled out`.

- [ ] **Step 5: Verify Ana in the target state**

Run: `bash verify-agent.sh ana-agent stt.faster_whisper`
Expected: `py-global present: False`, `py-global on sys.path: no`, every module `venv`, `lazy stt.faster_whisper OK` (first run downloads ~330 MB into `/opt/data/lazy-packages`; allow several minutes), `hermes --version` reports `v0.21.5`, all containers `ready=true restarts=0`, no `Traceback` in the log tail, exit code 0.

- [ ] **Step 6: Functional check (user)**

Ask the user to send Ana a text message and a short voice note on its usual channel and confirm both get a sensible reply. Do not proceed to Task 2 until confirmed. If either fails: run the Task 1 rollback, capture `kubectl logs -n ana-agent <pod> -c hermes-agent --since=15m`, and stop.

---

### Task 2: Jon (rename, restart, verify)

Jon has the largest py-global plus Discord, Telegram and Firecrawl.

**Files:** none (cluster-only).

**Interfaces:**
- Consumes: `verify-agent.sh` from Task 1, unchanged.

- [ ] **Step 1: Record Jon's baseline**

Run: `bash verify-agent.sh jon-agent stt.faster_whisper search.firecrawl`
Expected: `py-global on sys.path: ['/opt/data/py-global']`, several `py-global!` modules, exit code 1.

- [ ] **Step 2: Rename Jon's py-global**

```bash
P=$(kubectl get pods -n jon-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n jon-agent "$P" -c hermes-agent -- mv /opt/data/py-global /opt/data/py-global.retired-20261001
kubectl exec -n jon-agent "$P" -c hermes-agent -- ls -d /opt/data/py-global.retired-20261001
```

- [ ] **Step 3: Restart Jon and wait for Ready**

```bash
kubectl rollout restart deployment -n jon-agent
kubectl rollout status deployment -n jon-agent --timeout=15m
```

- [ ] **Step 4: Verify Jon in the target state**

Run: `bash verify-agent.sh jon-agent stt.faster_whisper search.firecrawl`
Expected: as in Task 1 Step 5, plus `lazy search.firecrawl OK`; log tail shows Discord and Telegram connecting with no `Traceback`; exit code 0.

- [ ] **Step 5: Functional check (user)**

Ask the user to: message Jon on Discord and on Telegram, send a voice note, and ask Jon to fetch a web page (exercises Firecrawl), and the dashboard/desktop still loads. Do not proceed until confirmed. On failure: Task 2 rollback, capture logs, stop.

---

### Task 3: Remove the py-global layer from the repo (PR)

**Files:**
- Modify: `Dockerfile` (delete `ENV PYTHONPATH=/opt/data/py-global` and the `COPY requirements.txt` / `pip install --target` block)
- Delete: `requirements.txt`
- Modify: `flux/apps/hermes-jon.yaml`, `flux/apps/hermes-ana.yaml`, `flux/apps/hermes-wander.yaml` (delete the `PYTHONPATH: /opt/data/py-global` line)
- Modify: `.github/workflows/docker-build.yml` (push paths, `changes` pattern, `Verify discord package` step, new regression step in `contract-tests`)
- Modify: `docs/apps.md:24`, `docs/ci-gates.md:3`

**Interfaces:**
- Produces: CI step `Assert no py-global layer` in the `contract-tests` job, which later tasks rely on to keep this from coming back.

- [ ] **Step 1: Write the regression check (the failing test)**

In `.github/workflows/docker-build.yml`, in the `contract-tests` job, insert this step immediately before `- name: Run contract tests`:

```yaml
      - name: Assert no py-global layer
        # 2026-09-28 incident + 2026-10-01 inventory: a PYTHONPATH dir on the
        # PVC shadowed the sealed venv. Optional deps belong in hermes's
        # lazy-install target (appended to sys.path), never ahead of the venv.
        run: |
          docker run --rm --entrypoint sh "${{ steps.img.outputs.ref }}" -c '
            set -e
            [ -z "${PYTHONPATH:-}" ] || { echo "image sets PYTHONPATH=$PYTHONPATH"; exit 1; }
            [ ! -e /opt/data/py-global ] || { echo "image ships /opt/data/py-global"; exit 1; }
            echo "ok: no PYTHONPATH, no /opt/data/py-global"'
          if grep -n 'PYTHONPATH' flux/apps/hermes-*.yaml; then
            echo "manifests still set PYTHONPATH"; exit 1
          fi
```

- [ ] **Step 2: Run the check against the current image to verify it fails**

```bash
IMG=ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.9.24-34e64f8
docker run --rm --entrypoint sh "$IMG" -c '[ -z "${PYTHONPATH:-}" ] || { echo "image sets PYTHONPATH=$PYTHONPATH"; exit 1; }'; echo "rc=$?"
grep -n 'PYTHONPATH' flux/apps/hermes-*.yaml
```

Expected: `image sets PYTHONPATH=/opt/data/py-global`, `rc=1`, and three manifest matches.

- [ ] **Step 3: Remove the layer**

Dockerfile: delete line 4 (`ENV PYTHONPATH=/opt/data/py-global`) and its following blank line, and delete:

```dockerfile
COPY requirements.txt .
RUN mkdir -p /opt/data/py-global && \
    pip install --no-cache-dir -r requirements.txt --target /opt/data/py-global && \
    rm requirements.txt
```

Then:

```bash
git rm requirements.txt
sed -i '' '/^      PYTHONPATH: \/opt\/data\/py-global$/d' flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml flux/apps/hermes-wander.yaml
```

In `.github/workflows/docker-build.yml`:
- `on.push.paths`: delete `      - requirements.txt`.
- `changes` job `PATTERN`: replace `^(Dockerfile|requirements\.txt|assets/|` with `^(Dockerfile|assets/|`.
- `validate-image` → `Verify discord package`: delete the `-e PYTHONPATH=/opt/data/py-global \` line and change `python3 -c` to `/opt/hermes/.venv/bin/python -c` (discord.py now comes from the venv).

`docs/apps.md:24`: replace the bullet with `   - Optional Python extras (faster-whisper, firecrawl, …) are installed on demand by hermes into \`/opt/data/lazy-packages\` (appended to \`sys.path\`; the venv always wins)`.
`docs/ci-gates.md:3`: replace `` (`Dockerfile`, `requirements.txt`, `assets/**`) `` with `` (`Dockerfile`, `assets/**`) ``.

- [ ] **Step 4: Verify locally**

```bash
grep -rn -E 'py-global|requirements\.txt|PYTHONPATH' --exclude-dir=.git --exclude-dir=superpowers --exclude-dir=fixtures . 
yamllint -c .yamllint $(git ls-files '*.yaml' '*.yml' | grep -vE '(pre-commit-config\.yaml$|secrets/)')
python3 -m pytest -q tests
```

Expected: the grep prints only the new `Assert no py-global layer` step lines; yamllint exits 0; pytest `28 passed, 1 skipped` (fixtures under `tests/fixtures/` are static render snapshots and are intentionally left unchanged).

- [ ] **Step 5: Commit, push, open PR, verify green**

```bash
git add -A Dockerfile flux/apps .github/workflows/docker-build.yml docs/apps.md docs/ci-gates.md
git commit -m "fix: retire /opt/data/py-global; rely on sealed venv + hermes lazy installs"
git push -u origin retire-py-global
gh pr create --base main --head retire-py-global --title "fix: retire /opt/data/py-global" --body-file docs/superpowers/plans/2026-10-01-retire-py-global.md
```

Expected on the PR: `Assert no py-global layer` passes, Contract Tests PASS for all 15 containers (3 browserless SKIPs), Upstream Changelog Diff posts "No upstream base change". Contract tests already run with an empty PVC, so they test exactly the post-change runtime.

---

### Task 4: Merge and verify the rollout

**Files:** none.

**Interfaces:**
- Consumes: `verify-agent.sh` from Task 1, unchanged.

- [ ] **Step 1: User merges the PR**

- [ ] **Step 2: Watch the main pipeline**

```bash
ID=$(gh run list --branch main --workflow docker-build.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$ID" --exit-status
```

Expected: all jobs succeed; `Bump Image Version` starts after `Contract Tests` completes; a `homelab-bump-image-ci[bot]` commit lands on main.

- [ ] **Step 3: Reconcile and wait for all three agents**

```bash
flux reconcile kustomization apps -n flux-system
for ns in jon-agent ana-agent wander-agent; do kubectl rollout status deployment -n $ns --timeout=15m; done
```

- [ ] **Step 4: Verify all three**

```bash
bash verify-agent.sh ana-agent stt.faster_whisper
bash verify-agent.sh jon-agent stt.faster_whisper search.firecrawl
bash verify-agent.sh wander-agent stt.faster_whisper search.firecrawl
for ns in jon-agent ana-agent wander-agent; do kubectl exec -n $ns deploy/$(kubectl get deploy -n $ns -o jsonpath='{.items[0].metadata.name}') -c hermes-agent -- printenv PYTHONPATH; echo "$ns PYTHONPATH rc=$? (1 = unset, expected)"; done
```

Expected: all three exit 0; `PYTHONPATH` unset in every pod; Wander now also has Firecrawl available.

- [ ] **Step 5: Functional check (user)**

Ask the user to message each agent once (Wander via WhatsApp) and confirm replies.

---

### Task 5: Soak, then delete retired data (no earlier than 2026-10-04)

**Files:** none (cluster-only). This is irreversible; get explicit user confirmation first. After this task, reverting the Task 3 PR is no longer a full rollback: the retired directories are gone, so a reverted `PYTHONPATH` would point at an empty path.

- [ ] **Step 1: Confirm no regressions during the soak**

```bash
for ns in jon-agent ana-agent wander-agent; do kubectl get pods -n $ns -o jsonpath='{range .items[*]}{.metadata.name} restarts={.status.containerStatuses[*].restartCount}{"\n"}{end}'; done
```

Expected: no restarts attributable to import errors.

Then confirm nothing recreated py-global during the soak:

```bash
for ns in jon-agent ana-agent wander-agent; do P=$(kubectl get pods -n $ns -o jsonpath='{.items[0].metadata.name}'); kubectl exec -n $ns "$P" -c hermes-agent -- sh -c 'ls -d /opt/data/py-global 2>/dev/null && echo "RECREATED in '"$ns"'" || echo "'"$ns"': absent (ok)"'; done
```

Expected: all three `absent (ok)` (the scan for skills' `pip install` hints timed out on Jon's PVC in the inventory, so confirm nothing rebuilt the directory).

Ask the user to confirm all three agents behaved normally since Task 4.

- [ ] **Step 2: Delete (after explicit user OK)**

```bash
P=$(kubectl get pods -n jon-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n jon-agent "$P" -c hermes-agent -- rm -rf /opt/data/py-global.retired-20261001 /opt/data/py-global-stale-hermes-20260928.tar
P=$(kubectl get pods -n ana-agent -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n ana-agent "$P" -c hermes-agent -- rm -rf /opt/data/py-global.retired-20261001
for ns in jon-agent ana-agent; do P=$(kubectl get pods -n $ns -o jsonpath='{.items[0].metadata.name}'); kubectl exec -n $ns "$P" -c hermes-agent -- sh -c 'ls -d /opt/data/py-global* 2>/dev/null; df -h /opt/data | tail -1'; done
```

Expected: no `py-global*` paths listed; ~1 GB freed across the two PVCs.
