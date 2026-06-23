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
ANTHROPIC_AUTH_TOKEN = _dotenv("ANTHROPIC_AUTH_TOKEN")
ANTHROPIC_BASE_URL = _dotenv("ANTHROPIC_BASE_URL")

# Minimal hermes config.yaml: sets provider to custom so hermes routes to LM Studio
# instead of trying to auto-detect an OpenRouter/Anthropic key.
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

    # chmod 777 so hermes uid 10000 can read and write everything
    data_dir.chmod(0o777)
    for p in data_dir.rglob("*"):
        p.chmod(0o777)

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
    return {
        "base_url": ANTHROPIC_BASE_URL,
        "auth_token": ANTHROPIC_AUTH_TOKEN,
        "opencode_config_path": os.environ.get("OPENCODE_CONFIG_PATH"),
        # --add-host entry for the LM Studio host (mDNS names don't resolve in Docker on macOS)
        "lmstudio_add_host": _resolve_add_host(LMSTUDIO_BASE_URL),
    }
