# Zeroshot Skill → neuroslick Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the zeroshot hermes-skill, its test suite, and its design history from homelab into the new `neuroslick` repo (a multi-skill plugin repo modeled on `superpowers`), then clean up the now-dead references in homelab without pushing the homelab changes.

**Architecture:** neuroslick adopts the standard Claude Code plugin layout (`.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `tests/<name>/{unit,integration}`). The integration test harness is made self-contained — it now seeds the skill file into the test container itself rather than relying on the Docker image baking it in, since the skill will be installed at runtime via `hermes skills install` going forward. Homelab keeps Docker-image infrastructure (zeroshot-patches, Dockerfile, flux deployment) and drops everything skill-content-related.

**Tech Stack:** Python/pytest (tests), Docker (integration test harness), GitHub Actions (CI), Markdown (skill + docs).

## Global Constraints

- Two repos involved: `/Users/jonregeimbal/Dev/jregeimbal/homelab` (source of truth being migrated *from*) and `/Users/jonregeimbal/Dev/jregeimbal/neuroslick` (destination, already exists on GitHub as a public repo, currently just a README).
- Do not push homelab changes — commit locally only, on a branch.
- neuroslick changes are committed locally; do not push without separate confirmation (pushing is a visible, hard-to-reverse action).
- `assets/zeroshot-patches/` and the Dockerfile's COPY lines for those patches stay in homelab untouched — they patch the zeroshot npm CLI, not the skill.
- Don't touch `the-open-engine/zeroshot` (the CLI tool repo) — out of scope.

---

## Phase A — neuroslick

### Task 1: Scaffold the plugin structure

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/.claude-plugin/plugin.json`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/LICENSE`

**Interfaces:**
- Produces: `.claude-plugin/plugin.json` — the plugin manifest later tasks don't reference directly, but it's required for neuroslick to be installable as a Claude Code plugin.

- [ ] **Step 1: Create directory layout**

```bash
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/.claude-plugin
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/skills/zeroshot
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/expected
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/plans
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/specs
mkdir -p /Users/jonregeimbal/Dev/jregeimbal/neuroslick/.github/workflows
```

- [ ] **Step 2: Write the plugin manifest**

Write `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/.claude-plugin/plugin.json`:

```json
{
  "name": "neuroslick",
  "description": "A collection of skills enabling LLM agents to operate complex deterministic automata with hard gates.",
  "version": "0.1.0",
  "author": {
    "name": "Jon Regeimbal"
  },
  "homepage": "https://github.com/jregeimbal/neuroslick",
  "repository": "https://github.com/jregeimbal/neuroslick",
  "license": "MIT",
  "keywords": [
    "skills",
    "zeroshot",
    "multi-agent",
    "hermes",
    "automation"
  ]
}
```

- [ ] **Step 3: Write the LICENSE**

Write `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/LICENSE` (MIT, matching the `license: MIT` field already declared in zeroshot's `SKILL.md`):

```
MIT License

Copyright (c) 2026 Jon Regeimbal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Verify**

```bash
test -f /Users/jonregeimbal/Dev/jregeimbal/neuroslick/.claude-plugin/plugin.json && \
test -f /Users/jonregeimbal/Dev/jregeimbal/neuroslick/LICENSE && \
python3 -m json.tool /Users/jonregeimbal/Dev/jregeimbal/neuroslick/.claude-plugin/plugin.json > /dev/null && \
echo OK
```

Expected: `OK`

---

### Task 2: Move the SKILL.md

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/skills/zeroshot/SKILL.md`
- Source (unchanged): `/Users/jonregeimbal/Dev/jregeimbal/homelab/assets/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md`

- [ ] **Step 1: Copy the file verbatim**

```bash
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/assets/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/skills/zeroshot/SKILL.md
```

- [ ] **Step 2: Verify content is identical**

```bash
diff /Users/jonregeimbal/Dev/jregeimbal/homelab/assets/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md \
     /Users/jonregeimbal/Dev/jregeimbal/neuroslick/skills/zeroshot/SKILL.md
```

Expected: no output (files identical)

---

### Task 3: Move design docs

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/plans/2026-06-22-zeroshot-hermes-jon.md`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/plans/2026-06-23-zeroshot-skill-validation.md`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/specs/2026-06-22-zeroshot-hermes-jon-design.md`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/specs/2026-06-23-zeroshot-skill-validation-design.md`

- [ ] **Step 1: Copy all four docs**

```bash
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/plans/2026-06-22-zeroshot-hermes-jon.md \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/plans/2026-06-22-zeroshot-hermes-jon.md
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/plans/2026-06-23-zeroshot-skill-validation.md \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/plans/2026-06-23-zeroshot-skill-validation.md
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/specs/2026-06-22-zeroshot-hermes-jon-design.md \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/specs/2026-06-22-zeroshot-hermes-jon-design.md
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/specs/2026-06-23-zeroshot-skill-validation-design.md \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs/specs/2026-06-23-zeroshot-skill-validation-design.md
```

- [ ] **Step 2: Verify all four copied**

```bash
find /Users/jonregeimbal/Dev/jregeimbal/neuroslick/docs -type f | sort
```

Expected: the 4 files listed above.

---

### Task 4: Move and fix the unit tests

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit/test_skill_loop_guards.py`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit/test_skill_step2.py`

**Interfaces:**
- Consumes: `skills/zeroshot/SKILL.md` (produced by Task 2)

- [ ] **Step 1: Copy both test files**

```bash
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/unit/zeroshot/test_skill_loop_guards.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit/test_skill_loop_guards.py
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/unit/zeroshot/test_skill_step2.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit/test_skill_step2.py
```

- [ ] **Step 2: Fix `SKILL_PATH` in `test_skill_loop_guards.py`**

The file now lives at `tests/zeroshot/unit/test_skill_loop_guards.py` (still 3 directories below repo root, so `parents[3]` still resolves to the repo root — only the subpath after it changes, since the skill is no longer under `assets/hermes-skills/...`).

In `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit/test_skill_loop_guards.py`, replace:

```python
SKILL_PATH = (
    Path(__file__).parents[3]
    / "assets" / "hermes-skills" / "autonomous-ai-agents" / "zeroshot" / "SKILL.md"
)
```

with:

```python
SKILL_PATH = Path(__file__).parents[3] / "skills" / "zeroshot" / "SKILL.md"
```

- [ ] **Step 3: Fix `SKILL_PATH` in `test_skill_step2.py`**

In `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/unit/test_skill_step2.py`, replace:

```python
SKILL_PATH = (
    Path(__file__).parents[3]
    / "assets"
    / "hermes-skills"
    / "autonomous-ai-agents"
    / "zeroshot"
    / "SKILL.md"
)
```

with:

```python
SKILL_PATH = Path(__file__).parents[3] / "skills" / "zeroshot" / "SKILL.md"
```

- [ ] **Step 4: Run the unit tests**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && python3 -m pytest tests/zeroshot/unit/ -v
```

Expected: all tests in both files PASS (9 tests total: 3 + 6).

---

### Task 5: Move and fix the integration tests

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/conftest.py`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/test_zeroshot_skill.py`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/test_opencode_json_schema.py`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/opencode-openrouter.json`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/calculator.py`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/test_calculator.py`
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/expected/calculator.py`

**Interfaces:**
- Consumes: `skills/zeroshot/SKILL.md` (produced by Task 2)

- [ ] **Step 1: Copy all integration test files (excluding caches)**

```bash
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/conftest.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/conftest.py
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/test_zeroshot_skill.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/test_zeroshot_skill.py
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/test_opencode_json_schema.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/test_opencode_json_schema.py
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/opencode-openrouter.json \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/opencode-openrouter.json
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/fixture/calculator.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/calculator.py
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/fixture/test_calculator.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/test_calculator.py
cp /Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/fixture/expected/calculator.py \
   /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/fixture/expected/calculator.py
```

- [ ] **Step 2: Add skill-seeding to `conftest.py`**

The skill is no longer baked into the Docker image (it's installed at runtime via `hermes skills install`), so the test harness must seed it itself, mirroring the path the flux deployment used to write to (`/opt/data/skills/autonomous-ai-agents/zeroshot/SKILL.md`).

In `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/integration/conftest.py`, add this constant near the top, after the existing `FIXTURE_DIR` constant:

```python
FIXTURE_DIR = Path(__file__).parent / "fixture"
SKILL_FILE = Path(__file__).parents[3] / "skills" / "zeroshot" / "SKILL.md"
```

Then in `_seed_hermes_data_dir`, add this block right after the `(data_dir / "config.yaml").write_text(_HERMES_CONFIG)` line:

```python
    (data_dir / "config.yaml").write_text(_HERMES_CONFIG)

    # Skill is no longer baked into the image — installed at runtime via
    # `hermes skills install`. Seed it directly so these tests stay
    # self-contained and don't depend on how a given image ships skills.
    skill_dir = data_dir / "skills" / "autonomous-ai-agents" / "zeroshot"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_FILE.read_text())

```

(Leave the rest of `_seed_hermes_data_dir` — the opencode config and `~/.claude/settings.json` seeding — unchanged.)

- [ ] **Step 3: Verify the new constant resolves correctly**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && python3 -c "
from pathlib import Path
import sys
sys.path.insert(0, 'tests/zeroshot/integration')
import conftest
assert conftest.SKILL_FILE.exists(), conftest.SKILL_FILE
print('OK', conftest.SKILL_FILE)
"
```

Expected: `OK /Users/jonregeimbal/Dev/jregeimbal/neuroslick/skills/zeroshot/SKILL.md`

- [ ] **Step 4: Collect the integration tests (no network/docker required for collection)**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && python3 -m pytest tests/zeroshot/integration/ --collect-only -q
```

Expected: test IDs listed, no collection errors. (Running them for real requires Docker + the hermes image + API keys — covered in Task 10's manual-verification note, not automated here.)

---

### Task 6: Add the test requirements file

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/requirements.txt`

- [ ] **Step 1: Write the file**

```
pytest
pytest-rerunfailures
```

- [ ] **Step 2: Verify**

```bash
pip install -r /Users/jonregeimbal/Dev/jregeimbal/neuroslick/tests/zeroshot/requirements.txt
```

Expected: installs cleanly (pytest is likely already installed; pytest-rerunfailures gets added).

---

### Task 7: Add neuroslick CI workflow

**Files:**
- Create: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `tests/zeroshot/requirements.txt` (Task 6), `tests/zeroshot/unit/` (Task 4), `tests/zeroshot/integration/` (Task 5)

- [ ] **Step 1: Write the workflow**

```yaml
---
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install test dependencies
        run: pip install -r tests/zeroshot/requirements.txt

      - name: Run unit tests
        run: pytest tests/zeroshot/unit/ -v

  zeroshot-integration:
    name: Zeroshot Integration (claude)
    runs-on: ubuntu-latest
    timeout-minutes: 45
    needs: [unit-tests]
    if: github.event_name == 'pull_request'
    permissions:
      contents: read
      packages: read
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Pull hermes image
        run: docker pull ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:latest

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install test dependencies
        run: pip install -r tests/zeroshot/requirements.txt

      - name: Run zeroshot integration tests
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          HERMES_IMAGE: ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:latest
          ZEROSHOT_TIMEOUT: "2400"
        run: pytest tests/zeroshot/integration/ -v --reruns 1 --reruns-delay 30
```

This requires two manual follow-ups outside this plan's control (called out in the design doc):
1. Add the `ANTHROPIC_API_KEY` secret to the neuroslick GitHub repo settings.
2. Confirm `ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab` grants read access to the neuroslick repo (or make the package public) — otherwise the "Pull hermes image" step will 403.

- [ ] **Step 2: Verify YAML is well-formed**

```bash
python3 -c "import yaml; yaml.safe_load(open('/Users/jonregeimbal/Dev/jregeimbal/neuroslick/.github/workflows/ci.yml'))" && echo OK
```

Expected: `OK`

---

### Task 8: Rewrite the README

**Files:**
- Modify: `/Users/jonregeimbal/Dev/jregeimbal/neuroslick/README.md`

- [ ] **Step 1: Replace the README contents**

Current content is just a single `# neuroslick` heading. Replace the full file with:

```markdown
# neuroslick

A collection of skills enabling LLM agents to operate complex deterministic automata with hard
gates. Structured as a Claude Code plugin so it can host many skills over time, in the spirit of
[superpowers](https://github.com/obra/superpowers) and
[frontend-slides](https://github.com/zarazhangrui/frontend-slides).

## Skills

| Skill | Description |
|---|---|
| [`zeroshot`](skills/zeroshot/SKILL.md) | Orchestrates a multi-agent (planner → implementer → validator) coding workflow via the [zeroshot](https://github.com/the-open-engine/zeroshot) CLI, launched and monitored from inside a [hermes](https://github.com/NousResearch/hermes-agent) agent session. |

## Testing

Each skill has its own test suite under `tests/<skill-name>/`:

```bash
pip install -r tests/zeroshot/requirements.txt

# Unit tests — pure SKILL.md content checks, no external dependencies
pytest tests/zeroshot/unit/ -v

# Integration tests — docker-run a real hermes container against a live provider
# (Anthropic API or local LM Studio). Requires Docker and ANTHROPIC_API_KEY.
pytest tests/zeroshot/integration/ -v
```

## Installing a skill

Skills here are hermes-flavored `SKILL.md` files. Install one into a running hermes agent with:

```bash
hermes skills install <path-or-url-to-skill-dir>
```
```

- [ ] **Step 2: Verify**

```bash
cat /Users/jonregeimbal/Dev/jregeimbal/neuroslick/README.md | head -5
```

Expected: starts with `# neuroslick`.

---

### Task 9: Commit neuroslick changes

**Files:** none (commit only)

- [ ] **Step 1: Review what's staged**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && git status
```

Expected: new files under `.claude-plugin/`, `skills/`, `tests/`, `docs/`, `.github/`, plus modified `README.md` and new `LICENSE`.

- [ ] **Step 2: Stage and commit**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick
git add .claude-plugin LICENSE skills tests docs .github README.md
git commit -m "$(cat <<'EOF'
feat: add zeroshot skill, migrated from jregeimbal/homelab

Moves the hardened zeroshot hermes-skill, its unit/integration test
suite, and design history out of homelab into this multi-skill plugin
repo. The integration test harness now seeds the skill file directly
rather than relying on it being baked into the hermes Docker image,
since the skill is installed at runtime via `hermes skills install`
going forward.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Verify**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && git log --oneline -1 && git status
```

Expected: commit present, working tree clean. **Do not push** — wait for explicit user confirmation.

---

## Phase B — homelab cleanup

### Task 10: Create a cleanup branch

**Files:** none

- [ ] **Step 1: Branch off main**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && git checkout -b chore/move-zeroshot-skill-to-neuroslick
```

- [ ] **Step 2: Verify**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && git branch --show-current
```

Expected: `chore/move-zeroshot-skill-to-neuroslick`

---

### Task 11: Delete moved skill, tests, docs, and dead directory

**Files:**
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/assets/hermes-skills/`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/tests/integration/zeroshot/`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/tests/unit/zeroshot/`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/plans/2026-06-22-zeroshot-hermes-jon.md`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/plans/2026-06-23-zeroshot-skill-validation.md`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/specs/2026-06-22-zeroshot-hermes-jon-design.md`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/docs/superpowers/specs/2026-06-23-zeroshot-skill-validation-design.md`
- Delete: `/Users/jonregeimbal/Dev/jregeimbal/homelab/scripts/validate-zeroshot/`

**Interfaces:**
- Consumes: confirmation that Phase A tasks 2–5 completed (content now lives in neuroslick) — do not run this task before Phase A is done and committed.

- [ ] **Step 1: Delete with git rm**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab
git rm -r assets/hermes-skills
git rm -r tests/integration/zeroshot
git rm -r tests/unit/zeroshot
git rm docs/superpowers/plans/2026-06-22-zeroshot-hermes-jon.md
git rm docs/superpowers/plans/2026-06-23-zeroshot-skill-validation.md
git rm docs/superpowers/specs/2026-06-22-zeroshot-hermes-jon-design.md
git rm docs/superpowers/specs/2026-06-23-zeroshot-skill-validation-design.md
```

`scripts/validate-zeroshot/` contains no git-tracked files (only a stray local `__pycache__`,
already gitignored) — it's dead weight left over from before these tests were relocated. Remove it
directly rather than with `git rm` (which would fail with "pathspec did not match any files"):

```bash
rm -rf /Users/jonregeimbal/Dev/jregeimbal/homelab/scripts/validate-zeroshot
```

- [ ] **Step 2: Verify nothing zeroshot-skill-related remains except the patches and the new design doc**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && find . -iname "*zeroshot*" -not -path "./.git/*"
```

Expected output (only these remain):
```
./assets/zeroshot-patches
./docs/superpowers/plans/2026-06-30-zeroshot-to-neuroslick-migration.md
./docs/superpowers/specs/2026-06-30-zeroshot-to-neuroslick-migration-design.md
```
(plus the `assets/zeroshot-patches/*.js` files themselves, and Dockerfile/CI/flux/validate-image.sh references handled in the next tasks)

---

### Task 12: Remove the skill COPY from the Dockerfile

**Files:**
- Modify: `/Users/jonregeimbal/Dev/jregeimbal/homelab/Dockerfile:31`

- [ ] **Step 1: Remove the line**

In `/Users/jonregeimbal/Dev/jregeimbal/homelab/Dockerfile`, remove this line (keep everything else, including the `assets/claude-settings.json` and `assets/gitconfig` COPY lines around it):

```dockerfile
COPY assets/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md /opt/config-defaults/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md
```

- [ ] **Step 2: Verify**

```bash
grep -n "hermes-skills" /Users/jonregeimbal/Dev/jregeimbal/homelab/Dockerfile
```

Expected: no output (no matches).

---

### Task 13: Remove the skill seeding from the flux deployment

**Files:**
- Modify: `/Users/jonregeimbal/Dev/jregeimbal/homelab/flux/apps/hermes-jon.yaml`

- [ ] **Step 1: Remove the two lines**

In `/Users/jonregeimbal/Dev/jregeimbal/homelab/flux/apps/hermes-jon.yaml`, remove these two lines from the `bootstrap-home-config` init container script (keep the surrounding `gitconfig`/`claude settings`/`opencode.json` seeding steps untouched):

```
            mkdir -p /opt/data/skills/autonomous-ai-agents/zeroshot
            cp /opt/config-defaults/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md /opt/data/skills/autonomous-ai-agents/zeroshot/SKILL.md
```

- [ ] **Step 2: Verify**

```bash
grep -n "zeroshot" /Users/jonregeimbal/Dev/jregeimbal/homelab/flux/apps/hermes-jon.yaml
```

Expected: no output.

- [ ] **Step 3: Validate the YAML is still well-formed**

```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('/Users/jonregeimbal/Dev/jregeimbal/homelab/flux/apps/hermes-jon.yaml')))" && echo OK
```

Expected: `OK`

---

### Task 14: Remove the zeroshot CI jobs

**Files:**
- Modify: `/Users/jonregeimbal/Dev/jregeimbal/homelab/.github/workflows/ci.yml`

- [ ] **Step 1: Remove the `zeroshot-paths` job**

In `/Users/jonregeimbal/Dev/jregeimbal/homelab/.github/workflows/ci.yml`, remove the entire `zeroshot-paths` job block:

```yaml
  zeroshot-paths:
    runs-on: ubuntu-latest
    timeout-minutes: 1
    if: github.event_name == 'pull_request'
    outputs:
      changed: ${{ steps.filter.outputs.zeroshot }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            zeroshot:
              - Dockerfile
              - assets/**
              - tests/requirements.txt
              - tests/integration/zeroshot/**

```

- [ ] **Step 2: Remove the `zeroshot-integration` job**

Remove the entire `zeroshot-integration` job block:

```yaml
  zeroshot-integration:
    name: Zeroshot Integration (claude)
    runs-on: ubuntu-latest
    timeout-minutes: 45
    needs: [yaml-lint, k8s-validation, secret-scanning, json-lint, unit-tests, zeroshot-paths]
    if: github.event_name == 'pull_request' && needs.zeroshot-paths.outputs.changed == 'true'
    permissions:
      contents: read
      packages: read
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Pull hermes image
        run: docker pull ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:latest

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install test dependencies
        run: pip install -r tests/requirements.txt

      - name: Run zeroshot integration tests
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY_INTEGRATION_TESTS }}
          HERMES_IMAGE: ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:latest
          ZEROSHOT_TIMEOUT: "2400"
        run: pytest tests/integration/zeroshot/ -v --reruns 1 --reruns-delay 30

```

- [ ] **Step 3: Fix the `security-review` job's `needs` list if it referenced zeroshot jobs**

Check first — from the file as currently read, `security-review` only depends on `[yaml-lint, k8s-validation, secret-scanning, json-lint, unit-tests]`, not on the zeroshot jobs, so no change is expected there. Confirm:

```bash
grep -A3 "^  security-review:" /Users/jonregeimbal/Dev/jregeimbal/homelab/.github/workflows/ci.yml
```

Expected: `needs: [yaml-lint, k8s-validation, secret-scanning, json-lint, unit-tests]` — no `zeroshot-*` entries. If any are present, remove them from the list.

- [ ] **Step 4: Verify YAML validity and no remaining references**

```bash
python3 -c "import yaml; yaml.safe_load(open('/Users/jonregeimbal/Dev/jregeimbal/homelab/.github/workflows/ci.yml'))" && echo OK
grep -n -i "zeroshot" /Users/jonregeimbal/Dev/jregeimbal/homelab/.github/workflows/ci.yml
```

Expected: `OK`, then no grep output.

---

### Task 15: Remove the skill check from validate-image.sh

**Files:**
- Modify: `/Users/jonregeimbal/Dev/jregeimbal/homelab/scripts/validate-image.sh`

- [ ] **Step 1: Remove the check block**

In `/Users/jonregeimbal/Dev/jregeimbal/homelab/scripts/validate-image.sh`, remove this block (keep the `zeroshot CLI` version check above it — that one verifies the CLI binary, not the skill, and stays):

```bash
echo ""
echo "=== Verifying config-defaults: zeroshot skill ==="
docker run --rm --entrypoint "" "${IMAGE}" test -f /opt/config-defaults/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md \
  || { echo "ERROR: Missing /opt/config-defaults/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md"; exit 1; }
echo "zeroshot skill present"
```

- [ ] **Step 2: Verify**

```bash
grep -n -i "zeroshot skill\|hermes-skills" /Users/jonregeimbal/Dev/jregeimbal/homelab/scripts/validate-image.sh
```

Expected: no output. The `=== Verifying zeroshot CLI ===` check (a different, earlier block) should still be present:

```bash
grep -n "Verifying zeroshot CLI" /Users/jonregeimbal/Dev/jregeimbal/homelab/scripts/validate-image.sh
```

Expected: one match.

---

### Task 16: Commit the homelab cleanup (do not push)

**Files:** none (commit only)

- [ ] **Step 1: Review the diff**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && git status && git diff --stat
```

Expected: deletions under `assets/hermes-skills/`, `tests/integration/zeroshot/`, `tests/unit/zeroshot/`, `docs/superpowers/{plans,specs}/2026-06-2[23]-zeroshot-*`, `scripts/validate-zeroshot/`; modifications to `Dockerfile`, `flux/apps/hermes-jon.yaml`, `.github/workflows/ci.yml`, `scripts/validate-image.sh`.

- [ ] **Step 2: Stage and commit**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab
git add -A -- assets/hermes-skills tests/integration/zeroshot tests/unit/zeroshot \
  docs/superpowers/plans/2026-06-22-zeroshot-hermes-jon.md \
  docs/superpowers/plans/2026-06-23-zeroshot-skill-validation.md \
  docs/superpowers/specs/2026-06-22-zeroshot-hermes-jon-design.md \
  docs/superpowers/specs/2026-06-23-zeroshot-skill-validation-design.md \
  Dockerfile flux/apps/hermes-jon.yaml \
  .github/workflows/ci.yml scripts/validate-image.sh
git commit -m "$(cat <<'EOF'
chore: remove zeroshot skill, now hosted in jregeimbal/neuroslick

The zeroshot hermes-skill, its test suite, and design history moved to
the neuroslick repo. The skill is no longer baked into the hermes
Docker image — it's installed at runtime via `hermes skills install`.
zeroshot-patches (which patch the zeroshot CLI binary, not the skill)
and the Dockerfile/image build stay in homelab unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Verify**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && git log --oneline -1 && git status
```

Expected: commit present on `chore/move-zeroshot-skill-to-neuroslick`, working tree clean. **Do not push.** Report the branch name to the user and wait for sign-off before pushing or opening a PR.

---

## Final Verification (run after all tasks)

```bash
# neuroslick: unit tests pass
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && python3 -m pytest tests/zeroshot/unit/ -v

# homelab: confirm only the patches + this migration's own docs reference zeroshot
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && find . -iname "*zeroshot*" -not -path "./.git/*"

# homelab: confirm remaining CI is still valid YAML
python3 -c "import yaml; yaml.safe_load(open('/Users/jonregeimbal/Dev/jregeimbal/homelab/.github/workflows/ci.yml'))" && echo "CI OK"

# both repos: confirm nothing was pushed
cd /Users/jonregeimbal/Dev/jregeimbal/neuroslick && git log origin/main..HEAD --oneline
cd /Users/jonregeimbal/Dev/jregeimbal/homelab && git log origin/main..chore/move-zeroshot-skill-to-neuroslick --oneline
```

Expected: neuroslick unit tests pass; only `zeroshot-patches` and this migration's two new doc files remain in homelab's zeroshot grep; CI YAML valid; both `git log origin/main..HEAD` commands show local-only commits not yet pushed.
