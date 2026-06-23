# Hermes Home Config Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix hermes jon-agent config files (claude-settings, opencode config, zeroshot skill) so they land in the container user's actual home directory (`/opt/data/home/`) rather than `/root/`, which uid 10000 cannot use.

**Architecture:** Dockerfile COPYs are moved from `/root/` to `/opt/config-defaults/` (never masked by any volume mount). A new `bootstrap-home-config` init container in `hermes-jon.yaml` copies each file to `/opt/data/home/` on first boot (copy-only-if-missing). The existing `fix-data-ownership` init container chowns everything afterward.

**Tech Stack:** Docker, Kubernetes (Flux CD HelmRelease), shell script

## Global Constraints

- Bootstrap policy: copy-only-if-missing (`[ ! -f dest ]` guard before every copy)
- Image defaults path: `/opt/config-defaults/` (never masked by any volume mount)
- Home directory: `/opt/data/home/` (on PVC, mounted at `/opt/data`)
- Init container order: `copy-hermes-source` → `bootstrap-home-config` (new) → `fix-data-ownership`
- New init container runs as uid 0 (root), `readOnlyRootFilesystem: true`, same securityContext shape as existing init containers
- Image tag in new init container: match exactly what is in the existing init containers (`ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.6.19-14b5699`)
- `set -eu` at top of all inline shell scripts

---

### Task 1: Update Dockerfile and validate-image.sh

Moves the three config COPY destinations from `/root/` to `/opt/config-defaults/`, removes the now-redundant `mkdir/cp` from the opencode install RUN step, and updates `validate-image.sh` to verify the new paths.

**Files:**
- Modify: `Dockerfile` (lines 21–32)
- Modify: `scripts/validate-image.sh` (skill file check — update path)

**Interfaces:**
- Produces: image with files at `/opt/config-defaults/claude/settings.json`, `/opt/config-defaults/opencode/opencode.json`, `/opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md`

- [ ] **Step 1: Update validate-image.sh to check the new config-defaults paths (TDD — these fail against current image)**

The current skill file check (near the bottom of `scripts/validate-image.sh`) points at `/root/.hermes/...`. Replace the entire zeroshot skill block and add config-defaults checks for all three files. Replace the existing zeroshot skill check block with:

```bash
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
echo "=== Verifying config-defaults: zeroshot skill ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md \
  || { echo "ERROR: Missing /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md"; exit 1; }
echo "zeroshot skill present"
```

This replaces the two existing zeroshot blocks (the CLI check stays; only the skill file path check changes). After this edit the full bottom of `scripts/validate-image.sh` from the zeroshot section onward should read:

```bash
echo ""
echo "=== Verifying zeroshot CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" zeroshot --version

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
echo "=== Verifying config-defaults: zeroshot skill ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md \
  || { echo "ERROR: Missing /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md"; exit 1; }
echo "zeroshot skill present"

echo ""
echo "=== All checks passed ==="
```

- [ ] **Step 2: Update the Dockerfile**

Replace lines 21–32 of `Dockerfile`. The current block:

```dockerfile
COPY assets/opencode.json /assets/opencode.json

RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then TARGET=x64; else TARGET=arm64; fi && \
    curl -fSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${TARGET}.tar.gz" -o /tmp/opencode.tar.gz && \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin/ opencode && \
    rm /tmp/opencode.tar.gz && \
    mkdir -p /root/.config/opencode && \
    cp /assets/opencode.json /root/.config/opencode/opencode.json

COPY assets/claude-settings.json /root/.claude/settings.json
COPY assets/hermes-skills/zeroshot/SKILL.md /root/.hermes/skills/software-development/zeroshot/SKILL.md
```

Becomes:

```dockerfile
COPY assets/opencode.json /opt/config-defaults/opencode/opencode.json

RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then TARGET=x64; else TARGET=arm64; fi && \
    curl -fSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${TARGET}.tar.gz" -o /tmp/opencode.tar.gz && \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin/ opencode && \
    rm /tmp/opencode.tar.gz

COPY assets/claude-settings.json /opt/config-defaults/claude/settings.json
COPY assets/hermes-skills/zeroshot/SKILL.md /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md
```

Three changes:
1. `COPY assets/opencode.json` destination changes from `/assets/opencode.json` to `/opt/config-defaults/opencode/opencode.json`
2. The `mkdir -p /root/.config/opencode && cp /assets/opencode.json ...` lines are removed from the RUN step
3. Both other COPY destinations change from `/root/...` to `/opt/config-defaults/...`

- [ ] **Step 3: Build the image and run validate-image.sh**

```bash
./scripts/validate-image.sh
```

Expected output (abbreviated):
```
=== Building ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev ===
...
=== Verifying claude CLI ===
...
=== Verifying zeroshot CLI ===
zeroshot/...

=== Verifying config-defaults: claude settings ===
claude settings present

=== Verifying config-defaults: opencode config ===
opencode config present

=== Verifying config-defaults: zeroshot skill ===
zeroshot skill present

=== All checks passed ===
```

If any config-defaults check fails, verify the COPY path in the Dockerfile matches the check path exactly.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile scripts/validate-image.sh
git commit -m "fix: move config defaults to /opt/config-defaults for uid 10000 home"
```

---

### Task 2: Add bootstrap-home-config init container to hermes-jon.yaml

Inserts the new init container between `copy-hermes-source` and `fix-data-ownership` in `flux/apps/hermes-jon.yaml`.

**Files:**
- Modify: `flux/apps/hermes-jon.yaml` (line 202 — insert before `fix-data-ownership` block)

**Interfaces:**
- Consumes: image built in Task 1 with files at `/opt/config-defaults/`
- Produces: files at `/opt/data/home/.claude/settings.json`, `/opt/data/home/.config/opencode/opencode.json`, `/opt/data/home/.hermes/skills/software-development/zeroshot/SKILL.md` on first pod boot

- [ ] **Step 1: Insert the bootstrap-home-config init container**

In `flux/apps/hermes-jon.yaml`, the `extraInitContainers` list currently has two entries: `copy-hermes-source` (ending at line 201) then `fix-data-ownership` (starting at line 202). Insert the new init container between them so the `fix-data-ownership` entry becomes the third item.

Insert this block at line 202 (before the existing `fix-data-ownership` entry):

```yaml
      - args:
          - |
            set -eu
            if [ ! -f /opt/data/home/.claude/settings.json ]; then
              mkdir -p /opt/data/home/.claude
              cp /opt/config-defaults/claude/settings.json /opt/data/home/.claude/settings.json
            fi
            if [ ! -f /opt/data/home/.config/opencode/opencode.json ]; then
              mkdir -p /opt/data/home/.config/opencode
              cp /opt/config-defaults/opencode/opencode.json /opt/data/home/.config/opencode/opencode.json
            fi
            if [ ! -f /opt/data/home/.hermes/skills/software-development/zeroshot/SKILL.md ]; then
              mkdir -p /opt/data/home/.hermes/skills/software-development/zeroshot
              cp /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md /opt/data/home/.hermes/skills/software-development/zeroshot/SKILL.md
            fi
        command:
          - /bin/sh
          - -ec
        image: ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.6.19-14b5699
        imagePullPolicy: IfNotPresent
        name: bootstrap-home-config
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: false
          runAsUser: 0
          runAsGroup: 0
          seccompProfile:
            type: RuntimeDefault
        volumeMounts:
          - mountPath: /opt/data
            name: data
          - mountPath: /tmp
            name: tmp
```

- [ ] **Step 2: Verify the YAML is valid and init container order is correct**

```bash
python3 -c "
import yaml, pathlib
doc = yaml.safe_load(pathlib.Path('flux/apps/hermes-jon.yaml').read_text())
containers = doc['spec']['values']['extraInitContainers']
names = [c['name'] for c in containers]
print('Init container order:', names)
assert names == ['copy-hermes-source', 'bootstrap-home-config', 'fix-data-ownership'], f'Wrong order: {names}'
print('Order OK')
"
```

Expected output:
```
Init container order: ['copy-hermes-source', 'bootstrap-home-config', 'fix-data-ownership']
Order OK
```

- [ ] **Step 3: Commit**

```bash
git add flux/apps/hermes-jon.yaml
git commit -m "feat: add bootstrap-home-config init container to seed /opt/data/home on first boot"
```

---

## Post-Implementation Verification

After Flux CD rolls out the new pod, verify the bootstrap worked:

```bash
# Check files landed in the right place
kubectl exec -n jon-agent deploy/hermes -- ls -la /opt/data/home/.claude/
kubectl exec -n jon-agent deploy/hermes -- ls -la /opt/data/home/.config/opencode/
kubectl exec -n jon-agent deploy/hermes -- ls -la /opt/data/home/.hermes/skills/software-development/zeroshot/

# Confirm ownership is 10000:10000
kubectl exec -n jon-agent deploy/hermes -- stat /opt/data/home/.claude/settings.json
```

To verify copy-only-if-missing: modify a config file, restart the pod, confirm the modification survives.
