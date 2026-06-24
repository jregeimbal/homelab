"""
Tests for SKILL.md step 2: repo navigation (clone vs pull).

Replicates the reported issue where the agent tried 'gh repo clone' on an
already-cloned directory (expected failure), then used the wrong fallback:

    git pull --rebase origin main

instead of the correct:

    git pull --rebase

The explicit 'origin main' fails when the remote's default branch is not
'main' — which is common for repos using 'master', 'trunk', or custom names.
LLMs also tend to substitute the shell expression
'$(git symbolic-ref --short HEAD)' with the literal string 'main'.
"""
import re
from pathlib import Path

SKILL_PATH = (
    Path(__file__).parents[3]
    / "assets"
    / "hermes-skills"
    / "autonomous-ai-agents"
    / "zeroshot"
    / "SKILL.md"
)


# ---------------------------------------------------------------------------
# Skill content tests — these FAIL before the fix, PASS after
# ---------------------------------------------------------------------------

def test_skill_step2_does_not_specify_remote_branch_in_pull():
    """SKILL.md step 2 must not use 'git pull --rebase origin <anything>'.

    The explicit remote+branch form breaks when the remote's default branch is
    not 'main', and LLMs tend to substitute the shell expression
    '$(git symbolic-ref --short HEAD)' with the literal string 'main'.
    The correct form is simply 'git pull --rebase', which honours the
    tracking-branch configuration set up by 'git clone'.
    """
    skill = SKILL_PATH.read_text()
    assert not re.search(r"git pull --rebase origin", skill), (
        "SKILL.md step 2 contains 'git pull --rebase origin <branch>'. "
        "Use 'git pull --rebase' alone so the tracking branch is respected."
    )


def test_skill_step2_has_explicit_directory_check():
    """SKILL.md step 2 must check directory existence before 'gh repo clone'.

    Without an explicit check the agent tries 'gh repo clone' first, which
    always fails when the directory already exists, and then falls back to
    a pull with wrong syntax.
    """
    skill = SKILL_PATH.read_text()
    assert re.search(r"\[ -d .*/opt/data", skill), (
        "SKILL.md step 2 lacks an explicit '[ -d /opt/data/<repo> ]' guard. "
        "Add one so the agent skips 'gh repo clone' when the dir exists."
    )

