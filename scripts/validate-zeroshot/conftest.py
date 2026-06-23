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
    return {
        "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
        "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        "opencode_config_path": os.environ.get("OPENCODE_CONFIG_PATH"),
    }
