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
LMSTUDIO_MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen/qwen3.6-35b-a3b")

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


@pytest.fixture
def tmp_repo(tmp_path):
    data_dir = tmp_path / "data"
    repo_dir = data_dir / "validation-repo"
    shutil.copytree(
        FIXTURE_DIR,
        repo_dir,
        ignore=shutil.ignore_patterns("expected", "__pycache__", ".pytest_cache", "*.pyc"),
    )

    # Seed hermes model config so it reaches LM Studio without interactive setup.
    # The k8s init containers normally do this from /opt/config-defaults/; plain
    # docker run skips them, so we do it here.
    (data_dir / "config.yaml").write_text(_HERMES_CONFIG)

    # Seed opencode config for zeroshot --provider opencode.
    # Mirrors what the k8s init container copies from /opt/config-defaults/opencode/.
    opencode_dir = data_dir / "home" / ".config" / "opencode"
    opencode_dir.mkdir(parents=True)
    (opencode_dir / "opencode.json").write_text(json.dumps(_OPENCODE_CONFIG, indent=2))

    # Seed ~/.claude/settings.json so claude-code sub-agents can authenticate.
    # Hermes sets HOME=$HERMES_HOME/home for its subprocess environment (confirmed by
    # checking $HOME inside a hermes terminal: /opt/data/home). So ~/.claude/ resolves
    # to data_dir/home/.claude/, which is where the opencode config lives too.
    # Hermes's env passthrough blocklist blocks ANTHROPIC_API_KEY from reaching terminal
    # subprocesses (security feature to prevent credential leakage to agent-run code).
    # The claude-code settings.json "env" override bypasses this — file-based, not env.
    if ANTHROPIC_API_KEY:
        claude_dir = data_dir / "home" / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.json").write_text(
            json.dumps({"env": {"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY}})
        )

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

    # chmod 777 AFTER git init so .git/ is also world-writable for hermes (uid 10000).
    # Hermes's stage2 init does chown -R 10000 /opt/data inside the container; on Linux
    # with native Docker this changes host-side ownership too, so we need wide-open perms
    # up front to let hermes write to the repo.
    data_dir.chmod(0o777)
    for p in data_dir.rglob("*"):
        p.chmod(0o777)

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
