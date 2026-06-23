# Zeroshot Hermes Jon-Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install `@the-open-engine/zeroshot` into the hermes jon-agent Docker image and bake in a Hermes skill that guides the agent to invoke `zeroshot run <issue> --pr --provider opencode` when asked to autonomously implement a GitHub issue.

**Architecture:** Three files change — `Dockerfile` gets the npm install and COPY directive, `assets/hermes-skills/zeroshot/SKILL.md` is the new hermes skill, and `scripts/validate-image.sh` gets zeroshot/skill-path checks. The existing GHA workflow rebuilds and pushes the image on merge; Flux CD rolls it out automatically.

**Tech Stack:** Docker, npm (`@the-open-engine/zeroshot`), Hermes Agent skill format (SKILL.md frontmatter)

## Global Constraints

- Base image: `nousresearch/hermes-agent:v2026.6.19` (do not change)
- All skill content must conform to Hermes SKILL.md frontmatter: `name`, `description` ≤ 1024 chars, body after closing `---`, total file ≤ 100,000 chars
- `readOnlyRootFilesystem: true` in k8s — all skill files must be baked into image layers, not written at runtime
- Skill provider flag must be `--provider opencode` (explicit, not relying on global default)
- Skill isolation flag must be `--pr`
- Repo clone target: `/opt/data/<repo-name>`
- `zeroshot --version` must succeed in Dockerfile RUN step (build-time verification)

---

### Task 1: Create the SKILL.md asset

**Files:**
- Create: `assets/hermes-skills/zeroshot/SKILL.md`

**Interfaces:**
- Produces: skill file content that Task 2 copies into the image

- [ ] **Step 1: Create the directory and write the skill file**

```bash
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/homelab/assets/hermes-skills/zeroshot
```

Write `assets/hermes-skills/zeroshot/SKILL.md` with this exact content:

```markdown
---
name: zeroshot
description: Use when the user asks to implement a GitHub issue using zeroshot, run a multi-agent coding workflow, or autonomously implement and verify a code change with a resulting PR. Invokes zeroshot run with --pr and --provider opencode.
version: 1.0.0
author: Jon Regeimbal
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [zeroshot, multi-agent, github, pr, implementation, coding-agent, autonomous]
    related_skills: [plan, requesting-code-review]
---

# Zeroshot Multi-Agent Implementation

## Overview

Zeroshot orchestrates planner → implementer → validators in an isolated git worktree, looping until the change is verified or rejected with reproducible failures. Use it when the user wants autonomous multi-agent implementation of a GitHub issue with a resulting PR, rather than manual coding steps.

## When to Use

- User says "use zeroshot to implement issue #N"
- User asks for autonomous or multi-agent implementation of a GitHub issue
- User wants a verified PR produced from an issue description

Don't use for:
- Simple one-shot edits (use the terminal directly)
- Tasks without a GitHub issue number, markdown file, or clear inline description

## Steps

1. **Confirm the target repo.** If the user has not specified a `owner/repo`, ask for it before proceeding.

2. **Navigate to the repo.** If already cloned under `/opt/data/<repo>`, enter it and update the default branch:
   ```bash
   cd /opt/data/<repo> && git pull --rebase origin $(git symbolic-ref --short HEAD)
   ```
   If not present, clone it first:
   ```bash
   cd /opt/data && gh repo clone <owner>/<repo> && cd <repo>
   ```

3. **Run zeroshot** from the repo root:
   ```bash
   zeroshot run <issue_number> --pr --provider opencode
   ```
   For a markdown file:
   ```bash
   zeroshot run path/to/spec.md --pr --provider opencode
   ```
   For inline text:
   ```bash
   zeroshot run "description of task" --pr --provider opencode
   ```

4. **Report the outcome.**
   - `VERIFIED` — PR was opened. Report the PR URL to the user.
   - `REJECTED` — zeroshot exhausted retries. Report the failure summary and ask whether to resume or adjust the task.
   - On interruption, resume with the cluster ID shown in the output header:
     ```bash
     zeroshot resume <cluster-id> --provider opencode
     ```

## Common Pitfalls

1. **Not in the repo root.** Zeroshot creates worktrees relative to the current directory. Always `cd` into the repo before running.
2. **GitHub auth missing.** Run `gh auth status` first. The container has `gh` configured via `GH_CONFIG_DIR`; if it fails, report to the user rather than proceeding.
3. **Missing remote.** Zeroshot resolves issue numbers from the repo's `origin` remote. Ensure the cloned repo has a GitHub `origin`.

## Verification Checklist

- [ ] `owner/repo` confirmed with the user
- [ ] Repo cloned and working directory is the repo root
- [ ] `gh auth status` passes
- [ ] `zeroshot run` command includes `--pr --provider opencode`
- [ ] Outcome (PR URL or failure summary) reported to the user
```

- [ ] **Step 2: Validate the frontmatter**

Run:
```bash
python3 - <<'EOF'
import yaml, re, pathlib
content = pathlib.Path("assets/hermes-skills/zeroshot/SKILL.md").read_text()
assert content.startswith("---"), "Must start with ---"
m = re.search(r'\n---\s*\n', content[3:])
assert m, "Must have closing ---"
fm = yaml.safe_load(content[3:m.start()+3])
assert "name" in fm, "Missing name"
assert "description" in fm, "Missing description"
assert len(fm["description"]) <= 1024, f"Description too long: {len(fm['description'])}"
assert len(content) <= 100_000, "File too large"
print(f"OK — name={fm['name']!r}, description length={len(fm['description'])}, file size={len(content)}")
EOF
```

Expected output:
```
OK — name='zeroshot', description length=<N>, file size=<N>
```

- [ ] **Step 3: Commit**

```bash
git add assets/hermes-skills/zeroshot/SKILL.md
git commit -m "feat: add zeroshot hermes skill asset"
```

---

### Task 2: Update Dockerfile and validation script

**Files:**
- Modify: `Dockerfile` (lines 31–35 — the claude-settings copy + npm install block)
- Modify: `scripts/validate-image.sh` (add zeroshot CLI check + skill file path check)

**Interfaces:**
- Consumes: `assets/hermes-skills/zeroshot/SKILL.md` from Task 1
- Produces: Docker image with `zeroshot` binary and skill at `/root/.hermes/skills/software-development/zeroshot/SKILL.md`

- [ ] **Step 1: Add zeroshot and skill-path checks to the validation script**

This step is written first (TDD order) so the checks exist before the Dockerfile change. They will fail against the current image and pass after the build.

Edit `scripts/validate-image.sh`. Replace the final two lines:

```bash
echo ""
echo "=== All checks passed ==="
```

With:

```bash
echo ""
echo "=== Verifying zeroshot CLI ==="
docker run --rm --entrypoint "" "${IMAGE}" zeroshot --version

echo ""
echo "=== Verifying zeroshot skill file ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /root/.hermes/skills/software-development/zeroshot/SKILL.md && echo "Skill file present at /root/.hermes/skills/software-development/zeroshot/SKILL.md"

echo ""
echo "=== All checks passed ==="
```

- [ ] **Step 2: Update the Dockerfile**

The current block (lines 31–35) reads:

```dockerfile
COPY assets/claude-settings.json /root/.claude/settings.json
RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force && \
    claude --version
```

Replace it with:

```dockerfile
COPY assets/claude-settings.json /root/.claude/settings.json
COPY assets/hermes-skills/zeroshot/SKILL.md /root/.hermes/skills/software-development/zeroshot/SKILL.md
RUN npm install -g @anthropic-ai/claude-code @the-open-engine/zeroshot && \
    npm cache clean --force && \
    claude --version && \
    zeroshot --version
```

- [ ] **Step 3: Run the validation script**

```bash
./scripts/validate-image.sh
```

Expected output (abbreviated):
```
=== Building ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev ===
...
=== Verifying claude CLI ===
Claude Code ...

=== Verifying discord package ===
...

=== Verifying gh CLI ===
gh version ...

=== Verifying opencode ===
...

=== Verifying zeroshot CLI ===
zeroshot/<version>

=== Verifying zeroshot skill file ===
Skill file present at /root/.hermes/skills/software-development/zeroshot/SKILL.md

=== All checks passed ===
```

If the zeroshot CLI check fails with "executable file not found", the npm install step did not run correctly — check the Dockerfile edit for typos.

If the skill file check fails, confirm the COPY path in the Dockerfile matches the asset path exactly (`assets/hermes-skills/zeroshot/SKILL.md`).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile scripts/validate-image.sh
git commit -m "feat: install zeroshot CLI and bake hermes skill into image"
```

---

## Post-Implementation

After merging to `main`, the GHA workflow (`.github/workflows/docker-build.yml`) triggers on the `Dockerfile` path change, builds and pushes the multi-arch image, and auto-commits the updated image tag into `flux/apps/hermes-jon.yaml` and `flux/apps/hermes-ana.yaml`. Flux CD reconciles within 5 minutes and rolls out the new pod.

To verify the skill loads in a live hermes session after rollout, start a new conversation with hermes and run:
```
/skills list
```
The `zeroshot` skill should appear under `software-development`.
