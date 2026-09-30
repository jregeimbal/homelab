"""Unit tests for scripts/manifest-contract-test.py (Task 1: plan builder)."""

import os
import re
import shutil

import pytest
import yaml

from scripts import manifest_contract_test as mct  # registered by tests/conftest.py

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")


def test_load_manifest_and_extract_values():
    hr = mct.load_manifest(os.path.join(REPO, "flux/apps/hermes-jon.yaml"))
    vals = yaml.safe_load(mct.extract_values(hr))
    assert set(vals) >= {"image", "config", "env", "extraContainers", "secrets"}
    assert yaml.safe_load(mct.extract_values(hr)) == hr["spec"]["values"]


def test_chart_commit_is_sha():
    assert re.fullmatch(r"[0-9a-f]{40}", mct.chart_commit(REPO))


def test_render_podspec_failure_includes_stderr():
    try:
        mct.render_podspec("/nonexistent-chart-dir", 'image:\n  tag: "x"', "r", "ns")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "helm" in str(e).lower() or "chart" in str(e).lower()


@pytest.mark.skipif(
    shutil.which("helm") is None or not os.environ.get("HERMES_CHART_DIR"),
    reason="needs helm + chart clone",
)
def test_render_podspec_real_chart():
    pod, cms = mct.render_podspec(
        os.environ["HERMES_CHART_DIR"],
        open(FIX + "/rendered-jon-values.yaml").read(),
        "hermes",
        "jon-agent",
    )
    assert [c["name"] for c in pod["containers"]] == [
        "hermes-agent",
        "browserless-chromium",
        "hermes-desktop",
    ]
    assert "config.yaml" in cms["hermes-hermes-agent-config"]


def test_argv_mapping():
    cmd_c = {"name": "d", "command": ["hermes", "dashboard", "--port", "9119"], "image": "img"}
    arg_c = {"name": "m", "args": ["gateway", "run"], "image": "img"}
    plan, _ = mct.build_plan({"containers": [arg_c], "initContainers": [cmd_c], "volumes": []}, "img")
    assert plan[0].entrypoint == "hermes" and plan[0].argv == ["dashboard", "--port", "9119"]
    assert plan[1].entrypoint is None and plan[1].argv == ["gateway", "run"]
    assert plan[0].is_init is True and plan[1].is_init is False


def test_resolve_env():
    cms = {"cm-a": {"app.conf": "x=1"}}
    assert mct.resolve_env({"name": "A", "value": "1"}, cms) == ("A", "1")
    assert mct.resolve_env({"name": "T", "valueFrom": {"secretKeyRef": {"name": "s", "key": "t"}}}, cms) == ("T", "ci-dummy-T")
    assert mct.resolve_env({"name": "C", "valueFrom": {"configMapKeyRef": {"name": "cm-a", "key": "app.conf"}}}, cms) == ("C", "x=1")


def main_user_from(fix, name):
    """Test-local expectation helper: container securityContext, else pod-level."""
    pod = fix["pod"]
    c = next(c for c in pod["containers"] if c["name"] == name)
    sc = c.get("securityContext") or {}
    psc = pod.get("securityContext") or {}
    uid = sc.get("runAsUser", psc.get("runAsUser"))
    gid = sc.get("runAsGroup", psc.get("runAsGroup"))
    if uid is None and gid is None:
        return None
    if gid is None:
        return str(uid)
    return f"{uid}:{gid}"


def test_build_plan_order_and_skip():
    fix = yaml.safe_load(open(FIX + "/rendered-jon-pod.yaml"))
    plan, skipped = mct.build_plan(
        fix["pod"], "ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.9.24-aaaaaaa"
    )
    assert [c.name for c in plan] == [
        "bootstrap-config",
        "copy-hermes-source",
        "bootstrap-home-config",
        "fix-data-ownership",
        "hermes-agent",
        "hermes-desktop",
    ]
    assert skipped == ["browserless-chromium"]
    main = plan[4]
    assert main.argv == ["gateway", "run"] and main.entrypoint is None
    assert ("data", "/opt/data", False) in main.mounts
    desk = plan[5]
    assert desk.entrypoint == "hermes"
    assert desk.argv == ["dashboard", "--host", "0.0.0.0", "--port", "9119", "--insecure", "--no-open"]
    assert ("hermes-agent-source", "/opt/hermes", True) in desk.mounts
    # user: assert against the fixture's actual values (container-level, else pod-level fallback)
    expected_user = main_user_from(fix, "hermes-agent")
    assert main.user == expected_user


def test_is_contract_failure():
    assert mct.is_contract_failure("Traceback (most recent call last)\n  File ...")
    assert mct.is_contract_failure("ModuleNotFoundError: No module named hermes")
    assert mct.is_contract_failure("usage: hermes [-h]\nerror: unrecognized arguments: --insecure")
    assert not mct.is_contract_failure("failed to connect to api.telegram.org: timeout")
    assert not mct.is_contract_failure("")
