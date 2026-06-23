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
        "-e", "OPENCODE_TELEMETRY_DISABLED=1",
    ]
    if docker_env["base_url"]:
        cmd += ["-e", f"ANTHROPIC_BASE_URL={docker_env['base_url']}"]
    if docker_env["auth_token"]:
        cmd += ["-e", f"ANTHROPIC_AUTH_TOKEN={docker_env['auth_token']}"]
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
