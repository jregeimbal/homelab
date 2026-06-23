import ast
import os
import subprocess
from pathlib import Path

import pytest

import conftest as _conf

FIXTURE_DIR = Path(__file__).parent / "fixture"
EXPECTED_CALCULATOR = FIXTURE_DIR / "expected" / "calculator.py"
ZEROSHOT_TIMEOUT = int(os.environ.get("ZEROSHOT_TIMEOUT", "1800"))


def _make_prompt(provider: str) -> str:
    return (
        "There is a Python project at /opt/data/validation-repo. "
        "The function add_numbers in calculator.py is not yet implemented (TODO stub) "
        "and test_calculator.py is currently failing. Please use zeroshot to implement it. "
        f'Run: zeroshot run "implement add_numbers in calculator.py so that '
        f'test_calculator.py passes" --provider {provider} '
        "(this is a local repo with no GitHub remote — do not use --pr). "
        "Poll zeroshot status until the cluster finishes. "
        "End your response with exactly one of these lines: 'Outcome: VERIFIED' or 'Outcome: REJECTED'."
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


# --- Integration tests ---

_PROVIDERS = [
    pytest.param(
        "opencode",
        id="opencode",
        marks=pytest.mark.skipif(
            _conf.IS_CI,
            reason="opencode requires LM Studio which is not available in CI",
        ),
    ),
    pytest.param(
        "claude",
        id="claude",
        marks=pytest.mark.skipif(
            not _conf.ANTHROPIC_API_KEY,
            reason="ANTHROPIC_API_KEY not set (add to .env or environment)",
        ),
    ),
]


def _run_zeroshot(provider: str, tmp_repo, hermes_image, docker_env) -> tuple[str, Path]:
    """Build and run the docker command. Returns (output, changed_file_path)."""
    cmd = ["docker", "run", "--rm", "--network", "host"]
    if docker_env["lmstudio_add_host"]:
        cmd += ["--add-host", docker_env["lmstudio_add_host"]]
    cmd += [
        "-v", f"{tmp_repo}:/opt/data",
        "-e", "HERMES_HOME=/opt/data",
        "-e", "OPENCODE_TELEMETRY_DISABLED=1",
    ]
    if docker_env["base_url"]:
        cmd += ["-e", f"ANTHROPIC_BASE_URL={docker_env['base_url']}"]
    if docker_env["auth_token"]:
        # ANTHROPIC_AUTH_TOKEN: read by claude-code sub-agents (zeroshot --provider claude)
        # ANTHROPIC_API_KEY:    read by hermes outer agent when provider: anthropic in config.yaml
        cmd += [
            "-e", f"ANTHROPIC_AUTH_TOKEN={docker_env['auth_token']}",
            "-e", f"ANTHROPIC_API_KEY={docker_env['auth_token']}",
        ]
    if docker_env["opencode_config_path"]:
        # Override the pre-seeded opencode.json with a custom provider config
        cmd += [
            "-v",
            f"{docker_env['opencode_config_path']}:/opt/data/home/.config/opencode/opencode.json:ro",
        ]
    cmd += [hermes_image, "hermes", "-z", _make_prompt(provider), "--accept-hooks", "--yolo"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=ZEROSHOT_TIMEOUT)
    output = result.stdout + result.stderr
    changed = tmp_repo / "validation-repo" / "calculator.py"
    return output, changed


def _assert_results(output: str, changed: Path):
    """Shared assertions for both provider tests."""
    # Primary: the file was actually fixed (most reliable evidence that zeroshot ran)
    assert changed.exists(), f"calculator.py missing at {changed}\n--- OUTPUT ---\n{output}"
    actual = _function_body_stmts(changed.read_text(), "add_numbers")
    expected = _function_body_stmts(EXPECTED_CALCULATOR.read_text(), "add_numbers")
    assert actual == expected, (
        f"Implementation does not match expected.\n"
        f"Actual:\n{changed.read_text()}\n"
        f"Expected:\n{EXPECTED_CALCULATOR.read_text()}\n"
        f"--- OUTPUT ---\n{output}"
    )

    # Secondary: hermes reported success (prompt asks for explicit VERIFIED/REJECTED)
    assert "REJECTED" not in output, (
        f"Zeroshot REJECTED the implementation.\n--- OUTPUT ---\n{output}"
    )
    assert "VERIFIED" in output, (
        f"Expected VERIFIED in hermes output.\n--- OUTPUT ---\n{output}"
    )
    assert "add_numbers" in output, (
        f"Expected mention of add_numbers in hermes summary.\n--- OUTPUT ---\n{output}"
    )


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_zeroshot_fixes_calculator(provider, tmp_repo, hermes_image, docker_env):
    output, changed = _run_zeroshot(provider, tmp_repo, hermes_image, docker_env)
    _assert_results(output, changed)
