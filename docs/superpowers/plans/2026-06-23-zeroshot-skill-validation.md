# Zeroshot Skill Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pytest-based integration test that spins up the custom hermes Docker image, plants a synthetic Python repo with a TODO stub under `/opt/data`, asks hermes to use zeroshot to fix it, and asserts on VERIFIED status, hermes output, and semantic code correctness.

**Architecture:** Three tasks build bottom-up: fixture files first (the synthetic repo), then conftest.py (pytest fixtures and env plumbing), then the test file (unit tests for helpers + the integration test). Each task ends with passing tests and a commit. The integration test is the only one that requires Docker and env vars; the helper unit tests run standalone.

**Tech Stack:** Python 3.14, pytest, subprocess, ast (stdlib), Docker CLI, hermes image (`ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev`)

## Global Constraints

- No new Python dependencies beyond `pytest` — everything else is stdlib.
- All inference provider config comes from caller env vars (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`) — nothing hardcoded.
- Test lives under `scripts/validate-zeroshot/` to match the `scripts/validate-image.sh` convention.
- The integration test (`test_zeroshot_fixes_calculator`) requires Docker and a reachable inference endpoint; the helper unit tests do not.
- Default timeout: 1800 s, overridable via `ZEROSHOT_TIMEOUT` env var.
- `--network host` is used so LAN hostnames (e.g. LM Studio) resolve inside the container; harmless for cloud providers.

---

## File Map

| File | Create/Modify | Purpose |
|---|---|---|
| `scripts/validate-zeroshot/fixture/calculator.py` | Create | Defective Python file — `add_numbers` is a TODO stub |
| `scripts/validate-zeroshot/fixture/test_calculator.py` | Create | Failing pytest tests; also serve as zeroshot's acceptance criteria |
| `scripts/validate-zeroshot/fixture/expected/calculator.py` | Create | Reference solution the test asserts against |
| `scripts/validate-zeroshot/opencode-openrouter.json` | Create | Example opencode config for the OpenRouter cloud provider |
| `scripts/validate-zeroshot/conftest.py` | Create | `tmp_repo`, `hermes_image`, `docker_env` pytest fixtures |
| `scripts/validate-zeroshot/test_zeroshot_skill.py` | Create | Unit tests for `_function_body_stmts` + integration test |

---

### Task 1: Synthetic fixture files

**Files:**
- Create: `scripts/validate-zeroshot/fixture/calculator.py`
- Create: `scripts/validate-zeroshot/fixture/test_calculator.py`
- Create: `scripts/validate-zeroshot/fixture/expected/calculator.py`
- Create: `scripts/validate-zeroshot/opencode-openrouter.json`

**Interfaces:**
- Produces: `fixture/test_calculator.py` imports `add_numbers` from `calculator` — used by zeroshot as acceptance criteria and by Task 3 for verifying the fix

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p scripts/validate-zeroshot/fixture/expected
```

- [ ] **Step 2: Write the defective stub**

Create `scripts/validate-zeroshot/fixture/calculator.py`:

```python
def add_numbers(a, b):
    """Return the sum of a and b."""
    # TODO: implement
    pass
```

- [ ] **Step 3: Write the failing tests**

Create `scripts/validate-zeroshot/fixture/test_calculator.py`:

```python
from calculator import add_numbers


def test_add_numbers():
    assert add_numbers(2, 3) == 5
    assert add_numbers(-1, 1) == 0
    assert add_numbers(0, 0) == 0
```

- [ ] **Step 4: Verify the tests fail against the stub**

Run:
```bash
python3 -m pytest scripts/validate-zeroshot/fixture/test_calculator.py -v --import-mode=importlib
```

Expected output:
```
FAILED scripts/validate-zeroshot/fixture/test_calculator.py::test_add_numbers
```
The test must fail (assertion error or None comparison) — if it passes, the stub is wrong.

- [ ] **Step 5: Write the expected solution**

Create `scripts/validate-zeroshot/fixture/expected/calculator.py`:

```python
def add_numbers(a, b):
    """Return the sum of a and b."""
    return a + b
```

- [ ] **Step 6: Verify the expected solution is correct**

```bash
python3 -c "
import sys
sys.path.insert(0, 'scripts/validate-zeroshot/fixture/expected')
from calculator import add_numbers
assert add_numbers(2, 3) == 5
assert add_numbers(-1, 1) == 0
assert add_numbers(0, 0) == 0
print('OK: all assertions pass')
"
```

Expected output: `OK: all assertions pass`

- [ ] **Step 7: Write the OpenRouter example config**

Create `scripts/validate-zeroshot/opencode-openrouter.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openrouter/anthropic/claude-sonnet-4-5",
  "provider": {
    "openrouter": {
      "npm": "@openrouter/ai-sdk-provider",
      "name": "OpenRouter",
      "options": {
        "apiKey": "${ANTHROPIC_AUTH_TOKEN}"
      },
      "models": {
        "anthropic/claude-sonnet-4-5": {
          "name": "Claude Sonnet 4.5 (via OpenRouter)"
        }
      }
    }
  }
}
```

> **Note:** This is a starting-point template. The exact provider schema depends on the opencode version in the image. Run `opencode providers` inside the container to list supported provider npm packages and verify the format before use.

- [ ] **Step 8: Commit**

```bash
git add scripts/validate-zeroshot/
git commit -m "test: add zeroshot validation fixture files"
```

---

### Task 2: `conftest.py` — pytest fixtures

**Files:**
- Create: `scripts/validate-zeroshot/conftest.py`

**Interfaces:**
- Consumes: `scripts/validate-zeroshot/fixture/` directory (from Task 1)
- Produces:
  - `tmp_repo` fixture → `pathlib.Path` pointing to a writable `/opt/data`-equivalent dir containing a git-initialized `validation-repo/`
  - `hermes_image` fixture → `str` image tag
  - `docker_env` fixture → `dict` with keys `base_url: str`, `auth_token: str`, `opencode_config_path: str | None`

- [ ] **Step 1: Install pytest**

```bash
pip3 install pytest
```

Verify:
```bash
python3 -m pytest --version
```
Expected: `pytest 8.x.x`

- [ ] **Step 2: Write conftest.py**

Create `scripts/validate-zeroshot/conftest.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixture"
DEFAULT_IMAGE = "ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev"


@pytest.fixture
def tmp_repo(tmp_path):
    data_dir = tmp_path / "data"
    repo_dir = data_dir / "validation-repo"
    shutil.copytree(FIXTURE_DIR, repo_dir, ignore=shutil.ignore_patterns("expected"))
    data_dir.chmod(0o777)
    repo_dir.chmod(0o777)
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
            "commit", "-m", "initial",
        ],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    return data_dir


@pytest.fixture
def hermes_image():
    return os.environ.get("HERMES_IMAGE", DEFAULT_IMAGE)


@pytest.fixture
def docker_env():
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    missing = [
        name for name, val in [
            ("ANTHROPIC_BASE_URL", base_url),
            ("ANTHROPIC_AUTH_TOKEN", auth_token),
        ]
        if not val
    ]
    if missing:
        pytest.fail(f"Required env vars not set: {', '.join(missing)}")
    return {
        "base_url": base_url,
        "auth_token": auth_token,
        "opencode_config_path": os.environ.get("OPENCODE_CONFIG_PATH"),
    }
```

- [ ] **Step 3: Verify pytest collection finds the fixtures**

```bash
python3 -m pytest scripts/validate-zeroshot/ --collect-only 2>&1 | head -20
```

Expected: no errors; fixtures listed as available (collection may show 0 tests since no test file exists yet — that's fine).

- [ ] **Step 4: Commit**

```bash
git add scripts/validate-zeroshot/conftest.py
git commit -m "test: add conftest fixtures for zeroshot validation"
```

---

### Task 3: Integration test and helper unit tests

**Files:**
- Create: `scripts/validate-zeroshot/test_zeroshot_skill.py`

**Interfaces:**
- Consumes:
  - `tmp_repo` fixture → `pathlib.Path` (from Task 2 conftest)
  - `hermes_image` fixture → `str` (from Task 2 conftest)
  - `docker_env` fixture → `dict` with `base_url`, `auth_token`, `opencode_config_path` (from Task 2 conftest)
  - `FIXTURE_DIR / "expected" / "calculator.py"` — reference solution (from Task 1)
- Produces: `_function_body_stmts(source: str, name: str) -> list[str]` consumed internally by `test_zeroshot_fixes_calculator`

- [ ] **Step 1: Write the failing unit tests first**

Create `scripts/validate-zeroshot/test_zeroshot_skill.py` with just the unit tests (no implementation yet):

```python
import ast
import os
import subprocess
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixture"
EXPECTED_CALCULATOR = FIXTURE_DIR / "expected" / "calculator.py"
ZEROSHOT_TIMEOUT = int(os.environ.get("ZEROSHOT_TIMEOUT", "1800"))

PROMPT = (
    "There is a Python project at /opt/data/validation-repo. "
    "The function add_numbers in calculator.py is not yet implemented (TODO stub) "
    "and test_calculator.py is currently failing. Please use zeroshot to implement it. "
    'Run: zeroshot run "implement add_numbers in calculator.py so that '
    'test_calculator.py passes" --provider opencode '
    "(this is a local repo with no GitHub remote — do not use --pr). "
    "Poll zeroshot status until VERIFIED or REJECTED and report the outcome."
)


# --- Unit tests for _function_body_stmts ---

def test_function_body_stmts_extracts_return():
    src = "def add_numbers(a, b):\n    return a + b\n"
    stmts = _function_body_stmts(src, "add_numbers")
    assert len(stmts) == 1
    assert "Return" in stmts[0]
    assert "BinOp" in stmts[0]


def test_function_body_stmts_skips_docstring():
    with_doc = 'def add_numbers(a, b):\n    """doc"""\n    return a + b\n'
    without_doc = "def add_numbers(a, b):\n    return a + b\n"
    assert _function_body_stmts(with_doc, "add_numbers") == _function_body_stmts(without_doc, "add_numbers")


def test_function_body_stmts_raises_for_unknown_function():
    src = "def other(): pass\n"
    with pytest.raises(ValueError, match="'add_numbers' not found"):
        _function_body_stmts(src, "add_numbers")
```

- [ ] **Step 2: Run the unit tests — expect NameError (function not defined yet)**

```bash
python3 -m pytest scripts/validate-zeroshot/test_zeroshot_skill.py -k "not zeroshot_fixes" -v
```

Expected: `ERROR` — `NameError: name '_function_body_stmts' is not defined`. This confirms the tests are wired up and failing for the right reason.

- [ ] **Step 3: Implement `_function_body_stmts` and add the integration test**

Replace the contents of `scripts/validate-zeroshot/test_zeroshot_skill.py` with:

```python
import ast
import os
import subprocess
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixture"
EXPECTED_CALCULATOR = FIXTURE_DIR / "expected" / "calculator.py"
ZEROSHOT_TIMEOUT = int(os.environ.get("ZEROSHOT_TIMEOUT", "1800"))

PROMPT = (
    "There is a Python project at /opt/data/validation-repo. "
    "The function add_numbers in calculator.py is not yet implemented (TODO stub) "
    "and test_calculator.py is currently failing. Please use zeroshot to implement it. "
    'Run: zeroshot run "implement add_numbers in calculator.py so that '
    'test_calculator.py passes" --provider opencode '
    "(this is a local repo with no GitHub remote — do not use --pr). "
    "Poll zeroshot status until VERIFIED or REJECTED and report the outcome."
)


def _function_body_stmts(source: str, name: str) -> list:
    """Return AST dumps of non-docstring body statements for the named function."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            stmts = node.body
            if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant):
                stmts = stmts[1:]
            return [ast.dump(s) for s in stmts]
    raise ValueError(f"Function {name!r} not found in source")


# --- Unit tests for _function_body_stmts ---

def test_function_body_stmts_extracts_return():
    src = "def add_numbers(a, b):\n    return a + b\n"
    stmts = _function_body_stmts(src, "add_numbers")
    assert len(stmts) == 1
    assert "Return" in stmts[0]
    assert "BinOp" in stmts[0]


def test_function_body_stmts_skips_docstring():
    with_doc = 'def add_numbers(a, b):\n    """doc"""\n    return a + b\n'
    without_doc = "def add_numbers(a, b):\n    return a + b\n"
    assert _function_body_stmts(with_doc, "add_numbers") == _function_body_stmts(without_doc, "add_numbers")


def test_function_body_stmts_raises_for_unknown_function():
    src = "def other(): pass\n"
    with pytest.raises(ValueError, match="'add_numbers' not found"):
        _function_body_stmts(src, "add_numbers")


# --- Integration test ---

def test_zeroshot_fixes_calculator(tmp_repo, hermes_image, docker_env):
    cmd = [
        "docker", "run", "--rm",
        "--network", "host",
        "-v", f"{tmp_repo}:/opt/data",
        "-e", "HERMES_HOME=/opt/data",
        "-e", f"ANTHROPIC_BASE_URL={docker_env['base_url']}",
        "-e", f"ANTHROPIC_AUTH_TOKEN={docker_env['auth_token']}",
        "-e", "OPENCODE_TELEMETRY_DISABLED=1",
    ]
    if docker_env["opencode_config_path"]:
        cmd += [
            "-v",
            f"{docker_env['opencode_config_path']}:/opt/data/home/.config/opencode/opencode.json:ro",
        ]
    cmd += [hermes_image, "hermes", "-z", PROMPT, "--accept-hooks", "--yolo"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=ZEROSHOT_TIMEOUT)
    output = result.stdout + result.stderr

    assert "VERIFIED" in output, (
        f"Expected VERIFIED in hermes output.\n--- OUTPUT ---\n{output}"
    )
    assert "REJECTED" not in output, (
        f"Zeroshot REJECTED the implementation.\n--- OUTPUT ---\n{output}"
    )
    assert "add_numbers" in output, (
        f"Expected mention of add_numbers in hermes summary.\n--- OUTPUT ---\n{output}"
    )

    changed = tmp_repo / "validation-repo" / "calculator.py"
    assert changed.exists(), f"calculator.py missing at {changed}"

    actual = _function_body_stmts(changed.read_text(), "add_numbers")
    expected = _function_body_stmts(EXPECTED_CALCULATOR.read_text(), "add_numbers")
    assert actual == expected, (
        f"Implementation does not match expected.\n"
        f"Actual:\n{changed.read_text()}\n"
        f"Expected:\n{EXPECTED_CALCULATOR.read_text()}"
    )
```

- [ ] **Step 4: Run the unit tests — expect PASS**

```bash
python3 -m pytest scripts/validate-zeroshot/test_zeroshot_skill.py -k "not zeroshot_fixes" -v
```

Expected output:
```
PASSED test_zeroshot_skill.py::test_function_body_stmts_extracts_return
PASSED test_zeroshot_skill.py::test_function_body_stmts_skips_docstring
PASSED test_zeroshot_skill.py::test_function_body_stmts_raises_for_unknown_function
3 passed
```

- [ ] **Step 5: Verify pytest collection includes the integration test**

```bash
python3 -m pytest scripts/validate-zeroshot/ --collect-only 2>&1
```

Expected: four tests collected — three unit tests plus `test_zeroshot_fixes_calculator`. No errors.

- [ ] **Step 6: Verify the integration test skips cleanly when env vars are missing**

```bash
python3 -m pytest scripts/validate-zeroshot/test_zeroshot_skill.py::test_zeroshot_fixes_calculator -v 2>&1
```

Expected: `FAILED` with message `Required env vars not set: ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN` (the `docker_env` fixture calls `pytest.fail`). This confirms the fast-fail guard works.

- [ ] **Step 7: Commit**

```bash
git add scripts/validate-zeroshot/test_zeroshot_skill.py
git commit -m "test: add zeroshot skill integration test and helper unit tests"
```

---

## Running the full integration test

```bash
export ANTHROPIC_BASE_URL=http://jonathans-mac-studio:1234
export ANTHROPIC_AUTH_TOKEN=lmstudio
# optional: export HERMES_IMAGE=ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev
# optional: export ZEROSHOT_TIMEOUT=1800
pytest scripts/validate-zeroshot/ -v
```

For OpenRouter:
```bash
export ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1
export ANTHROPIC_AUTH_TOKEN=<your-openrouter-key>
export OPENCODE_CONFIG_PATH=scripts/validate-zeroshot/opencode-openrouter.json
pytest scripts/validate-zeroshot/ -v
```

Unit tests only (no Docker, no env vars required):
```bash
pytest scripts/validate-zeroshot/ -k "not zeroshot_fixes" -v
```
