# Hermes Home Config Bootstrap

## Overview

The hermes jon-agent container runs as uid 10000 whose home directory is `/opt/data/home` (on the PVC). Config files currently `COPY`'d to `/root/` in the Dockerfile are never visible to the running process because uid 10000's home resolves to `/opt/data/home`, and files in the image layer at `/opt/data/` are masked at runtime by the PVC volume mount.

This design fixes that by baking default config files into the image at `/opt/config-defaults/` (never masked) and adding a new init container that copies them to `/opt/data/home/` on first boot.

## Design Decisions

### Bootstrap policy: copy only if missing

Config files are only written if the destination does not already exist. This preserves user customizations across pod restarts and image upgrades.

### Default file location in image: `/opt/config-defaults/`

This path is never shadowed by any volume mount (PVC is at `/opt/data/`, emptyDir volumes are at `/run/`, `/opt/hermes/`, and `/tmp`). Files here are always readable from the image layer at runtime.

### Mechanism: new init container

A new `bootstrap-home-config` init container runs between the existing `copy-hermes-source` and `fix-data-ownership` init containers. Running second means it can write files; running before `fix-data-ownership` means newly created files and directories are chowned to 10000:10000 automatically.

### Alternatives considered

- **Extend fix-data-ownership**: mixes concerns in one script; less readable
- **Entrypoint wrapper**: requires knowing and wrapping the upstream hermes entrypoint; fragile to upstream changes

## Architecture

Two files change:

```
homelab/
├── Dockerfile                     ← move COPY destinations to /opt/config-defaults/
└── flux/apps/hermes-jon.yaml      ← add bootstrap-home-config init container
```

Init container execution order (sequential):
1. `copy-hermes-source` — existing
2. `bootstrap-home-config` — **new**: seeds `/opt/data/home/` with defaults
3. `fix-data-ownership` — existing: chowns all of `/opt/data` to 10000:10000

## Components

### 1. Dockerfile Changes

Remove direct writes to `/root/` and replace with COPY to `/opt/config-defaults/`:

```dockerfile
# Before (broken — masked by PVC at runtime):
COPY assets/claude-settings.json /root/.claude/settings.json
# Inside opencode RUN step: mkdir -p /root/.config/opencode && cp /assets/opencode.json /root/.config/opencode/opencode.json
COPY assets/hermes-skills/zeroshot/SKILL.md /root/.hermes/skills/software-development/zeroshot/SKILL.md

# After (correct — /opt/config-defaults/ is never masked):
COPY assets/claude-settings.json /opt/config-defaults/claude/settings.json
COPY assets/opencode.json /opt/config-defaults/opencode/opencode.json
COPY assets/hermes-skills/zeroshot/SKILL.md /opt/config-defaults/hermes-skills/software-development/zeroshot/SKILL.md
```

The `mkdir -p /root/.config/opencode && cp` lines inside the opencode install `RUN` step are removed.

### 2. New Init Container (`flux/apps/hermes-jon.yaml`)

Inserted as the second entry in `extraInitContainers`, after `copy-hermes-source` and before `fix-data-ownership`:

```yaml
- name: bootstrap-home-config
  image: ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.6.19-34c59c3
  imagePullPolicy: IfNotPresent
  command:
    - /bin/sh
    - -ec
  args:
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

Runs as root (uid 0) so it can create directories and write files on the PVC — same pattern as the existing `copy-hermes-source` and `fix-data-ownership` init containers. The image tag is auto-bumped by CI alongside all other init container references.

## Data Flow

```
Image build:
  COPY assets/claude-settings.json     → /opt/config-defaults/claude/settings.json
  COPY assets/opencode.json            → /opt/config-defaults/opencode/opencode.json
  COPY assets/.../zeroshot/SKILL.md   → /opt/config-defaults/hermes-skills/.../SKILL.md

Pod startup:
  [copy-hermes-source] copies /opt/hermes/ → emptyDir
  [bootstrap-home-config] (first boot only):
    /opt/config-defaults/claude/settings.json        → /opt/data/home/.claude/settings.json
    /opt/config-defaults/opencode/opencode.json      → /opt/data/home/.config/opencode/opencode.json
    /opt/config-defaults/hermes-skills/.../SKILL.md → /opt/data/home/.hermes/skills/.../SKILL.md
  [fix-data-ownership] chowns /opt/data → 10000:10000

Main container runs as uid 10000:
  HOME=/opt/data/home
  ~/.claude/settings.json        ✓ readable
  ~/.config/opencode/opencode.json ✓ readable
  ~/.hermes/skills/.../SKILL.md  ✓ readable
```

## Error Handling

- If `/opt/config-defaults/` is missing a file (e.g., image was built without the COPY), `cp` exits non-zero and `set -eu` aborts the init container — pod fails to start with a clear error in init container logs
- If the destination directory already exists with the file present, the `[ ! -f ]` guard skips the copy silently
- `fix-data-ownership` runs after this container unconditionally, so any newly created files are always owned by 10000:10000 before the main container starts

## Testing Strategy

- `validate-image.sh`: add checks that `/opt/config-defaults/` files exist in the built image
- Manual: delete one of the destination files from the PVC, restart the pod, confirm the file is restored
- Manual: modify a config file on the PVC, restart the pod, confirm the modification is preserved (copy-only-if-missing behavior)
