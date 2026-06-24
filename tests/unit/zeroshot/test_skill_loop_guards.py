"""
Unit tests for SKILL.md loop-guard content.

These replicate the failure modes observed in a real hermes session where the
agent:
  1. Called `git pull --rebase` 25+ times after it already succeeded
  2. Launched 5 separate zeroshot clusters instead of one
  3. Polled `zeroshot status` in a tight loop with no sleep
  4. Never checked the setup log when the cluster was stuck in setup
"""
import re
from pathlib import Path

SKILL_PATH = (
    Path(__file__).parents[3]
    / "assets" / "hermes-skills" / "autonomous-ai-agents" / "zeroshot" / "SKILL.md"
)


def _skill() -> str:
    return SKILL_PATH.read_text()


def test_skill_instructs_git_pull_exactly_once():
    """Step 2 must tell the agent to run git pull exactly once and move on."""
    assert re.search(r"exactly once", _skill()), (
        "SKILL.md step 2 must say 'exactly once' after git pull so the agent "
        "does not loop on a successful pull."
    )


def test_skill_instructs_zeroshot_list_before_launch():
    """Step 3 must instruct checking `zeroshot list` before launching."""
    assert re.search(r"zeroshot list", _skill()), (
        "SKILL.md step 3 must tell the agent to run 'zeroshot list' before "
        "launching, so it doesn't create duplicate clusters."
    )


def test_skill_warns_against_multiple_launches():
    """Pitfall section must warn against launching multiple clusters."""
    skill = _skill()
    assert re.search(r"[Ll]aunching multiple clusters|multiple clusters", skill), (
        "SKILL.md pitfalls must warn about launching multiple zeroshot clusters."
    )


def test_skill_polling_loop_includes_sleep():
    """The status-polling loop must include `sleep 60`."""
    assert re.search(r"sleep 60", _skill()), (
        "SKILL.md step 4 polling loop must include 'sleep 60' between checks."
    )


def test_skill_warns_against_tight_polling():
    """Pitfall section must warn against tight status polling."""
    assert re.search(r"[Tt]ight status polling|rapid.fire|rapid-fire", _skill()), (
        "SKILL.md pitfalls must warn against calling zeroshot status without sleeping."
    )


def test_skill_instructs_setup_log_check_when_stuck():
    """Step 4 must tell the agent to check the setup log if stuck in setup."""
    skill = _skill()
    assert re.search(r"daemon\.log", skill), (
        "SKILL.md step 4 must mention the daemon log path so the agent knows "
        "where to look when a cluster is stuck in setup."
    )
    assert re.search(r"setup.*2 minutes|2 minutes.*setup", skill, re.IGNORECASE), (
        "SKILL.md step 4 must specify a timeout (2 minutes) before giving up on "
        "polling status and checking the setup log instead."
    )


def test_skill_warns_about_setup_stuck_pitfall():
    """Pitfall section must cover cluster stuck in setup state."""
    assert re.search(r"[Ss]tuck in setup|setup.*stuck", _skill()), (
        "SKILL.md pitfalls must warn that a cluster can get stuck in setup and "
        "explain what to do (check the log)."
    )
