# Zeroshot Skill Validation Script

## Overview

A local validation test that verifies the hermes zeroshot skill works end-to-end: hermes receives a prompt, invokes zeroshot against a synthetic Python repo with a failing test, zeroshot completes with `VERIFIED` status, and the code change matches an expected solution.

## Goals

- Catch regressions in the zeroshot skill before shipping a new hermes image
- Provide a human-readable fixture that documents exactly what zeroshot is expected to handle
- Produce pytest output suitable for CI or manual local runs

## Non-Goals

- Testing GitHub PR creation (`--pr` is omitted; this is a local-only test)
- Testing the LLM model itself; we assume the configured inference provider (`ANTHROPIC_BASE_URL`) is available and working

## Architecture

```
scripts/
└── validate-zeroshot/
    ├── conftest.py                  ← pytest fixtures: tmp repo setup, docker runner
    ├── test_zeroshot_skill.py       ← single test: test_zeroshot_fixes_calculator
    └── fixture/
        ├── calculator.py            ← defective file (unimplemented TODO stub)
        ├── test_calculator.py       ← failing tests (also serve as zeroshot acceptance criteria)
        └── expected/
            └── calculator.py        ← reference solution asserted against after the run
```

No new top-level dependencies beyond `pytest` and the standard library (`subprocess`, `shutil`, `ast`, `os`).

## Fixture

### `fixture/calculator.py`

```python
def add_numbers(a, b):
    """Return the sum of a and b."""
    # TODO: implement
    pass
```

### `fixture/test_calculator.py`

```python
from calculator import add_numbers

def test_add_numbers():
    assert add_numbers(2, 3) == 5
    assert add_numbers(-1, 1) == 0
    assert add_numbers(0, 0) == 0
```

These tests fail against the stub and pass against the expected solution. Zeroshot uses them as its acceptance criteria during the validator phase.

### `fixture/expected/calculator.py`

```python
def add_numbers(a, b):
    """Return the sum of a and b."""
    return a + b
```

## Test Flow

### `conftest.py` — `tmp_repo` fixture

1. Copy `fixture/` (excluding `expected/`) into `tmp_path / "data" / "validation-repo"` via `shutil.copytree`.
2. `git init`, `git add .`, `git commit -m "initial"` inside the copied dir so zeroshot has a clean working tree to branch from.
3. Yield `tmp_path / "data"` as the `/opt/data` mount point.

### `conftest.py` — `hermes_image` fixture

Returns the image tag from the `HERMES_IMAGE` env var, defaulting to `ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev`.

### `conftest.py` — provider env passthrough

All provider configuration comes from the caller's environment — nothing is hardcoded in the test. The following env vars are read at test time and forwarded into the container:

| Env var | Required | Description |
|---|---|---|
| `ANTHROPIC_BASE_URL` | Yes | Base URL for the inference API (e.g. `http://jonathans-mac-studio:1234` for LM Studio, `https://openrouter.ai/api/v1` for OpenRouter) |
| `ANTHROPIC_AUTH_TOKEN` | Yes | Auth token for the inference API (`lmstudio` for LM Studio, an API key for cloud providers) |
| `OPENCODE_CONFIG_PATH` | No | Local path to a custom `opencode.json` to mount over `/opt/data/home/.config/opencode/opencode.json`. Use this to switch opencode to a different provider (e.g. OpenRouter). If unset, the image's default config is used. |

The test fails with a clear error at collection time if `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN` are not set.

### Supported provider configurations

**LM Studio (default local dev):**
```bash
export ANTHROPIC_BASE_URL=http://jonathans-mac-studio:1234
export ANTHROPIC_AUTH_TOKEN=lmstudio
pytest scripts/validate-zeroshot/ -v
```

**OpenRouter (cloud):**
```bash
export ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1
export ANTHROPIC_AUTH_TOKEN=<openrouter-api-key>
export OPENCODE_CONFIG_PATH=./scripts/validate-zeroshot/opencode-openrouter.json
pytest scripts/validate-zeroshot/ -v
```

A `opencode-openrouter.json` example config is included in the fixture directory for reference.

### `test_zeroshot_skill.py` — `test_zeroshot_fixes_calculator`

```
docker run --rm
  --network host                              # LAN hostnames (e.g. LM Studio) resolve inside container
  -v <tmp_path/data>:/opt/data
  [-v <OPENCODE_CONFIG_PATH>:/opt/data/home/.config/opencode/opencode.json:ro]  # if set
  -e HERMES_HOME=/opt/data
  -e ANTHROPIC_BASE_URL                       # forwarded from caller env
  -e ANTHROPIC_AUTH_TOKEN                     # forwarded from caller env
  -e OPENCODE_TELEMETRY_DISABLED=1
  <image>
  hermes -z "<PROMPT>" --accept-hooks --yolo
```

Capture stdout+stderr with a configurable timeout (default 1800 s). The test blocks until the container exits.

## Prompt

```
There is a Python project at /opt/data/validation-repo. The function
add_numbers in calculator.py is not yet implemented (TODO stub) and
test_calculator.py is currently failing. Please use zeroshot to implement
it. Run: zeroshot run "implement add_numbers in calculator.py so that
test_calculator.py passes" --provider opencode (this is a local repo with
no GitHub remote — do not use --pr). Poll zeroshot status until VERIFIED or
REJECTED and report the outcome.
```

## Assertions

| Acceptance criterion | Assertion |
|---|---|
| Zeroshot returns success | `"VERIFIED" in output` |
| Final result provided to hermes matches expectation | `"add_numbers" in output` and `"REJECTED" not in output` |
| Code change matches expected solution | AST comparison of the modified `calculator.py` vs `fixture/expected/calculator.py` |

The AST comparison (`ast.parse` + `ast.dump`) compares the compiled function body semantically, so whitespace and comment differences do not cause spurious failures.

## Docker Run Details

- `--network host` is used on Linux so LAN hostnames (e.g. `jonathans-mac-studio`) resolve inside the container. On macOS Docker Desktop, `--network host` is a no-op; the container uses Docker's default bridge, and LAN hostnames must resolve via mDNS/DNS (same as production k8s). For cloud providers (OpenRouter), network access goes through the normal internet path and `--network host` is not needed but is harmless.
- `--accept-hooks --yolo` suppress hermes permission prompts so the container runs unattended.
- The container runs as uid 10000. The `tmp_path` volume is created by the test runner; if permission errors occur, the fixture should `chmod 777` the data dir before mounting.
- `OPENCODE_TELEMETRY_DISABLED=1` prevents opencode from phoning home during tests.
- `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` are passed through from the caller's environment without defaults — the test fails fast at collection time if either is missing.

## Timeout and CI Considerations

- Default timeout: 1800 s (30 min). Configurable via `ZEROSHOT_TIMEOUT` env var.
- For CI, this test should be in a separate job gated behind a label or manual trigger (not part of the fast lint/validate checks). LM Studio runs require mac-studio to be reachable; cloud provider runs (OpenRouter) can run in any CI environment with network access.

## File Placement

The test lives under `scripts/validate-zeroshot/` rather than a top-level `tests/` dir to stay consistent with the existing `scripts/validate-image.sh` convention. It is invoked with:

```bash
pytest scripts/validate-zeroshot/ -v
```
