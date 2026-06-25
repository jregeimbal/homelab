---
name: zeroshot
description: Use when the user asks to implement a GitHub issue using zeroshot, run a multi-agent coding workflow, or autonomously implement and verify a code change with a resulting PR. Supports opencode (LM Studio, local) and claude (Anthropic API) providers. Launches zeroshot in daemon mode (--pr --provider <provider> -d), monitors progress via logs, and reports the final outcome.
version: 1.4.0
author: Jon Regeimbal
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [zeroshot, multi-agent, github, pr, implementation, coding-agent, autonomous, blind-validation]
    related_skills: [plan, requesting-code-review]
---

# Zeroshot Multi-Agent Implementation

## Overview

Zeroshot orchestrates planner → implementer → validators in an isolated git worktree. Independent validators verify the work without seeing the implementer's reasoning (blind validation), looping until the change is verified or rejected. Tasks scale automatically: trivial tasks use 1 agent, critical tasks use up to 7. Use it when the user wants autonomous multi-agent implementation of a GitHub issue with a resulting PR.

Run in daemon mode (`-d`) so hermes is not blocked for the entire run — zeroshot clusters can take 30–90 minutes for non-trivial tasks.

## Provider Selection

Choose a provider based on what's available in the environment:

| Provider | Flag | When to use |
|---|---|---|
| `opencode` | `--provider opencode` | Default for local dev. Uses LM Studio via the baked-in opencode config. |
| `claude` | `--provider claude` | Anthropic API (requires `ANTHROPIC_API_KEY`). Stronger reasoning, slower, costs tokens. |

If the user doesn't specify, default to `opencode` for local repos and `claude` when the user mentions Anthropic or wants higher-quality output.

## When to Use

- User says "use zeroshot to implement issue #N"
- User asks for autonomous or multi-agent implementation of a GitHub issue
- User wants a verified PR produced from an issue description or markdown spec

Don't use for:
- Simple one-shot edits (use opencode, claude-code, codex, or the terminal directly)
- Tasks without a GitHub issue number, markdown file, or clear inline description

## Steps

1. **Confirm the target repo.** If the user has not specified `owner/repo`, ask for it before proceeding.

2. **Navigate to the repo.** Check whether the directory already exists before deciding what to do — never run `gh repo clone` when the directory is already present, as it will always fail:
   ```bash
   # If already cloned ([ -d /opt/data/<repo> ] is true):
   cd /opt/data/<repo> && git pull --rebase
   # If not yet cloned:
   cd /opt/data && gh repo clone <owner>/<repo> && cd <repo>
   ```
   Use `git pull --rebase` without explicit remote or branch — it uses the tracking-branch configuration set by `git clone` and works regardless of the default branch name.

   Run `git pull --rebase` **exactly once**. Whether it prints "Already up to date." or pulls new commits, that is a success — proceed immediately to step 3. Do not run it again.

3. **Check for an existing cluster**, then launch once if none exists:
   ```bash
   zeroshot list
   ```
   If a cluster for this repo is already `running` or in `setup`, record its ID and skip to step 4. Do not launch another cluster.

   If no relevant cluster exists, launch zeroshot **exactly once** from the repo root:
   ```bash
   zeroshot run <issue_number> --pr --provider opencode -d   # local dev (LM Studio)
   zeroshot run <issue_number> --pr --provider claude -d     # Anthropic API
   ```
   For a markdown file:
   ```bash
   zeroshot run path/to/spec.md --pr --provider opencode -d
   ```
   For inline text:
   ```bash
   zeroshot run "description of task" --pr --provider opencode -d
   ```
   If the command exits 0 and prints a cluster ID (e.g., `Started cobalt-lion-31`), record the ID and proceed. Do not run `zeroshot run` again regardless of what happens next.

4. **Confirm it's running**, then report the cluster ID to the user:
   ```bash
   zeroshot status <cluster-id>
   ```
   Do NOT use `zeroshot logs -f` or `-w` — those stream indefinitely and block the agent. Use status-based polling instead.

   Poll with a mandatory sleep between each check — rapid-fire status calls do not speed anything up:
   ```bash
   for i in 1 2 3; do zeroshot status <cluster-id>; sleep 60; done
   ```
   Re-run as needed. Exit early if the status shows `VERIFIED` or `REJECTED`.

   **If the cluster disappears from `zeroshot status` / `zeroshot list`**, do NOT assume failure. Zeroshot auto-deletes successful clusters after the PR is created — this is normal. To distinguish success from a true crash:
   ```bash
   grep "Cleaned up worktree isolation" ~/.zeroshot/<cluster-id>-daemon.log
   ```
   - Line present → cluster completed and auto-cleaned → check GitHub for the PR:
     ```bash
     gh pr list --repo <owner>/<repo> --state all --limit 5
     ```
   - Log file missing entirely → cluster may have crashed before starting. Report the situation to the user.

   **If status stays in `setup` for more than 2 minutes**, stop polling status and check the setup log instead:
   ```bash
   tail -50 ~/.zeroshot/<cluster-id>-daemon.log
   ```
   Common causes: LM Studio unreachable (for `opencode`), Anthropic API key not injected (for `claude`). Report what the log shows to the user rather than continuing to poll.

5. **Report the outcome** once the cluster finishes:
   - `VERIFIED` — PR was opened. Report the PR URL to the user.
   - Cluster auto-deleted (gone from `zeroshot list`) — this means success with `--pr`. Find and report the PR URL via `gh pr list`.
   - `REJECTED` — zeroshot exhausted retries. Report the failure summary and ask whether to resume or adjust.
   - To resume after failure or interruption:
     ```bash
     zeroshot resume <cluster-id> --provider opencode   # or --provider claude
     ```

6. **Remove the worktree** once report was sent to the user:
   (Optional) Clean up the worktree to avoid clutter.  Find the worktree path with `git worktree list | grep <cluster-id>` and remove it:
   ```bash
   git worktree remove <worktree-path>/<cluster-id>
   ```

## Management Commands

```bash
zeroshot list                    # show all clusters (active and past)
zeroshot status <cluster-id>     # current state — use this for polling (returns immediately)
zeroshot stop <cluster-id>       # graceful stop (waits for current agent to finish)
zeroshot kill <cluster-id>       # force-kill immediately
zeroshot resume <cluster-id>     # resume from last persisted checkpoint
```

## Common Pitfalls

1. **Not in the repo root.** Zeroshot creates worktrees relative to the current directory. Always `cd` into the repo before running.
2. **GitHub auth missing.** Run `gh auth status` first. The container has `gh` configured via `GH_CONFIG_DIR`; if it fails, report to the user rather than proceeding.
3. **Missing remote.** Zeroshot resolves issue numbers from the repo's `origin` remote. Ensure the cloned repo has a GitHub `origin`.
4. **Streaming logs.** Never use `zeroshot logs -f` or `-w` — they stream indefinitely and stall the agent. Use `zeroshot status <id>` in a short polling loop instead.
5. **Launching multiple clusters.** Run `zeroshot run` exactly once per session. Check `zeroshot list` first — if a cluster already exists for this repo, use it. Launching extras wastes resources and creates confusion about which cluster to track.
6. **Tight status polling.** Do not call `zeroshot status` repeatedly without sleeping. The `for i in 1 2 3` loop in step 4 includes `sleep 60` — that sleep is mandatory, not optional. Rapid-fire calls do not help and fill context with duplicate output.
7. **Cluster stuck in setup.** If `State: setup` persists for more than 2 minutes, stop polling status and read the setup log (`tail -50 ~/.zeroshot/<cluster-id>-daemon.log`). The log will reveal the actual error. Do not keep polling status — the state will not change until the underlying problem is fixed.
8. **Cluster disappears from `zeroshot list` — this is success, not failure.** Zeroshot auto-deletes the cluster record after a successful `--pr` run. If a cluster you were tracking is suddenly missing, check `grep "Cleaned up worktree isolation" ~/.zeroshot/<cluster-id>-daemon.log` and `gh pr list --repo <owner>/<repo> --state all --limit 5` before concluding it failed. A missing cluster with a daemon log that ends in cleanup is the normal success path.

## Verification Checklist

- [ ] `owner/repo` confirmed with the user
- [ ] Repo cloned and working directory is the repo root
- [ ] `gh auth status` passes
- [ ] `zeroshot run` command includes `-d --pr --provider <opencode|claude>`
- [ ] Cluster ID recorded from launch output
- [ ] Outcome (PR URL or failure summary) reported to the user
