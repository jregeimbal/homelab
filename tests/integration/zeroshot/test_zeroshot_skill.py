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


def _dir_tree(root: Path, max_depth: int = 4) -> str:
    """Return a compact directory listing for failure messages."""
    lines = []
    for p in sorted(root.rglob("*")):
        try:
            depth = len(p.relative_to(root).parts)
        except ValueError:
            continue
        if depth > max_depth:
            continue
        indent = "  " * (depth - 1)
        name = p.name + ("/" if p.is_dir() else "")
        try:
            size = f"  ({p.stat().st_size}B)" if p.is_file() else ""
        except OSError:
            size = "  (unreadable)"
        lines.append(f"{indent}{name}{size}")
    return "\n".join(lines) if lines else "(empty)"


def _run_zeroshot(provider: str, tmp_repo, hermes_image, docker_env) -> tuple[str, int]:
    """Build and run the docker command. Returns (combined stdout+stderr, exit_code)."""
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
        # ANTHROPIC_API_KEY is the standard env var for the Anthropic SDK.
        # Do NOT also set ANTHROPIC_AUTH_TOKEN: that is a bearer-token auth path
        # (Authorization: Bearer ...) which the Anthropic API rejects for API keys.
        cmd += ["-e", f"ANTHROPIC_API_KEY={docker_env['auth_token']}"]
    if docker_env["opencode_config_path"]:
        # Override the pre-seeded opencode.json with a custom provider config
        cmd += [
            "-v",
            f"{docker_env['opencode_config_path']}:/opt/data/home/.config/opencode/opencode.json:ro",
        ]
    cmd += [hermes_image, "hermes", "-z", _make_prompt(provider), "--accept-hooks", "--yolo"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=ZEROSHOT_TIMEOUT)
    output = result.stdout + result.stderr

    # Hermes stage2 init does `chown -R 10000 /opt/data` inside the container.
    # On Linux with native Docker, that changes host-side ownership too, making all
    # output files unreadable by the test runner. `sudo -n` is passwordless on GitHub
    # Actions; it fails immediately (and silently via check=False) on macOS.
    subprocess.run(
        ["sudo", "-n", "chmod", "-R", "a+rX", str(tmp_repo)],
        capture_output=True, check=False,
    )

    return output, result.returncode


def _find_implemented(data_dir: Path, expected_stmts: list) -> Path | None:
    """Return the first calculator.py under data_dir that has the expected implementation.

    Zeroshot applies changes to a git worktree, which may be anywhere under data_dir
    rather than the main working tree.  Searching recursively handles both cases.
    """
    for candidate in data_dir.rglob("calculator.py"):
        try:
            actual = _function_body_stmts(candidate.read_text(), "add_numbers")
            if actual == expected_stmts:
                return candidate
        except (PermissionError, OSError, ValueError, SyntaxError):
            continue
    return None


def _assert_results(output: str, exit_code: int, data_dir: Path):
    """Shared assertions for both provider tests."""
    tree = _dir_tree(data_dir)
    context = (
        f"--- EXIT CODE ---\n{exit_code}\n"
        f"--- DIRECTORY TREE ---\n{tree}\n"
        f"--- OUTPUT (last 60 lines) ---\n"
        + "\n".join(output.splitlines()[-60:])
    )

    # Layer 1: docker itself ran and hermes didn't crash on startup
    assert exit_code == 0, f"docker run exited {exit_code} — container crash or timeout.\n{context}"

    # Layer 2: hermes outer agent invoked zeroshot and it didn't explicitly reject
    assert "REJECTED" not in output, f"Zeroshot REJECTED the implementation.\n{context}"
    assert "VERIFIED" in output, f"Expected VERIFIED in hermes output.\n{context}"

    # Layer 3: the implementation is present somewhere in the data dir
    # (main working tree or isolated zeroshot worktree — either counts)
    expected = _function_body_stmts(EXPECTED_CALCULATOR.read_text(), "add_numbers")
    implemented = _find_implemented(data_dir, expected)
    assert implemented is not None, (
        f"No calculator.py with the correct implementation found under {data_dir}.\n{context}"
    )


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_zeroshot_fixes_calculator(provider, tmp_repo, hermes_image, docker_env):
    output, exit_code = _run_zeroshot(provider, tmp_repo, hermes_image, docker_env)
    _assert_results(output, exit_code, tmp_repo)
