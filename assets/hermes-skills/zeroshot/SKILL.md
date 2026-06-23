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
