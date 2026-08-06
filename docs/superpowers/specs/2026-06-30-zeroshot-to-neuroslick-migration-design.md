# Zeroshot Skill → neuroslick Migration

## Context

The zeroshot hermes-skill (`assets/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md`) has been
hardened in homelab over several iterations (loop-guard fixes, step-2 navigation fix, opencode JSON
schema validation), accumulating a dedicated integration/unit test suite
(`tests/integration/zeroshot/`, `tests/unit/zeroshot/`) and design history
(`docs/superpowers/plans|specs/2026-06-2[23]-zeroshot-*`).

This work moves the skill, its tests, and its design history out of homelab into a new repo,
`neuroslick` (https://github.com/jregeimbal/neuroslick, already created, public), which is intended
to host many skills going forward — modeled on the `superpowers` and `frontend-slides` Claude Code
plugin repos.

Homelab keeps everything that is genuinely homelab/Docker-image infrastructure rather than skill
content: `assets/zeroshot-patches/` (patches to the `@the-open-engine/zeroshot` npm CLI baked into
the hermes-agent image), the Dockerfile, and the flux deployment.

The skill will no longer be baked into the hermes-agent Docker image. Going forward it is installed
at runtime via `hermes skills install` (done manually by the user, outside this migration).

## neuroslick repo structure

Standard Claude Code plugin layout (verified against the cached `superpowers` plugin structure):

```
neuroslick/
  .claude-plugin/
    plugin.json
  skills/
    zeroshot/
      SKILL.md                          # moved as-is from homelab
  tests/
    zeroshot/
      unit/
        test_skill_loop_guards.py       # SKILL_PATH updated to point at skills/zeroshot/SKILL.md
        test_skill_step2.py             # SKILL_PATH updated to point at skills/zeroshot/SKILL.md
      integration/
        conftest.py                     # + seeds skills/zeroshot/SKILL.md into the test container
        test_zeroshot_skill.py
        test_opencode_json_schema.py
        fixture/
        opencode-openrouter.json
      requirements.txt                  # pytest, pytest-rerunfailures
  docs/
    plans/
      2026-06-22-zeroshot-hermes-jon.md
      2026-06-23-zeroshot-skill-validation.md
    specs/
      2026-06-22-zeroshot-hermes-jon-design.md
      2026-06-23-zeroshot-skill-validation-design.md
  .github/workflows/
    ci.yml
  README.md
  LICENSE
```

`assets/zeroshot-patches/` (3 JS files patching the zeroshot CLI binary, COPY'd into
`/usr/local/lib/node_modules/@the-open-engine/zeroshot/...` in the Dockerfile) is **not** part of
this move — it patches the zeroshot CLI tool, not the hermes-skill, and stays in homelab.

## Test migration mechanics

**Skill seeding inside the test harness.** Previously, the running container picked up the
SKILL.md via the Docker image build (`COPY` into `/opt/config-defaults/...`) plus a k8s deploy step
copying it into `/opt/data/skills/...`. Since the skill is no longer baked into the image,
`conftest.py`'s `_seed_hermes_data_dir` gains a step that copies
`<repo_root>/skills/zeroshot/SKILL.md` into
`data_dir/skills/autonomous-ai-agents/zeroshot/SKILL.md` before each container run, so the
integration tests are self-contained and don't depend on how a given image ships the skill.

**Path fixes.** `test_skill_loop_guards.py` and `test_skill_step2.py` resolve `SKILL_PATH` via a
relative `Path(__file__).parents[N]` lookup into `assets/hermes-skills/...`; this is updated to
resolve into `skills/zeroshot/SKILL.md` under the new repo layout.

**CI.** `neuroslick/.github/workflows/ci.yml` gets two jobs, mirroring homelab's current
`zeroshot-integration` job:
- `unit-tests`: no external dependencies, runs `pytest tests/zeroshot/unit/`.
- `zeroshot-integration`: pulls `ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:latest` and runs
  `pytest tests/zeroshot/integration/` with `ANTHROPIC_API_KEY` (claude provider only — opencode is
  skipped in CI, same as homelab today, since it needs LM Studio).

Two follow-ups outside this migration's control, called out explicitly so they aren't silently
dropped:
- The user adds the `ANTHROPIC_API_KEY` secret to the neuroslick GitHub repo.
- The user confirms (or grants) neuroslick's CI read access to the
  `ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab` package, since its current visibility wasn't
  verified from this environment.

## Homelab-side cleanup

Applied locally on a branch and **committed but not pushed**, pending sign-off on neuroslick:

- Delete `assets/hermes-skills/`
- Delete `tests/integration/zeroshot/` and `tests/unit/zeroshot/`
- Delete `docs/superpowers/plans/2026-06-2[23]-zeroshot-*.md` and
  `docs/superpowers/specs/2026-06-2[23]-zeroshot-*-design.md`
- Delete `scripts/validate-zeroshot/` (already dead — contains only a stale `__pycache__` left over
  from before these tests were relocated to `tests/integration/zeroshot/`)
- `Dockerfile`: remove the `COPY assets/hermes-skills/.../SKILL.md ...` line; keep the
  `zeroshot-patches` COPY lines
- `flux/apps/hermes-jon.yaml`: remove the `mkdir -p /opt/data/skills/.../zeroshot && cp ...` lines
- `.github/workflows/ci.yml`: remove the `zeroshot-paths` and `zeroshot-integration` jobs
- `scripts/validate-image.sh`: remove the check for
  `/opt/config-defaults/hermes-skills/.../SKILL.md`

Everything else (hermes-agent base image, opencode/claude config defaults, zeroshot-patches, the
deployment itself) is untouched.

## Out of scope

- Setting up `hermes skills install` for the zeroshot skill (user does this manually after the
  migration).
- Any change to the `the-open-engine/zeroshot` CLI tool itself.
- Granting neuroslick CI access to the ghcr package or adding its secrets (user action, called out
  above).
