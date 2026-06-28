import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

collect_ignore_glob = ["fixture/*.py"]

FIXTURE_DIR = Path(__file__).parent / "fixture"
DEFAULT_IMAGE = "ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:local-dev"
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://jonathans-mac-studio:1234/v1")
LMSTUDIO_MODEL = os.environ.get("LMSTUDIO_MODEL", "google/gemma-4-26b-a4b")

# GitHub Actions (and other standard CI environments) set CI=true.
# In CI: hermes uses Anthropic API; opencode provider is skipped (no LM Studio).
IS_CI = os.environ.get("CI") == "true"
HERMES_CI_MODEL = os.environ.get("HERMES_MODEL", "claude-sonnet-4-6")


def _dotenv(key: str) -> str | None:
    """Read a value from the environment, falling back to the repo-root .env file."""
    val = os.environ.get(key)
    if val:
        return val
    env_file = Path(__file__).parents[3] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    return None


# Read auth vars once at import time so skip marks can reference them
ANTHROPIC_API_KEY = _dotenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = _dotenv("ANTHROPIC_BASE_URL")

# Hermes config.yaml seeded into tmp_repo so the container doesn't need interactive setup.
# CI: use Anthropic API (ANTHROPIC_API_KEY from env, no ANTHROPIC_BASE_URL redirect).
# Local dev: use LM Studio via custom OpenAI-compatible endpoint.
if IS_CI:
    _HERMES_CONFIG = f"""\
model:
  default: {HERMES_CI_MODEL}
  provider: anthropic
providers: {{}}
_config_version: 30
"""
else:
    _HERMES_CONFIG = f"""\
model:
  default: {LMSTUDIO_MODEL}
  provider: custom
  base_url: {LMSTUDIO_BASE_URL}
providers: {{}}
_config_version: 30
"""

# opencode.json used by zeroshot --provider opencode
_OPENCODE_CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "model": f"lmstudio/{LMSTUDIO_MODEL}",
    "provider": {
        "lmstudio": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LM Studio (mac-studio)",
            "options": {"baseURL": LMSTUDIO_BASE_URL},
            "models": {LMSTUDIO_MODEL: {"name": LMSTUDIO_MODEL}},
        }
    },
    "plugin": ["superpowers@git+https://github.com/obra/superpowers.git"],
}


def _resolve_add_host(base_url: str) -> str | None:
    """Return hostname:ip for --add-host if the hostname needs help resolving inside Docker."""
    try:
        hostname = urlparse(base_url).hostname
        if not hostname or hostname in ("localhost", "127.0.0.1", "::1"):
            return None
        ip = socket.gethostbyname(hostname)
        if ip.startswith("127."):
            return None
        return f"{hostname}:{ip}"
    except OSError:
        return None


_GIT_ID = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _seed_hermes_data_dir(data_dir: Path) -> None:
    """Write hermes config files into data_dir (mounted as /opt/data in container).

    Mirrors what the k8s init containers copy from /opt/config-defaults/ — needed
    because plain `docker run` skips the init-container setup phase.
    """
    (data_dir / "config.yaml").write_text(_HERMES_CONFIG)

    # opencode config for zeroshot --provider opencode
    opencode_dir = data_dir / "home" / ".config" / "opencode"
    opencode_dir.mkdir(parents=True)
    (opencode_dir / "opencode.json").write_text(json.dumps(_OPENCODE_CONFIG, indent=2))

    # ~/.claude/settings.json so claude-code sub-agents can authenticate.
    # Hermes sets HOME=$HERMES_HOME/home for terminal subprocesses, so ~/.claude/
    # resolves to data_dir/home/.claude/.
    # Hermes's env passthrough blocklist strips ANTHROPIC_API_KEY from subprocess
    # envs (security feature). The settings.json "env" key bypasses this — file-based.
    if ANTHROPIC_API_KEY:
        claude_dir = data_dir / "home" / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text(
            json.dumps({"env": {"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY}})
        )


def _chmod_for_hermes(data_dir: Path) -> None:
    """Make data_dir world-writable so hermes (uid 10000) can write inside it.

    Hermes stage2 init does `chown -R 10000 /opt/data` inside the container; on
    Linux with native Docker that changes host-side ownership too, so we need
    wide-open permissions up front.
    """
    data_dir.chmod(0o777)
    for p in data_dir.rglob("*"):
        p.chmod(0o777)


@pytest.fixture
def tmp_repo(tmp_path):
    data_dir = tmp_path / "data"
    repo_dir = data_dir / "validation-repo"
    shutil.copytree(
        FIXTURE_DIR,
        repo_dir,
        ignore=shutil.ignore_patterns("expected", "__pycache__", ".pytest_cache", "*.pyc"),
    )

    _seed_hermes_data_dir(data_dir)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git"] + _GIT_ID + ["commit", "-m", "initial"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    _chmod_for_hermes(data_dir)
    return data_dir


@pytest.fixture
def tmp_tracking_repo(tmp_path):
    """Data dir pre-loaded with a bare remote.git and a local target-repo clone.

    Layout inside the container (/opt/data → data_dir):
      /opt/data/remote.git   — bare remote, default branch 'develop'
      /opt/data/target-repo  — clone of remote, tracking origin/develop,
                               one commit BEHIND (update.txt not yet pulled)

    The remote has no 'main' branch, so:
      git pull --rebase origin main  → fails ("couldn't find remote ref main")
      git pull --rebase              → succeeds (uses tracking-branch config)

    Verifying that update.txt appears in target-repo after hermes runs step 2
    proves the correct command was used.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed_hermes_data_dir(data_dir)

    # Bare remote (container path: /opt/data/remote.git)
    remote = data_dir / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    # Populate remote with an initial commit on 'develop'
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(remote), str(work)], check=True, capture_output=True)
    subprocess.run(["git"] + _GIT_ID + ["checkout", "-b", "develop"],
                   cwd=work, check=True, capture_output=True)
    (work / "README.md").write_text("initial")
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git"] + _GIT_ID + ["commit", "-m", "initial"],
                   cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "develop"],
                   cwd=work, check=True, capture_output=True)

    # Clone into target-repo from the host path, then repoint origin to the
    # container path so git pull --rebase inside the container resolves correctly.
    target = data_dir / "target-repo"
    subprocess.run(
        ["git", "clone", "--branch", "develop", str(remote), str(target)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "set-url", "origin", "file:///opt/data/remote.git"],
        cwd=target, check=True, capture_output=True,
    )

    # Push a new commit to remote that target-repo hasn't fetched yet
    (work / "update.txt").write_text("added by remote after initial clone")
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git"] + _GIT_ID + ["commit", "-m", "add update.txt"],
                   cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "push"], cwd=work, check=True, capture_output=True)

    _chmod_for_hermes(data_dir)
    return data_dir


@pytest.fixture
def hermes_image():
    return os.environ.get("HERMES_IMAGE", DEFAULT_IMAGE)


@pytest.fixture
def docker_env():
    return {
        "base_url": ANTHROPIC_BASE_URL,
        "auth_token": ANTHROPIC_API_KEY,
        "opencode_config_path": os.environ.get("OPENCODE_CONFIG_PATH"),
        # --add-host entry for the LM Studio host (mDNS names don't resolve in Docker on macOS)
        "lmstudio_add_host": _resolve_add_host(LMSTUDIO_BASE_URL),
    }
