#!/usr/bin/env python3
"""Manifest contract-test plan builder + docker execution layer.

Parses Flux HelmRelease manifests, helm-renders the pinned chart, builds a
docker replay plan for each manifest's pod, and (without --dry-run) executes
it: fresh volume fixtures, init containers in order, service containers with
a survival window + loopback port probes, and a `hermes --version`
image-vs-base assertion.  With --dry-run the plans are printed as JSON and no
docker is invoked.

Exit codes: 0 all pass, 1 any failure, 2 usage/setup error (missing helm or
docker, render failure, ...).
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ProcessPoolExecutor
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


# ---------------------------------------------------------------------------
# Task 2: docker execution layer (fixtures, init sequence, survival, probes)
# ---------------------------------------------------------------------------

DEFAULT_INIT_TIMEOUT = 300

# Per-worker log context.  Manifests run in a process pool and each worker
# handles manifests strictly one at a time, so module-level state is safe;
# main() also seeds the log dir in the parent process.
_LOG_DIR: str | None = None
_LOG_MANIFEST: str | None = None

# Version-assertion bookkeeping.  main() runs the check once per invocation in
# the parent and ships the verdict to pool workers via the executor
# initializer; callers without a parent verdict (e.g. tests invoking
# run_manifest directly) fall back to the per-process memo below.
_VERSION_MEMO: dict[tuple[str, str], tuple[bool, str]] = {}
_PARENT_VERSION: tuple[bool, str, str, str] | None = None  # (ok, detail, image, base)


def _set_log_context(manifest: str | None, log_dir: str | None) -> None:
    """Remember where this worker process writes per-container logs."""
    global _LOG_DIR, _LOG_MANIFEST
    if log_dir is not None:
        _LOG_DIR = log_dir
        os.makedirs(log_dir, exist_ok=True)
    if manifest is not None:
        _LOG_MANIFEST = os.path.splitext(os.path.basename(manifest))[0]


def _log_path(log_dir: str | None, run: ContainerRun) -> str | None:
    dir_ = log_dir if log_dir is not None else _LOG_DIR
    if not dir_:
        return None
    name = f"{_LOG_MANIFEST}-{run.name}.log" if _LOG_MANIFEST else f"{run.name}.log"
    return os.path.join(dir_, name)


def _write_log(path: str | None, content: str) -> None:
    if not path:
        return
    try:
        with open(path, "w") as fh:
            fh.write(content if content.endswith("\n") else content + "\n")
    except OSError:
        pass


def _container_name(run: ContainerRun) -> str:
    """Unique docker container name so parallel manifests never collide."""
    return f"mct-{run.name}-{uuid.uuid4().hex[:10]}"


def _max_run_as_user(pod_spec: dict) -> int | None:
    """Max numeric runAsUser across pod-level and container security contexts."""
    psc = pod_spec.get("securityContext") or {}
    uids: list[int] = []
    candidates = [psc.get("runAsUser")]
    for section in ("initContainers", "containers"):
        for c in pod_spec.get(section) or []:
            candidates.append((c.get("securityContext") or {}).get("runAsUser", psc.get("runAsUser")))
    for uid in candidates:
        if isinstance(uid, bool):
            continue
        if isinstance(uid, int):
            uids.append(uid)
        elif isinstance(uid, str) and uid.isdigit():
            uids.append(int(uid))
    return max(uids) if uids else None


def prepare_fixtures(pod_spec: dict, rendered_cms: dict, root: str) -> dict[str, str]:
    """Create docker-side stand-ins for every pod volume under root.

    persistentVolumeClaim -> root/volumes/<name> (fresh, empty: fresh-PVC worst case)
    emptyDir              -> fresh dir
    configMap             -> dir with the rendered configmap data files written
    any other type (secret, hostPath, ...) -> fresh empty dir (contents are not
        replayable pre-merge; CI never reads cluster secrets)

    Every dir/file is chmod a+rwX and best-effort chowned to the max numeric
    runAsUser of the pod so a container running as that uid can read/write.
    The same volume name maps to the same host dir for every container of the
    pod (K8s emptyDir/PVC semantics): init containers populate fixtures that
    main containers later read.
    """
    vols_dir = os.path.join(os.path.abspath(root), "volumes")
    os.makedirs(vols_dir, exist_ok=True)
    uid = _max_run_as_user(pod_spec)
    hosts: dict[str, str] = {}
    touched: list[str] = []
    for vol in pod_spec.get("volumes") or []:
        name = vol.get("name")
        if not name:
            continue
        host = os.path.join(vols_dir, name)
        os.makedirs(host, exist_ok=True)
        hosts[name] = host
        touched.append(host)
        cm_ref = vol.get("configMap")
        if cm_ref:
            cm_name = cm_ref.get("name", "")
            data = rendered_cms.get(cm_name)
            if data is None:
                raise RuntimeError(f"volume {name}: configMap {cm_name} not in rendered configmaps")
            for key, value in data.items():
                fpath = os.path.join(host, key)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w") as fh:
                    fh.write("" if value is None else str(value))
                touched.append(fpath)
    for path in touched:
        try:
            os.chmod(path, 0o777 if os.path.isdir(path) else 0o666)
        except OSError:
            pass
        if uid is not None:
            try:
                os.chown(path, uid, uid)
            except OSError:
                pass  # host may not permit chown; a+rwX keeps access working
    return hosts


def docker_flags(run: ContainerRun, fixtures: dict[str, str]) -> list[str]:
    """Middle slice of `docker run`: everything between run/-d/publish and image.

    Exact order: --entrypoint, -e per env in order, -v per mount in order
    (with :ro when read_only), --user, --read-only.
    """
    flags: list[str] = []
    if run.entrypoint is not None:
        flags += ["--entrypoint", run.entrypoint]
    for key, value in run.env:
        flags += ["-e", f"{key}={value}"]
    for volume_name, mount_path, read_only in run.mounts:
        spec = f"{fixtures[volume_name]}:{mount_path}" + (":ro" if read_only else "")
        flags += ["-v", spec]
    if run.user is not None:
        flags += ["--user", run.user]
    if run.read_only:
        flags.append("--read-only")
    return flags


def publish_flags(run: ContainerRun) -> list[str]:
    """-p 127.0.0.1::<port> per declared port (random/ephemeral host port)."""
    return [flag for port in run.ports for flag in ("-p", f"127.0.0.1::{port}")]


def run_command(
    run: ContainerRun, image: str, fixtures: dict[str, str], detach: bool, publish: bool
) -> list[str]:
    """Full docker argv: run, (-d), publish flags, docker flags, image, argv."""
    cmd: list[str] = ["run"]
    if detach:
        cmd.append("-d")
    if publish:
        cmd += publish_flags(run)
    cmd += docker_flags(run, fixtures)
    cmd.append(image)
    cmd += list(run.argv)
    return cmd


def probe(host_port: int) -> bool:
    """True if the port is serving.

    urllib GET http://127.0.0.1:<port>/ first: any HTTP status (HTTPError
    included) counts as a response.  On a connection-level failure fall back
    to a raw TCP connect; both failing means the port is not up.
    """
    url = f"http://127.0.0.1:{host_port}/"
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        pass  # refused / timeout / reset -> try plain TCP
    try:
        with socket.create_connection(("127.0.0.1", host_port), 3):
            return True
    except OSError:
        return False


def _docker_logs(name: str) -> str:
    proc = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
    out = proc.stdout or ""
    err = proc.stderr or ""
    return out + (("\n" + err) if err else "")


def _container_state(name: str) -> tuple[str, int | None]:
    """(State.Status, State.ExitCode) of a container."""
    proc = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", name],
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "").strip()
    if not out:
        return "missing", None
    parts = out.split()
    code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return parts[0], code


def _stop_container(name: str) -> None:
    subprocess.run(["docker", "stop", "-t", "10", name], capture_output=True)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _docker_port_map(name: str, ports: list[int]) -> dict[int, int]:
    """Map declared container ports to their random host ports via `docker port`."""
    wanted = set(ports)
    proc = subprocess.run(["docker", "port", name], capture_output=True, text=True)
    mapping: dict[int, int] = {}
    for line in (proc.stdout or "").splitlines():
        if " -> " not in line:
            continue
        left, right = line.split(" -> ", 1)
        port = left.split("/")[0]
        if not port.isdigit() or int(port) not in wanted:
            continue
        host_port = right.strip().split()[-1].rsplit(":", 1)[-1]
        if host_port.isdigit():
            mapping[int(port)] = int(host_port)
    return mapping


def run_init(
    run: ContainerRun,
    image: str,
    fixtures: dict[str, str],
    timeout: int = DEFAULT_INIT_TIMEOUT,
    log_dir: str | None = None,
) -> tuple[int, str]:
    """Run one init container to completion (not detached).

    A watchdog thread `docker kill`s the container after `timeout` seconds so
    a wedged init (e.g. a slow copy of the whole /opt/hermes tree) cannot stall
    the gate forever.  Returns (exit_code, combined logs); the logs are also
    written to the log dir.  The timeout/log_dir parameters default to the
    CLI's --init-timeout/--log-dir values (pass them through from run_manifest).
    """
    name = _container_name(run)
    cmd = run_command(run, image, fixtures, detach=False, publish=False)
    cmd[1:1] = ["--name", name, "--rm"]
    done = threading.Event()
    fired = threading.Event()

    def _watchdog() -> None:
        if done.wait(timeout):
            return
        fired.set()
        subprocess.run(["docker", "kill", name], capture_output=True)

    wd = threading.Thread(target=_watchdog, daemon=True)
    wd.start()
    try:
        proc = subprocess.run(
            ["docker"] + cmd, capture_output=True, text=True, timeout=timeout + 60
        )
    except subprocess.TimeoutExpired as e:
        done.set()
        wd.join(timeout=5)
        partial = "".join(
            blob.decode() if isinstance(blob, bytes) else blob
            for blob in (e.stdout, e.stderr)
            if blob
        )
        _stop_container(name)
        logs = partial + f"\n[contract-test] init timed out after {timeout}s; killed"
        _write_log(_log_path(log_dir, run), logs)
        return 124, logs
    except (OSError, subprocess.SubprocessError) as e:
        done.set()
        wd.join(timeout=5)
        logs = f"docker run failed to complete: {e}"
        _write_log(_log_path(log_dir, run), logs)
        return 125, logs
    done.set()
    wd.join(timeout=5)
    logs = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    if fired.is_set():
        logs += f"\n[contract-test] init timed out after {timeout}s; docker kill issued"
    _write_log(_log_path(log_dir, run), logs)
    return proc.returncode, logs


def run_service(
    run: ContainerRun,
    image: str,
    fixtures: dict[str, str],
    survive_s: int,
    log_dir: str | None,
) -> tuple[bool, str]:
    """Start a service container detached and enforce the survival window.

    The container is published on loopback (random host ports) and its
    declared ports are probed every 2 s for the whole window (Review Focus 4:
    slow binds must not fail the gate).  Verdict at window end (Review Focus
    1): exited -> PASS iff the logs show no contract-failure signature (a
    gateway dying on dummy channel credentials is platform behavior, not a
    contract break); still alive -> PASS, provided at least one declared port
    responded during the window (a service that never bound a declared port
    FAILs).  The container is stopped and removed at the end.
    Returns (ok, detail); logs are also written to the log dir.
    """
    name = _container_name(run)
    cmd = run_command(run, image, fixtures, detach=True, publish=bool(run.ports))
    cmd[1:1] = ["--name", name]
    try:
        proc = subprocess.run(["docker"] + cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        detail = f"docker run failed to start: {e}"
        _write_log(_log_path(log_dir, run), detail)
        return False, detail
    if proc.returncode != 0:
        logs = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        _write_log(_log_path(log_dir, run), logs)
        detail = f"docker run failed (rc={proc.returncode}): {logs.strip()[-800:]}"
        return False, detail

    deadline = time.monotonic() + survive_s
    host_ports: dict[int, int] = {}
    port_ok: dict[int, bool] = {p: False for p in run.ports}
    while True:
        if run.ports:
            missing = [p for p in run.ports if p not in host_ports]
            if missing:
                host_ports.update(_docker_port_map(name, missing))
            for p in run.ports:
                if not port_ok[p] and p in host_ports and probe(host_ports[p]):
                    port_ok[p] = True
        if time.monotonic() >= deadline:
            break
        time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))

    status, exit_code = _container_state(name)
    logs = _docker_logs(name)
    if status == "exited":
        ok = not is_contract_failure(logs)
        detail = "exited rc=%s: %s" % (
            exit_code,
            "no contract-failure signature in logs"
            if ok
            else "contract-failure signature in logs",
        )
    elif status == "running":
        if run.ports and not any(port_ok.values()):
            ok = False
            detail = "alive at window end but no declared port ever responded"
        else:
            ok = True
            extra = ""
            if run.ports:
                good = [str(p) for p in run.ports if port_ok[p]]
                if good:
                    extra = f", port(s) {','.join(good)} responded"
            detail = f"alive at window end{extra}"
    else:
        ok = False
        detail = f"unexpected container state at window end: '{status}'"
    _stop_container(name)
    _write_log(_log_path(log_dir, run), logs)
    return ok, detail


_HERMES_VERSION_PATHS = ("hermes", "/opt/hermes/.venv/bin/hermes")


def _hermes_version(image: str) -> str | None:
    """`hermes --version` output for one image.

    The default `hermes` executable is probed first; on failure the venv path
    /opt/hermes/.venv/bin/hermes is tried.  `--entrypoint` is used so the
    image's own ENTRYPOINT cannot swallow the arguments.
    """
    for exe in _HERMES_VERSION_PATHS:
        try:
            proc = subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", exe, image, "--version"],
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        text = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if text:
            return text
    return None


def _oneline(text: str) -> str:
    """Collapse newlines so result details stay on one stdout line."""
    return " | ".join(line.strip() for line in text.splitlines() if line.strip())


def check_version(image: str, base_image: str) -> tuple[bool, str]:
    """Assert `hermes --version` is equal in the candidate and base images."""
    v_image = _hermes_version(image)
    v_base = _hermes_version(base_image)
    if v_image is None or v_base is None:
        missing = [
            ref
            for ref, v in (("image " + image, v_image), ("base " + base_image, v_base))
            if v is None
        ]
        return False, "could not determine hermes --version in " + " and ".join(missing)
    if v_image == v_base:
        return True, "hermes version equal in image and base: " + _oneline(v_image)
    return False, (
        "hermes version mismatch: image "
        + repr(_oneline(v_image))
        + " != base "
        + repr(_oneline(v_base))
    )


def version_assertion(image: str, base_image: str) -> tuple[bool, str]:
    """The version check, executed at most once per invocation.

    Pool workers reuse the parent's verdict shipped via _pool_initializer;
    callers without one (e.g. tests) fall back to the per-process memo.
    """
    if _PARENT_VERSION is not None and _PARENT_VERSION[2:] == (image, base_image):
        return _PARENT_VERSION[0], _PARENT_VERSION[1]
    key = (image, base_image)
    if key not in _VERSION_MEMO:
        _VERSION_MEMO[key] = check_version(image, base_image)
    return _VERSION_MEMO[key]


def _run_manifest_impl(
    manifest_path: str,
    image: str,
    base_image: str,
    chart_dir: str,
    survive_s: int,
    init_timeout_s: int,
    log_dir: str | None,
) -> tuple[bool, list[str], str | None]:
    """Render, build, and execute one manifest's containers.

    Returns (ok, per-container lines, setup_error).  setup_error is non-None
    for exit-2-class problems (manifest/render/fixture setup); container-level
    failures are reflected in ok only.  The fixture root is a fresh temp dir:
    cleaned on success, kept on failure (and announced on stderr) for
    debugging.
    """
    _set_log_context(manifest_path, log_dir)
    lines: list[str] = []
    try:
        helmrelease = load_manifest(manifest_path)
        values = extract_values(helmrelease)
        release, namespace = _release_namespace(helmrelease)
        pod, cms = render_podspec(chart_dir, values, release, namespace)
        runs, skipped = build_plan(pod, image)
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as e:
        return False, [f"FAIL {manifest_path} setup: {e}"], str(e)

    root = tempfile.mkdtemp(prefix="contract-fixtures-")
    try:
        hosts = prepare_fixtures(pod, cms, root)
    except (OSError, RuntimeError) as e:
        shutil.rmtree(root, ignore_errors=True)
        return False, [f"FAIL {manifest_path} fixtures: {e}"], str(e)

    ok = True
    if base_image and base_image != image:
        v_ok, _v_detail = version_assertion(image, base_image)
        ok = ok and v_ok

    for name in skipped:
        lines.append(f"SKIP {manifest_path}/{name} image not under test")

    for run in (r for r in runs if r.is_init):
        code, logs = run_init(run, image, hosts, timeout=init_timeout_s, log_dir=log_dir)
        if code == 0:
            lines.append(f"PASS {manifest_path}/{run.name} init exit 0")
        else:
            tail = "\n".join((logs or "").strip().splitlines()[-5:])
            lines.append(f"FAIL {manifest_path}/{run.name} init exit {code}: {tail}")
            ok = False
            break  # abort: the remaining containers of this pod do not run

    if ok:
        for run in (r for r in runs if not r.is_init):
            s_ok, s_detail = run_service(run, image, hosts, survive_s, log_dir)
            lines.append(f"{'PASS' if s_ok else 'FAIL'} {manifest_path}/{run.name} {s_detail}")
            ok = ok and s_ok

    if ok:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"keeping fixture root for {manifest_path}: {root}", file=sys.stderr)
    return ok, lines, None


def run_manifest(
    manifest_path: str,
    image: str,
    base_image: str,
    chart_dir: str,
    survive_s: int,
    init_timeout_s: int,
    log_dir: str | None,
) -> tuple[bool, list[str]]:
    """Render, build, and execute one manifest's containers. Returns (ok, lines)."""
    ok, lines, _setup_error = _run_manifest_impl(
        manifest_path, image, base_image, chart_dir, survive_s, init_timeout_s, log_dir
    )
    return ok, lines


def _pool_initializer(parent_version: tuple[bool, str, str, str] | None) -> None:
    global _PARENT_VERSION
    _PARENT_VERSION = parent_version


def _run_manifest_worker(args: tuple) -> tuple[bool, list[str], str | None]:
    """Pool entry point (module-level so it pickles across spawn)."""
    return _run_manifest_impl(*args)


def _release_namespace(helmrelease: dict) -> tuple[str, str]:
    spec = helmrelease.get("spec") or {}
    release = spec.get("releaseName") or (helmrelease.get("metadata") or {}).get("name")
    namespace = (
        (helmrelease.get("metadata") or {}).get("namespace")
        or spec.get("targetNamespace")
        or "default"
    )
    return release, namespace


def _plan_for_manifest(manifest: str, chart_dir: str, image: str) -> dict:
    helmrelease = load_manifest(manifest)
    values = extract_values(helmrelease)
    release, namespace = _release_namespace(helmrelease)
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
    global _PARENT_VERSION
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

    if args.dry_run:
        for manifest in args.manifests:
            try:
                plan = _plan_for_manifest(manifest, args.chart_dir, args.image)
            except (OSError, ValueError, RuntimeError, yaml.YAMLError) as e:
                print(f"error: {manifest}: {e}", file=sys.stderr)
                return 2
            print(json.dumps(plan, indent=2))
        return 0

    # Execution path: replay every container in docker against the candidate image.
    if shutil.which("docker") is None:
        print("error: docker not found on PATH", file=sys.stderr)
        return 2

    _set_log_context(None, args.log_dir)

    # Version assertion: once per invocation, only when the base image ref is
    # effectively different from the image under test.
    if args.base_image != args.image:
        version_ok, version_detail = check_version(args.image, args.base_image)
    else:
        version_ok, version_detail = True, "image and base image are the same reference"
    _PARENT_VERSION = (version_ok, version_detail, args.image, args.base_image)
    print(f"{'PASS' if version_ok else 'FAIL'} version {version_detail}")

    tasks = [
        (
            m,
            args.image,
            args.base_image,
            args.chart_dir,
            args.survive,
            args.init_timeout,
            args.log_dir,
        )
        for m in args.manifests
    ]
    workers = max(1, args.parallel)
    if workers == 1:
        results = [_run_manifest_worker(t) for t in tasks]
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_pool_initializer,
            initargs=(_PARENT_VERSION,),
        ) as pool:
            results = list(pool.map(_run_manifest_worker, tasks))

    rc = 0
    for ok, lines, setup_error in results:
        for line in lines:
            print(line)
        if setup_error is not None:
            print(f"error: {setup_error}", file=sys.stderr)
            rc = 2
        elif not ok:
            rc = max(rc, 1)
    if not version_ok:
        rc = max(rc, 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())