#!/usr/bin/env python3
"""Manifest contract-test plan builder (Task 1: pure logic, dry-run).

Parses Flux HelmRelease manifests, helm-renders the pinned chart, and builds a
docker replay plan for each manifest's pod.  With --dry-run the plans are
printed as JSON and no docker is invoked; executing the plans lands in Task 2.

Exit codes: 0 all pass, 1 any failure, 2 usage/setup error (missing helm,
render failure, ...).
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import yaml


@dataclass
class ContainerRun:
    """Docker replay recipe for one pod container."""

    name: str
    image: str
    entrypoint: str | None
    argv: list[str]
    env: list[tuple[str, str]]
    mounts: list[tuple[str, str, bool]]  # (volume_name, mount_path, read_only)
    user: str | None
    read_only: bool
    ports: list[int]
    is_init: bool


def load_manifest(path: str) -> dict:
    """Parse one HelmRelease doc from a manifest file."""
    with open(path) as fh:
        docs = [d for d in yaml.safe_load_all(fh) if d]
    for d in docs:
        if d.get("kind") == "HelmRelease":
            return d
    if not docs:
        raise ValueError(f"no YAML documents in {path}")
    return docs[0]


def extract_values(helmrelease: dict) -> str:
    """Return the yaml.safe_dump of spec.values."""
    values = (helmrelease.get("spec") or {}).get("values") or {}
    return yaml.safe_dump(values, sort_keys=False)


def chart_commit(repo_root: str) -> str:
    """Find the GitRepository named `hermes-agent` under flux/cluster/*.yaml.

    Returns its spec.ref.commit (the pinned chart commit).
    """
    for fname in sorted(glob.glob(os.path.join(repo_root, "flux", "cluster", "*.yaml"))):
        with open(fname) as fh:
            for doc in yaml.safe_load_all(fh):
                if (
                    doc
                    and doc.get("kind") == "GitRepository"
                    and (doc.get("metadata") or {}).get("name") == "hermes-agent"
                ):
                    return doc["spec"]["ref"]["commit"]
    raise RuntimeError("no GitRepository named 'hermes-agent' under flux/cluster/*.yaml")


def render_podspec(
    chart_dir: str, values_text: str, release: str, namespace: str
) -> tuple[dict, dict[str, dict[str, str]]]:
    """helm-template the chart; return (Deployment pod template spec, configmaps).

    Configmaps are returned as {name: {key: value}}.  On a non-zero helm exit,
    raise a RuntimeError whose message includes helm's stderr verbatim.
    """
    helm = shutil.which("helm")
    if helm is None:
        raise RuntimeError("helm binary not found on PATH; cannot render chart")
    fd, values_path = tempfile.mkstemp(suffix=".yaml", prefix="contract-values-")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(values_text)
        proc = subprocess.run(
            [helm, "template", release, chart_dir, "-f", values_path, "-n", namespace],
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(values_path)
    if proc.returncode != 0:
        raise RuntimeError(
            f"helm template failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    docs = [d for d in yaml.safe_load_all(proc.stdout) if d]
    deployments = [d for d in docs if d.get("kind") == "Deployment"]
    if len(deployments) != 1:
        raise RuntimeError(
            f"expected exactly one Deployment in rendered output, found {len(deployments)}"
        )
    pod = deployments[0]["spec"]["template"]["spec"]
    configmaps = {
        d["metadata"]["name"]: (d.get("data") or {})
        for d in docs
        if d.get("kind") == "ConfigMap"
    }
    return pod, configmaps


def resolve_env(entry: dict, rendered_cms: dict) -> tuple[str, str]:
    """Resolve one env entry to a (name, value) pair for docker replay.

    Literal values pass through; secretKeyRef values are replaced by
    ci-dummy-<NAME> placeholders; configMapKeyRef values are looked up in
    rendered_cms (raising if the configmap or key is absent).
    """
    name = entry.get("name", "")
    if "value" in entry:
        value = entry["value"]
        return name, (value if value is not None else "")
    value_from = entry.get("valueFrom") or {}
    if "secretKeyRef" in value_from:
        return name, f"ci-dummy-{name}"
    if "configMapKeyRef" in value_from:
        ref = value_from["configMapKeyRef"]
        cm_name, cm_key = ref["name"], ref["key"]
        cm = rendered_cms.get(cm_name)
        if cm is None or cm_key not in cm:
            raise RuntimeError(
                f"env {name}: configMapKeyRef {cm_name}/{cm_key} not found in rendered configmaps"
            )
        return name, str(cm[cm_key])
    return name, ""  # fieldRef / resourceFieldRef: not replayable, leave empty


def _image_repo(image: str) -> str:
    """Repository portion of an image reference (digest and tag stripped)."""
    base = image.split("@", 1)[0]
    if ":" in base.rsplit("/", 1)[-1]:
        base = base.rsplit(":", 1)[0]
    return base


def _resolve_user(container: dict, pod: dict) -> str | None:
    """Container securityContext runAsUser/runAsGroup, else pod-level fallback."""
    csc = container.get("securityContext") or {}
    psc = pod.get("securityContext") or {}
    uid = csc.get("runAsUser", psc.get("runAsUser"))
    gid = csc.get("runAsGroup", psc.get("runAsGroup"))
    if uid is None and gid is None:
        return None
    if uid is None:
        return f"0:{gid}"
    if gid is None:
        return str(uid)
    return f"{uid}:{gid}"


def _to_run(container: dict, pod: dict, is_init: bool) -> ContainerRun:
    command = container.get("command")
    args = container.get("args") or []
    if command:
        entrypoint, argv = command[0], list(command[1:]) + list(args)
    else:
        entrypoint, argv = None, list(args)
    sc = container.get("securityContext") or {}
    return ContainerRun(
        name=container["name"],
        image=container["image"],
        entrypoint=entrypoint,
        argv=argv,
        env=[resolve_env(e, {}) for e in container.get("env") or []],
        mounts=[
            (m["name"], m["mountPath"], bool(m.get("readOnly", False)))
            for m in container.get("volumeMounts") or []
        ],
        user=_resolve_user(container, pod),
        read_only=bool(sc.get("readOnlyRootFilesystem", False)),
        ports=[
            p["containerPort"]
            for p in container.get("ports") or []
            if p.get("containerPort") is not None
        ],
        is_init=is_init,
    )


def build_plan(pod_spec: dict, image_under_test: str) -> tuple[list[ContainerRun], list[str]]:
    """Build docker replay runs from a rendered pod spec.

    Init containers come first in rendered order, then main containers in
    rendered order.  Containers whose image repository differs from
    image_under_test's repository are skipped: their names are returned in the
    second list.
    """
    target_repo = _image_repo(image_under_test)
    runs: list[ContainerRun] = []
    skipped: list[str] = []
    for section, is_init in (("initContainers", True), ("containers", False)):
        for c in pod_spec.get(section) or []:
            if _image_repo(c.get("image", "")) != target_repo:
                skipped.append(c["name"])
                continue
            runs.append(_to_run(c, pod_spec, is_init))
    return runs, skipped


_CONTRACT_FAILURE_MARKERS = (
    "Traceback (most recent call last)",
    "No module named",
    "ModuleNotFoundError",
    "ImportError",
    "cannot import name",
    "unrecognized arguments",
    "error: argument",
    "usage:",
)


def is_contract_failure(logs: str) -> bool:
    """True if container logs show a Python import/CLI contract break."""
    return any(marker in logs for marker in _CONTRACT_FAILURE_MARKERS)


def parse_base_image(dockerfile: str) -> str:
    """Return the image from the last FROM line of a Dockerfile."""
    base = None
    with open(dockerfile) as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if parts[0].lower() == "from":
                tokens = [t for t in parts[1:] if not t.startswith("--")]
                if tokens:
                    base = tokens[0]
    if base is None:
        raise ValueError(f"no FROM line found in {dockerfile}")
    return base


def _plan_for_manifest(manifest: str, chart_dir: str, image: str) -> dict:
    helmrelease = load_manifest(manifest)
    values = extract_values(helmrelease)
    spec = helmrelease.get("spec") or {}
    release = spec.get("releaseName") or (helmrelease.get("metadata") or {}).get("name")
    namespace = (
        (helmrelease.get("metadata") or {}).get("namespace")
        or spec.get("targetNamespace")
        or "default"
    )
    pod, _configmaps = render_podspec(chart_dir, values, release, namespace)
    runs, skipped = build_plan(pod, image)
    return {
        "manifest": manifest,
        "release": release,
        "namespace": namespace,
        "skipped": skipped,
        "runs": [dataclasses.asdict(r) for r in runs],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="manifest-contract-test",
        description=(
            "HelmRelease manifest contract test: render the pod against the "
            "pinned chart and replay its containers in docker against a "
            "candidate image."
        ),
    )
    ap.add_argument("--image", required=True, help="candidate image reference under test")
    ap.add_argument(
        "--base-image",
        default=None,
        help="base image reference (default: parsed from the Dockerfile in the repo root)",
    )
    ap.add_argument("--manifests", nargs="+", required=True, help="HelmRelease manifest path(s)")
    ap.add_argument("--chart-dir", required=True, help="path to the chart at the pinned commit")
    ap.add_argument("--dry-run", action="store_true", help="render + build plans, print JSON, exit 0 (no docker)")
    ap.add_argument("--survive", type=int, default=45, help="seconds a container must keep running to count as pass")
    ap.add_argument("--init-timeout", type=int, default=300, help="max seconds per init container")
    ap.add_argument("--parallel", type=int, default=3, help="manifest-level parallelism")
    ap.add_argument("--log-dir", default="/tmp/contract-logs", help="directory for per-container logs")
    args = ap.parse_args(argv)

    if args.base_image is None:
        dockerfile = os.path.join(os.getcwd(), "Dockerfile")
        try:
            args.base_image = parse_base_image(dockerfile)
        except (OSError, ValueError) as e:
            print(f"error: cannot determine base image: {e}", file=sys.stderr)
            return 2

    if shutil.which("helm") is None:
        print("error: helm not found on PATH", file=sys.stderr)
        return 2

    if not args.dry_run:
        # Task 2 replaces this stub with the real docker execution path.
        print("execution not implemented yet (Task 2)", file=sys.stderr)
        return 2

    for manifest in args.manifests:
        try:
            plan = _plan_for_manifest(manifest, args.chart_dir, args.image)
        except (OSError, ValueError, RuntimeError, yaml.YAMLError) as e:
            print(f"error: {manifest}: {e}", file=sys.stderr)
            return 2
        print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())