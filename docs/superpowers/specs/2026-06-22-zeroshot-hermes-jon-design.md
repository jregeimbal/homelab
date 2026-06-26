# Zeroshot Integration for hermes jon-agent

## Overview

Install the `@the-open-engine/zeroshot` CLI into the custom hermes jon-agent Docker image and add a Hermes skill that guides the agent to invoke `zeroshot run <issue> --pr --provider opencode` when the user asks for autonomous multi-agent implementation of a GitHub issue.

Zeroshot is an open-source multi-agent orchestration CLI that runs planner → implementer → validators in an isolated git worktree, looping until changes are verified or rejected with reproducible failures. It produces a GitHub PR as output.

## Design Decisions

### Approach: Bake into Docker image

Everything is baked into the custom Docker image at build time. No Kubernetes manifest changes, no ConfigMaps, no new volumes. This matches the existing pattern for `opencode.json`, `claude-settings.json`, and the `gh` CLI install.

**Alternatives considered:**
- ConfigMap-mounted skill: more flexible for skill iteration but adds k8s boilerplate
- Agent self-bootstrap: fragile and not reproducible

### Provider: opencode

Both `claude` (via LM Studio) and `opencode` are already in the image. The SKILL.md hardcodes `--provider opencode` on the command line — no global zeroshot settings file needed.

### Isolation: --pr

Zeroshot runs with `--pr`, creating an isolated git worktree and opening a GitHub PR automatically. `gh` is already authenticated in the container via the sealed `GITHUB_TOKEN` secret.

### Repo resolution: user specifies

The skill asks the user for `owner/repo` if not in context, then clones into `/opt/data/<repo>` and runs zeroshot from the repo root. This is explicit and avoids ambiguity.

## Architecture

Three files change; nothing else in the repo is affected:

```
homelab/
├── Dockerfile                              ← add zeroshot npm install + COPY skill
├── assets/
│   ├── opencode.json                       (existing, unchanged)
│   ├── claude-settings.json               (existing, unchanged)
│   └── hermes-skills/
│       └── zeroshot/
│           └── SKILL.md                   ← new hermes skill
└── flux/apps/hermes-jon.yaml              (unchanged — image tag auto-bumped by CI)
```

The existing GHA workflow triggers on `Dockerfile` path changes, rebuilds the multi-arch image, and auto-bumps the image tag in `hermes-jon.yaml` and `hermes-ana.yaml`.

## Components

### 1. Dockerfile Changes

Add zeroshot to the existing npm install step:

```dockerfile
RUN npm install -g @anthropic-ai/claude-code @the-open-engine/zeroshot && \
    npm cache clean --force && \
    claude --version && \
    zeroshot --version
```

Copy the skill into the hermes user-local skills tree:

```dockerfile
COPY assets/hermes-skills/zeroshot/SKILL.md /root/.hermes/skills/software-development/zeroshot/SKILL.md
```

**Path note:** The container runs as uid 10000, but the existing convention (e.g., `/root/.claude/settings.json`) uses `/root` as the effective home. If hermes resolves `~/.hermes/skills/` to a different path for uid 10000, a fallback copy to `/opt/hermes/skills/software-development/zeroshot/SKILL.md` (the in-repo tree propagated by the init container) should be added.

### 2. Hermes Skill (`assets/hermes-skills/zeroshot/SKILL.md`)

Frontmatter:
- `name: zeroshot`
- Trigger description: "Use when the user asks to implement a GitHub issue using zeroshot, run a multi-agent coding workflow, or autonomously implement and verify a code change with a resulting PR."
- `related_skills: [plan, requesting-code-review]`

Skill behavior:
1. Confirm `owner/repo` with user if not in context
2. If repo exists at `/opt/data/<repo>`, `cd` into it and `git pull --rebase origin $(git symbolic-ref --short HEAD)` to update the default branch. If not present, clone it with `gh repo clone` then `cd` into it.
3. Run `zeroshot run <issue_number> --pr --provider opencode`
4. Report outcome: PR URL on `VERIFIED`, failure summary on `REJECTED`, resume command on interruption

## Data Flow

```
User: "use zeroshot to implement issue #42 on owner/repo"
  → Hermes loads zeroshot skill
  → Confirms repo; clones to /opt/data/repo if absent, otherwise pulls --rebase; cd into it
  → Runs: zeroshot run 42 --pr --provider opencode
      → zeroshot planner (opencode) → creates acceptance criteria
      → zeroshot implementer (opencode) → makes changes in git worktree
      → zeroshot validators (opencode) → verify independently
      → Loop until VERIFIED or REJECTED
      → On VERIFIED: gh pr create → PR URL returned
  → Hermes reports PR URL to user
```

## Error Handling

- **gh auth failure**: skill checks `gh auth status` before running; reports to user rather than proceeding
- **Missing repo remote**: documented in skill pitfalls — clone via `gh repo clone` ensures correct `origin`
- **REJECTED outcome**: skill instructs hermes to report the failure summary and offer `zeroshot resume <cluster-id>`
- **Interruption**: `zeroshot resume <cluster-id> --provider opencode` restores state from zeroshot's SQLite ledger
- **Path mismatch for skill**: if `/root/.hermes/skills/` is not found at runtime, add a second COPY to `/opt/hermes/skills/` in the Dockerfile

## Testing Strategy

- Build verification: `zeroshot --version` in the Dockerfile RUN step catches install failures at image build time
- Skill loading: verify in a fresh hermes session via `skill_view` or `skills_list` that the `zeroshot` skill appears
- End-to-end: run `zeroshot run "add a hello world test" --provider opencode` on a test repo to confirm the full planner/implementer/validator loop works with the LM Studio model
