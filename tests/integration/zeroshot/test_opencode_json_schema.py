"""
Integration test: opencode JSON schema compliance with local Qwen model.

Reproduces the failure observed in cluster spinning-cosmos-71 where the
validator agent (opencode + Qwen3.6-35B-A3B via LM Studio) produced output
that was accepted as "completed" but was missing all three required JSON
fields, causing zeroshot to reject the validation with:

  Agent validator output failed JSON schema validation:
    #/required must have required property 'approved'
    #/required must have required property 'summary'
    #/required must have required property 'errors'

Root cause: the model parsed the validator prompt correctly but after running
bash commands to verify the code, it produced output without the required JSON
structure. zeroshot then exhausted all 3 retry attempts and crashed the
validator, rejecting the entire cluster.

This test runs opencode directly (bypassing hermes and the full zeroshot
cluster) with a prompt that requires command execution followed by JSON output,
matching the real validator workload. It exercises all 3 attempts that zeroshot
would make, asserting every attempt produces a JSON object with the required
fields and correct types.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

import conftest as _conf

OPENCODE_TIMEOUT = 120

# Number of times zeroshot retries a failed validator task.
# The test runs the same number of attempts so a single lucky pass does not
# mask an intermittent failure.
_VALIDATOR_ATTEMPTS = 3

# Validator prompt representative of what zeroshot sends.
# Crucially it requires the model to RUN BASH COMMANDS first (the step that
# caused distraction in spinning-cosmos-71) before outputting JSON.
_VALIDATOR_PROMPT = """\
## \U0001f6ab YOU ARE A VALIDATOR - READ-ONLY MODE

Your ONLY job is to VALIDATE and OUTPUT JSON. Do NOT edit files.

Issue #12 fix: `import sys` was removed from inside a for-loop and all
`sys.stdout.write()` calls replaced with `console.print()`.

## WORKFLOW

1. Run this command and capture output:
   ```bash
   grep -n "import sys" /opt/data/home/.config/opencode/opencode.json 2>&1 || echo "NOT FOUND"
   ```
2. Run this command:
   ```bash
   echo "validation complete"
   ```
3. Based on the results, output your verdict as JSON.

## \U0001f534 OUTPUT FORMAT (CRITICAL)

After running the commands above, you MUST respond with ONLY this JSON
(no preamble, no explanation outside the JSON block):

```json
{
  "approved": true,
  "summary": "one-line verdict under 100 chars",
  "errors": []
}
```

Set approved:true if the grep confirms no sys.stdout.write remains.
Set approved:false and populate errors[] if problems were found.
"""

# Required fields and their types (from quick-validation.json schema)
_REQUIRED_FIELDS: dict[str, type] = {
    "approved": bool,
    "summary": str,
    "errors": list,
}


def _run_opencode_direct(
    prompt: str, data_dir: Path, hermes_image: str, docker_env: dict
) -> tuple[str, int]:
    """Run opencode directly inside the hermes image (no hermes orchestration).

    Uses --format json so the output format matches what zeroshot uses in
    production. HOME is set so opencode finds the config seeded by
    _seed_hermes_data_dir.
    """
    cmd = ["docker", "run", "--rm", "--network", "host"]
    if docker_env.get("lmstudio_add_host"):
        cmd += ["--add-host", docker_env["lmstudio_add_host"]]

    cmd += [
        "-v", f"{data_dir}:/opt/data",
        "-e", "HOME=/opt/data/home",
        "-e", "OPENCODE_TELEMETRY_DISABLED=1",
    ]

    if docker_env.get("opencode_config_path"):
        cmd += [
            "-v",
            f"{docker_env['opencode_config_path']}:/opt/data/home/.config/opencode/opencode.json:ro",
        ]

    # --format json produces NDJSON events so text can be reliably extracted.
    # --dir keeps opencode anchored to /opt/data (not the gitdir-resolved main repo).
    cmd += [
        hermes_image,
        "opencode", "run", "--format", "json", "--dir", "/opt/data",
        prompt,
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=OPENCODE_TIMEOUT
    )
    subprocess.run(
        ["sudo", "-n", "chmod", "-R", "a+rX", str(data_dir)],
        capture_output=True,
        check=False,
    )
    return result.stdout + result.stderr, result.returncode


def _extract_text_from_ndjson(raw: str) -> str:
    """Collect all LLM text parts from opencode's --format json (NDJSON) output."""
    parts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # opencode may prefix lines with a timestamp bracket: [1234567890]{...}
        brace = line.find("{")
        if brace > 0:
            line = line[brace:]
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "text":
            text = obj.get("part", {}).get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _extract_json_object(text: str) -> dict | None:
    """Return the first JSON object found in text, checking code fences first."""
    # 1. JSON inside a ```json ... ``` block (typical Qwen output style)
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 2. Bare JSON object anywhere in the text (fallback)
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _assert_valid_validator_json(parsed: dict | None, attempt: int, context: str) -> None:
    assert parsed is not None, (
        f"Attempt {attempt}/{_VALIDATOR_ATTEMPTS}: no valid JSON object in opencode output.\n"
        "The model must respond with a JSON object containing approved/summary/errors.\n"
        + context
    )
    for field, expected_type in _REQUIRED_FIELDS.items():
        assert field in parsed, (
            f"Attempt {attempt}/{_VALIDATOR_ATTEMPTS}: "
            f"missing required field '{field}' in validator JSON.\n"
            f"Got fields: {list(parsed.keys())}\n" + context
        )
        assert isinstance(parsed[field], expected_type), (
            f"Attempt {attempt}/{_VALIDATOR_ATTEMPTS}: "
            f"field '{field}' must be {expected_type.__name__}, "
            f"got {type(parsed[field]).__name__}: {parsed[field]!r}\n" + context
        )


@pytest.mark.skipif(
    _conf.IS_CI,
    reason="opencode requires LM Studio which is not available in CI",
)
def test_opencode_validator_produces_required_json_fields(
    tmp_path, hermes_image, docker_env
):
    """opencode + Qwen must produce JSON with approved/summary/errors on every
    attempt when given a validator-style prompt that includes bash commands.

    Reproduces spinning-cosmos-71: after running bash commands the model got
    distracted and omitted the required JSON fields. zeroshot exhausted all
    3 retry attempts:

      Agent validator output failed JSON schema validation:
        #/required must have required property 'approved'
        #/required must have required property 'summary'
        #/required must have required property 'errors'

    The test mirrors zeroshot's retry count (_VALIDATOR_ATTEMPTS = 3) so a
    single lucky pass cannot mask an intermittent failure.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _conf._seed_hermes_data_dir(data_dir)
    _conf._chmod_for_hermes(data_dir)

    for attempt in range(1, _VALIDATOR_ATTEMPTS + 1):
        raw_output, _exit_code = _run_opencode_direct(
            _VALIDATOR_PROMPT, data_dir, hermes_image, docker_env
        )

        llm_text = _extract_text_from_ndjson(raw_output)
        searchable = llm_text or raw_output

        parsed = _extract_json_object(searchable)

        tail = "\n".join((llm_text or raw_output).splitlines()[-40:])
        context = f"--- attempt {attempt} output (last 40 lines) ---\n{tail}"

        _assert_valid_validator_json(parsed, attempt, context)
