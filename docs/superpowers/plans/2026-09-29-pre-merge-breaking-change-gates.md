# Pre-Merge Breaking-Change Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate hermes base-image bumps in CI before merge — replay every rendered manifest container against the freshly built image in Docker, and diff the upstream changelog between old and new base tags with a PR comment.

**Architecture:** Two new jobs in `.github/workflows/docker-build.yml`. `contract-tests` (needs `build-push`, runs on PR and push): extract each HelmRelease's `values:` block, `helm template` it against the pinned upstream chart commit, then run every rendered init container in order (expect exit 0) and every main container using the built image via `docker run` with rendered env (secretKeyRef → dummy) and bind-mounted volume fixtures (PVC → fresh dir, emptyDir → shared tmp dir, configMap → rendered data), asserting survival plus port probes; also assert `hermes --version` in our image equals the upstream base image's. `upstream-changelog` (parallel, runs on PR and push): GitHub compare API between the old base tag (manifest `tag:` minus `-sha`) and the new base tag (Dockerfile `FROM`), always posting a PR comment, failing the check only on breaking markers or fetch failure.

**Tech Stack:** GitHub Actions (ubuntu-latest), Python 3 + PyYAML (pytest for tests), Helm 3 CLI, Docker CLI, GitHub REST compare API.

**Spec:** Approved in-chat design, option (a) "pre-merge only" (2026-09-28, session ses_f135dc223ffe). Scope limits: no cluster secrets, no kubeconfig in CI, no post-deploy checks, no canary. After merge, the user must mark both new checks required in GitHub branch protection.

## Global Constraints

- Pre-merge only: CI never reads cluster secrets. Env from `valueFrom.secretKeyRef` becomes the literal dummy value `ci-dummy-<KEY>`.
- Only containers whose image **repository** equals the image-under-test repository are contract-tested; foreign images (e.g. `ghcr.io/browserless/chromium:latest`) are reported as skipped, not run.
- Chart source: `https://github.com/ultraworkers/hermes-agent-helm-chart`, chart at repo root, commit read **dynamically** from `flux/cluster/helmrepositories.yaml` (the `GitRepository` named `hermes-agent`, `spec.ref.commit`; currently `e3b685d4d0288668a37216435742cd0a659ebc6c` — never hardcode it).
- Manifest set is exactly: `flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml flux/apps/hermes-wander.yaml`.
- Base image ref is parsed from line 1 of `Dockerfile` (`FROM <repo>:<tag>`; currently `nousresearch/hermes-agent:v2026.9.24`).
- New Python code: stdlib + PyYAML only. Tests: pytest.
- Both new jobs run on `pull_request` and `push` (pre-merge is the point). `contract-tests` needs `build-push`; `upstream-changelog` needs nothing (fully parallel).
- The build is multi-arch (`platforms: linux/amd64,linux/arm64`), so the amd64 GitHub runner can pull and run the image built in the same run.
- Built image ref: on push events `${REGISTRY}/${OWNER}/${IMAGE_NAME}:${{ needs.build-push.outputs.version }}-${{ needs.build-push.outputs.sha }}`; on `pull_request` the version tag is disabled, so use `${{ needs.build-push.outputs.sha }}` only.
- Upstream changelog breaking markers (case-insensitive regex): `BREAKING`, `removed`, `no longer`, `requires` — matched against commit messages and against patches of files whose path matches `*changelog*` (case-insensitive).
- Total added CI wall time target: +2–4 min, parallel.

## Review Focus

1. **Gateway exits on dummy channel credentials** — `gateway run` with dummy env may fail WhatsApp/Telegram/Discord connections and exit non-zero; a survival-only check becomes flaky or a false negative. → Task 1 tests `is_contract_failure`; Task 2 pins the assertion: a service container PASSES if alive at window end OR its logs contain no contract-failure signature (traceback / missing module / unrecognized-argument usage errors).
2. **GHCR visibility on PRs** — if the ghcr package is private, PR checks can't pull. → Task 3 includes the login step; Task 5 verification catches a 403 and directs the fix (make package public or add a read-only PAT secret).
3. **Chart/values drift** — a future chart pin bump may reject committed values. → `render_podspec` must raise with helm's stderr verbatim (Task 1 test).
4. **Port-probe flakiness** — slow binds must not fail the gate. → probes retry for the whole survival window; a port that never responded fails only if the container died or shows a contract-failure signature (Task 2 test).
5. **Changelog marker false positives** — a benign "removed X" commit fails the check. Accepted tradeoff (fail = human review). → the failure output must point at the posted comment URL (Task 4 test).

---

### Task 1: Plan builder — parse, render, plan (pure logic, dry-run)

**Files:**
- Create: `scripts/manifest-contract-test.py`
- Create: `tests/test_manifest_contract_test.py`
- Create: `tests/fixtures/rendered-jon-pod.yaml`
- Create: `tests/fixtures/rendered-jon-values.yaml` (the dumped `spec.values`, used by the real-chart render test)
- Create: `tests/fixtures/podspec-min.yaml` (minimal synthetic pod spec used by Task 2 too)

**Interfaces:**
- Produces (all in `scripts/manifest-contract-test.py`, importable — put a `if __name__ == '__main__': sys.exit(main())` guard):
  - `@dataclass ContainerRun: name: str; image: str; entrypoint: str | None; argv: list[str]; env: list[tuple[str, str]]; mounts: list[tuple[str, str, bool]]  # (volume_name, mount_path, read_only); user: str | None; read_only: bool; ports: list[int]; is_init: bool`
  - `load_manifest(path: str) -> dict` — parse one HelmRelease doc.
  - `extract_values(helmrelease: dict) -> str` — `yaml.safe_dump` of `spec.values`.
  - `chart_commit(repo_root: str) -> str` — find the `GitRepository` named `hermes-agent` under `flux/cluster/*.yaml`, return `spec.ref.commit`.
  - `render_podspec(chart_dir: str, values_text: str, release: str, namespace: str) -> tuple[dict, dict[str, dict[str, str]]]` — `helm template` (subprocess), return (Deployment pod template spec, `{configmap_name: {key: value}}`); on non-zero exit raise `RuntimeError` whose message includes helm's stderr verbatim.
  - `resolve_env(entry: dict, rendered_cms: dict) -> tuple[str, str]` — literal → as-is; `secretKeyRef` → `("ci-dummy-<KEY>")`; `configMapKeyRef` → value from `rendered_cms[cm][key]` (raise `RuntimeError` naming the missing cm/key if absent).
  - `build_plan(pod_spec: dict, image_under_test: str) -> tuple[list[ContainerRun], list[str]]` — init containers first in rendered order, then main containers in rendered order; containers whose image repository ≠ `image_under_test` repository → their names in the second (skipped) list. K8s→docker argv mapping: `command` present → `entrypoint=command[0]`, `argv=command[1:]+args`; `command` absent → `entrypoint=None`, `argv=args` (image ENTRYPOINT is used). `user` from container `securityContext.runAsUser/runAsGroup`, falling back to pod-level `securityContext` (format `"uid:gid"` or `"uid"`).
  - `is_contract_failure(logs: str) -> bool` — True if logs contain any of: `Traceback (most recent call last)`, `No module named`, `ModuleNotFoundError`, `ImportError`, `cannot import name`, `unrecognized arguments`, `error: argument`, `usage:`.
  - CLI: `--image REF` (required) `--base-image REF` (default: parse Dockerfile in repo root) `--manifests P...` (required) `--chart-dir DIR` (required) `--dry-run` (render + build plans, print JSON, exit 0 — no docker) `--survive N` (default 45) `--init-timeout N` (default 300) `--parallel N` (default 3, manifest-level) `--log-dir DIR` (default `/tmp/contract-logs`; write `<manifest>-<container>.log` per container).
  - Exit codes: 0 all pass; 1 any failure; 2 usage/setup error (missing helm, render failure).

- [ ] **Step 1: Build the checked-in render fixture**

Run (reproducible from repo state; the pinned commit comes from the flux file, not hardcoded):

```bash
COMMIT=$(python3 -c "
import yaml, glob
for f in glob.glob('flux/cluster/*.yaml'):
    for d in yaml.safe_load_all(open(f)):
        if d and d.get('kind') == 'GitRepository' and d['metadata']['name'] == 'hermes-agent':
            print(d['spec']['ref']['commit'])
")
rm -rf /tmp/chart-fixture && mkdir -p /tmp/chart-fixture && cd /tmp/chart-fixture
git clone --depth 1 https://github.com/ultraworkers/hermes-agent-helm-chart chart
git -C chart fetch --depth 1 origin "$COMMIT" && git -C chart checkout -q "$COMMIT"
python3 -c "
import yaml, os
d = yaml.safe_load(open('flux/apps/hermes-jon.yaml'))
os.makedirs('tests/fixtures', exist_ok=True)
open('tests/fixtures/rendered-jon-values.yaml', 'w').write(yaml.safe_dump(d['spec']['values'], sort_keys=False))
open('/tmp/chart-fixture/values.yaml', 'w').write(yaml.safe_dump(d['spec']['values'], sort_keys=False))
"
helm template hermes chart -f values.yaml -n jon-agent > /tmp/chart-fixture/rendered.yaml
python3 -c "
import yaml
docs = [d for d in yaml.safe_load_all(open('/tmp/chart-fixture/rendered.yaml')) if d]
dep = next(d for d in docs if d['kind'] == 'Deployment')
out = {
  'pod': dep['spec']['template']['spec'],
  'configmaps': {d['metadata']['name']: (d.get('data') or {}) for d in docs if d['kind'] == 'ConfigMap'},
}
open('tests/fixtures/rendered-jon-pod.yaml', 'w').write(yaml.safe_dump(out, sort_keys=False))
"
```

Then create `tests/fixtures/podspec-min.yaml` by hand: a pod spec with pod-level `securityContext: {runAsUser: 10000}`, one init container (`name: init-x`, `command: ["/bin/sh","-c"]`, `args: ["echo hi > /opt/data/marker"]`, mounts `data:/opt/data`, `securityContext: {runAsUser: 0, readOnlyRootFilesystem: true}`), one service container (`name: svc-x`, `command: ["python3","-m","http.server","8642"], no args, env `[{"name":"A","value":"1"},{"name":"T","valueFrom":{"secretKeyRef":{"name":"s","key":"t"}}}]`, mounts `data:/opt/data`, `ports: [{containerPort: 8642}]`), volumes `data: {persistentVolumeClaim: {claimName: x}}`, `cfg: {configMap: {name: cm-a}}`; plus `configmaps: {cm-a: {"app.conf": "x=1"}}`.

- [ ] **Step 2: Write the failing tests**

`tests/test_manifest_contract_test.py` (imports from `scripts/manifest-contract-test.py` via `sys.path.insert(0, 'scripts')` or a `tests/conftest.py` doing the same):

```python
import yaml, re, os
from scripts import manifest_contract_test as mct   # (via conftest sys.path)

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')

def test_load_manifest_and_extract_values():
    hr = mct.load_manifest('flux/apps/hermes-jon.yaml')
    vals = yaml.safe_load(mct.extract_values(hr))
    assert set(vals) >= {'image', 'config', 'env', 'extraContainers', 'secrets'}
    assert yaml.safe_load(mct.extract_values(hr)) == hr['spec']['values']

def test_chart_commit_is_sha():
    assert re.fullmatch(r'[0-9a-f]{40}', mct.chart_commit(os.getcwd()))

def test_render_podspec_failure_includes_stderr():
    try:
        mct.render_podspec('/nonexistent-chart-dir', 'image:\n  tag: "x"', 'r', 'ns')
        assert False, 'expected RuntimeError'
    except RuntimeError as e:
        assert 'helm' in str(e).lower() or 'chart' in str(e).lower()

@pytest.mark.skipif(shutil.which('helm') is None or not os.environ.get('HERMES_CHART_DIR'), reason='needs helm + chart clone')
def test_render_podspec_real_chart():
    pod, cms = mct.render_podspec(os.environ['HERMES_CHART_DIR'], open(FIX + '/rendered-jon-values.yaml').read(), 'hermes', 'jon-agent')
    assert [c['name'] for c in pod['containers']] == ['hermes-agent', 'browserless-chromium', 'hermes-desktop']
    assert 'config.yaml' in cms['hermes-hermes-agent-config']

def test_argv_mapping():
    cmd_c = {'name': 'd', 'command': ['hermes', 'dashboard', '--port', '9119'], 'image': 'img'}
    arg_c = {'name': 'm', 'args': ['gateway', 'run'], 'image': 'img'}
    plan, _ = mct.build_plan({'containers': [arg_c], 'initContainers': [cmd_c], 'volumes': []}, 'img')
    assert plan[0].entrypoint == 'hermes' and plan[0].argv == ['dashboard', '--port', '9119']
    assert plan[1].entrypoint is None and plan[1].argv == ['gateway', 'run']
    assert plan[0].is_init is True and plan[1].is_init is False

def test_resolve_env():
    cms = {'cm-a': {'app.conf': 'x=1'}}
    assert mct.resolve_env({'name': 'A', 'value': '1'}, cms) == ('A', '1')
    assert mct.resolve_env({'name': 'T', 'valueFrom': {'secretKeyRef': {'name': 's', 'key': 't'}}}, cms) == ('T', 'ci-dummy-T')
    assert mct.resolve_env({'name': 'C', 'valueFrom': {'configMapKeyRef': {'name': 'cm-a', 'key': 'app.conf'}}}, cms) == ('C', 'x=1')

def test_build_plan_order_and_skip():
    fix = yaml.safe_load(open(FIX + '/rendered-jon-pod.yaml'))
    plan, skipped = mct.build_plan(fix['pod'], 'ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.9.24-aaaaaaa')
    assert [c.name for c in plan] == ['bootstrap-config', 'copy-hermes-source', 'bootstrap-home-config', 'fix-data-ownership', 'hermes-agent', 'hermes-desktop']
    assert skipped == ['browserless-chromium']
    main = plan[4]
    assert main.argv == ['gateway', 'run'] and main.entrypoint is None
    assert ('data', '/opt/data', False) in main.mounts
    desk = plan[5]
    assert desk.entrypoint == 'hermes'
    assert desk.argv == ['dashboard', '--host', '0.0.0.0', '--port', '9119', '--insecure', '--no-open']
    assert ('hermes-agent-source', '/opt/hermes', True) in desk.mounts
    # user: assert against the fixture's actual values (container-level, else pod-level fallback)
    sc = fix['pod'].get('securityContext', {})
    expected_user = main_user_from(fix, 'hermes-agent')   # helper in test: container sc or pod sc
    assert main.user == expected_user

def test_is_contract_failure():
    assert mct.is_contract_failure('Traceback (most recent call last)\n  File ...')
    assert mct.is_contract_failure('ModuleNotFoundError: No module named hermes')
    assert mct.is_contract_failure('usage: hermes [-h]\nerror: unrecognized arguments: --insecure')
    assert not mct.is_contract_failure('failed to connect to api.telegram.org: timeout')
    assert not mct.is_contract_failure('')
```

`main_user_from(fix, name)` is a 4-line test-local helper implementing the same container→pod fallback, reading the fixture (write it by looking at the fixture — it is the expectation source).

- [ ] **Step 3: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_manifest_contract_test.py -v`
Expected: collection error / ImportError (`No module named scripts.manifest_contract_test`).

- [ ] **Step 4: Implement the module**

Implement exactly the Interfaces list. Notes the tests leave open:
- `render_podspec` runs `helm template <release> <chart_dir> -f <tmp values file> -n <namespace>` (values written to a temp file) and parses all docs with `yaml.safe_load_all`; the Deployment is found by `kind == 'Deployment'` (single).
- CLI `--dry-run` prints one JSON object per manifest: `{manifest, release, namespace, skipped, runs: [{name, image, entrypoint, argv, env, mounts, user, read_only, ports, is_init}]}`.
- Non-dry-run execution is a stub raising `NotImplementedError` (Task 2 replaces it).

- [ ] **Step 5: Run tests, verify they pass**

Run: `python3 -m pytest tests/test_manifest_contract_test.py -v`
Expected: all PASS (the real-chart test skips unless `HERMES_CHART_DIR` set).

- [ ] **Step 6: Verify dry-run against real manifests + real chart**

```bash
COMMIT=$(python3 -c "
import yaml, glob
for f in glob.glob('flux/cluster/*.yaml'):
    for d in yaml.safe_load_all(open(f)):
        if d and d.get('kind') == 'GitRepository' and d['metadata']['name'] == 'hermes-agent':
            print(d['spec']['ref']['commit'])")
rm -rf /tmp/chart-dry && mkdir /tmp/chart-dry && cd /tmp/chart-dry
git clone --depth 1 https://github.com/ultraworkers/hermes-agent-helm-chart chart
git -C chart fetch --depth 1 origin "$COMMIT" && git -C chart checkout -q "$COMMIT"
python3 scripts/manifest-contract-test.py --dry-run \
  --image ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.9.24-6e01c6c \
  --chart-dir /tmp/chart-dry/chart \
  --manifests flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml flux/apps/hermes-wander.yaml
```

Expected: 3 JSON plans; jon plan = 4 inits + hermes-agent + hermes-desktop, skipped `[browserless-chromium]`; ana plan likewise with its own extra volumes; every `valueFrom.secretKeyRef` env value is `ci-dummy-*`; desktop argv matches the rendered `command`.

- [ ] **Step 7: Commit**

```bash
git add scripts/manifest-contract-test.py tests/test_manifest_contract_test.py tests/fixtures/ tests/conftest.py 2>/dev/null
git commit -m "ci: add manifest contract-test plan builder (helm render + docker replay plan)"
```

---

### Task 2: Docker runner — fixtures, init sequence, survival, probes

**Files:**
- Modify: `scripts/manifest-contract-test.py` (replace the `NotImplementedError` stub)
- Create: `tests/test_contract_docker_runner.py`
- Reuse: `tests/fixtures/podspec-min.yaml` (from Task 1)

**Interfaces:**
- Consumes: `ContainerRun`, `build_plan`, `render_podspec`, `is_contract_failure`, CLI flags `--survive/--init-timeout/--parallel/--log-dir` (all from Task 1).
- Produces:
  - `prepare_fixtures(pod_spec: dict, rendered_cms: dict, root: str) -> dict[str, str]` — one dir per pod volume: `persistentVolumeClaim` → `root/volumes/<name>` (fresh, empty — fresh-PVC worst case), `emptyDir` → fresh dir, `configMap` → dir with rendered `data` files written (subPath ignored in this chart). All dirs `chown`ed to the max numeric runAsUser in the plan, `chmod a+rwX`. Same volume name shared by every container of the pod (K8s emptyDir/PVC semantics) — init containers populate fixtures that main containers later read.
  - `run_command(run: ContainerRun, image: str, fixtures: dict, detach: bool, publish: bool) -> list[str]` — full `docker` argv, exact order: `run`, (`-d` if detach), publish flags, entrypoint flag, env flags, mount flags, user flag, read-only flag, `image`, then `argv`.
  - `docker_flags(run, fixtures) -> list[str]` — the middle slice (everything between `run/-d`/publish and the image): `[--entrypoint <e>]` (only if `entrypoint` not None), one `-e K=V` per env in order, one `-v host:mp` or `-v host:mp:ro` per mount in order, `[--user <u>]`, `[--read-only]`.
  - `publish_flags(run) -> list[str]` — `-p 127.0.0.1::<port>` per port (random host port).
  - `run_init(run, image, fixtures) -> tuple[int, str]` — `docker run` (not detached) with `--init-timeout` watchdog; returns (exit_code, combined logs); logs also written to `--log-dir`.
  - `probe(host_port: int) -> bool` — `urllib` GET `http://127.0.0.1:<host_port>/`, any HTTP status = True; on connection-level failure fall back to raw TCP connect, success = True; both fail = False.
  - `run_service(run, image, fixtures, survive_s, log_dir) -> tuple[bool, str]` — start detached with publish; poll `docker port` then `probe` every 2 s until the window elapses (port must respond at least once during the window — Review Focus 4); at window end: container exited → PASS iff `not is_contract_failure(logs)` (Review Focus 1), else FAIL; still alive → PASS (and require the port responded at least once if the container declares ports — a service that never bound a declared port FAILs); stop container.
  - `run_manifest(manifest_path, image, base_image, chart_dir, survive_s, init_timeout_s, log_dir) -> tuple[bool, list[str]]` — render, build plan, prepare fixtures under a fresh temp root, run inits in order (any non-zero exit → FAIL, abort, report), then service containers (each with the shared fixtures), version assertion (`hermes --version` in `image` vs `base_image`, both probed as `hermes --version` then `/opt/hermes/.venv/bin/hermes --version` on failure — must be equal when base_image given), return (ok, per-container result lines).
  - `main()` — loop manifests with a process pool of `--parallel`, print one line per container (`PASS/FAIL/SKIP <manifest>/<container> <detail>`), exit 0/1.

- [ ] **Step 1: Write the failing tests**

`tests/test_contract_docker_runner.py`:

```python
import socket, threading, http.server, subprocess, shutil
from scripts import manifest_contract_test as mct

def make_run(**kw):
    base = dict(name='c', image='img', entrypoint=None, argv=['true'], env=[('A','1')],
                mounts=[('data','/opt/data',False)], user=None, read_only=False, ports=[], is_init=False)
    base.update(kw)
    return mct.ContainerRun(**base)

def test_docker_flags_exact():
    run = make_run(entrypoint='hermes', argv=['dashboard','--port','9119'],
                   env=[('A','1'),('T','ci-dummy-T')],
                   mounts=[('data','/opt/data',False),('src','/opt/hermes',True)],
                   user='10000:10000', read_only=True)
    assert mct.docker_flags(run, {'data':'/h/data','src':'/h/src'}) == [
        '--entrypoint','hermes','-e','A=1','-e','T=ci-dummy-T',
        '-v','/h/data:/opt/data','-v','/h/src:/opt/hermes:ro',
        '--user','10000:10000','--read-only']

def test_run_command_assembly():
    run = make_run(entrypoint='hermes', argv=['dashboard'])
    cmd = mct.run_command(run, 'ghcr.io/x/y:v1', {'data':'/h/data'}, detach=True, publish=False)
    assert cmd[:2] == ['run','-d']
    assert cmd[-2:] == ['ghcr.io/x/y:v1','dashboard']

def test_publish_flags():
    assert mct.publish_flags(make_run(ports=[8642,9119])) == ['-p','127.0.0.1::8642','-p','127.0.0.1::9119']

def test_probe_http_any_status():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(500); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try: assert mct.probe(srv.server_address[1])
    finally: srv.shutdown()

def test_probe_tcp_only():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1)
    threading.Thread(target=lambda: s.accept(), daemon=True).start()
    try: assert mct.probe(s.getsockname()[1])
    finally: s.close()

def test_prepare_fixtures():
    import yaml, tempfile, os
    fix = yaml.safe_load(open('tests/fixtures/podspec-min.yaml'))
    root = tempfile.mkdtemp()
    vols = mct.prepare_fixtures(fix['pod'], fix['configmaps'], root)
    assert set(vols) == {'data', 'cfg'}
    assert open(os.path.join(vols['cfg'], 'app.conf')).read() == 'x=1'
    assert os.path.isdir(vols['data']) and os.listdir(vols['data']) == []

@pytest.mark.skipif(shutil.which('docker') is None, reason='docker not available')
def test_run_service_live_pass_and_semantics():
    import yaml, tempfile, os
    fix = yaml.safe_load(open('tests/fixtures/podspec-min.yaml'))
    root = tempfile.mkdtemp()
    vols = mct.prepare_fixtures(fix['pod'], fix['configmaps'], root)
    # init writes into the shared fixture; service must see it
    init = mct.ContainerRun(name='init-x', image='alpine:3.20', entrypoint='sh', argv=['-c','echo hi > /opt/data/marker'],
                            env=[], mounts=[('data','/opt/data',False)], user='0', read_only=False, ports=[], is_init=True)
    code, logs = mct.run_init(init, 'alpine:3.20', vols)
    assert code == 0
    assert open(os.path.join(vols['data'], 'marker')).read().strip() == 'hi'
    # alive service passes
    svc = mct.ContainerRun(name='svc', image='alpine:3.20', entrypoint='sh', argv=['-c','sleep 60'],
                           env=[], mounts=[('data','/opt/data',False)], user=None, read_only=False, ports=[], is_init=False)
    ok, detail = mct.run_service(svc, 'alpine:3.20', vols, survive_s=10, log_dir=root)
    assert ok, detail
    # exited without contract signature passes (Review Focus 1)
    svc2 = mct.ContainerRun(name='svc2', image='alpine:3.20', entrypoint='sh', argv=['-c','echo platform failure; exit 3'],
                            env=[], mounts=[], user=None, read_only=False, ports=[], is_init=False)
    ok2, _ = mct.run_service(svc2, 'alpine:3.20', vols, survive_s=10, log_dir=root)
    assert ok2
    # traceback fails
    svc3 = mct.ContainerRun(name='svc3', image='alpine:3.20', entrypoint='sh',
                            argv=['-c','echo "Traceback (most recent call last)"; exit 1'],
                            env=[], mounts=[], user=None, read_only=False, ports=[], is_init=False)
    ok3, _ = mct.run_service(svc3, 'alpine:3.20', vols, survive_s=10, log_dir=root)
    assert not ok3
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_contract_docker_runner.py -v`
Expected: FAIL/AttributeError for `docker_flags`, `prepare_fixtures`, `run_init`, `run_service`.

- [ ] **Step 3: Implement the runner**

Implement the Interfaces list, replace the `NotImplementedError` stub in `main()`. Implementation notes the tests leave open:
- `probe`: try `urllib.request.urlopen(..., timeout=3)`; on `URLError`/`HTTPError` where `HTTPError` has an `.code` → True; else TCP `socket.create_connection(('127.0.0.1', port), 3)`.
- Init watchdog: a thread that `docker kill`s after `--init-timeout` (default 300 s — `copy-hermes-source` copies the whole `/opt/hermes` tree).
- Manifest parallelism: `concurrent.futures.ProcessPoolExecutor(max_workers=--parallel)` over manifests; each manifest gets a fresh temp fixture root (cleaned up on success, kept on failure for log debugging).
- Version assertion only runs once per invocation (not per manifest) and only when `--base-image` is effectively different from `--image`.

- [ ] **Step 4: Run tests, verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS (live docker test runs if docker is up — on this Mac and on GH runners; skip otherwise).

- [ ] **Step 5: Full local end-to-end against the real image**

```bash
docker pull ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.9.24-6e01c6c   # needs ghcr login or public package
python3 scripts/manifest-contract-test.py \
  --image ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab:v2026.9.24-6e01c6c \
  --chart-dir /tmp/chart-dry/chart \
  --manifests flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml flux/apps/hermes-wander.yaml \
  --survive 45
```

Expected: all `PASS` lines (inits exit 0; `hermes-agent` alive + 8642 responds; `hermes-desktop` alive + 9119 responds; `browserless-chromium` SKIP; version assertion equal). If the gateway exits on dummy channel credentials, the contract-failure classifier must still PASS it (Review Focus 1) — if it instead shows a traceback, record the exact log tail in the commit message. If `docker pull` 403s, note that the ghcr package is private (unblocks Task 3's login step and Task 5's public-package check).

- [ ] **Step 6: Commit**

```bash
git add scripts/manifest-contract-test.py tests/test_contract_docker_runner.py
git commit -m "ci: implement docker runner for manifest contract tests (fixtures, init sequence, survival, probes)"
```

---

### Task 3: Wire the `contract-tests` job into the workflow

**Files:**
- Modify: `.github/workflows/docker-build.yml`

**Interfaces:**
- Consumes: `scripts/manifest-contract-test.py` CLI (Task 1/2), `build-push` outputs `version`/`sha`, workflow env `REGISTRY/OWNER/IMAGE_NAME`.
- Produces: job `contract-tests` (name "Contract Tests (manifest replay)") — this is the required-status check the user will enforce in branch protection.

- [ ] **Step 1: Add the job**

Insert after `build-push` (position in file doesn't matter; it only `needs` build-push, so it stays parallel with `validate-*`/`bump-version`):

```yaml
  contract-tests:
    name: Contract Tests (manifest replay)
    runs-on: ubuntu-latest
    timeout-minutes: 20
    needs: [build-push]
    permissions:
      contents: read
      packages: read
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Resolve image refs
        id: img
        run: |
          REF="${{ env.REGISTRY }}/${{ env.OWNER }}/${{ env.IMAGE_NAME }}:"
          if [ "${{ github.event_name }}" = "push" ]; then
            TAG="${{ needs.build-push.outputs.version }}-${{ needs.build-push.outputs.sha }}"
          else
            TAG="${{ needs.build-push.outputs.sha }}"
          fi
          echo "ref=${REF}${TAG}" >> "$GITHUB_OUTPUT"
          echo "base=$(grep '^FROM ' Dockerfile | awk '{print $2}')" >> "$GITHUB_OUTPUT"

      - name: Install helm
        run: curl -sSfL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

      - name: Clone pinned chart
        id: chart
        run: |
          COMMIT=$(python3 -c "
          import yaml, glob
          for f in glob.glob('flux/cluster/*.yaml'):
              for d in yaml.safe_load_all(open(f)):
                  if d and d.get('kind') == 'GitRepository' and d['metadata']['name'] == 'hermes-agent':
                      print(d['spec']['ref']['commit'])")
          git clone --depth 1 https://github.com/ultraworkers/hermes-agent-helm-chart chart
          git -C chart fetch --depth 1 origin "$COMMIT"
          git -C chart checkout -q "$COMMIT"
          echo "dir=\$PWD/chart" >> "$GITHUB_OUTPUT"

      - name: Install Python deps
        run: python3 -m pip install --quiet pyyaml pytest

      - name: Run unit tests
        run: python3 -m pytest tests/ -q

      - name: Run contract tests
        run: |
          python3 scripts/manifest-contract-test.py \
            --image "${{ steps.img.outputs.ref }}" \
            --base-image "${{ steps.img.outputs.base }}" \
            --chart-dir "${{ steps.chart.outputs.dir }}" \
            --manifests flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml flux/apps/hermes-wander.yaml \
            --survive 45 --parallel 3 --log-dir /tmp/contract-logs

      - name: Upload container logs
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: contract-test-logs
          path: /tmp/contract-logs/
          if-no-files-found: ignore
```

Note: no `if: github.event_name == 'push'` guard — this job must run on `pull_request` (pre-merge is the point).

- [ ] **Step 2: Validate the workflow file**

Run: `python3 -c "import yaml; d = yaml.safe_load(open('.github/workflows/docker-build.yml')); print(sorted(d['jobs']))"`
Expected: prints all six job ids; no YAML error. (Run `actionlint` too if installed locally — optional.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docker-build.yml
git commit -m "ci: add contract-tests job replaying rendered manifests against the built image"
```

---

### Task 4: `upstream-changelog` — diff, comment, breaking gate

**Files:**
- Create: `scripts/upstream-changelog.py`
- Create: `tests/test_upstream_changelog.py`
- Modify: `.github/workflows/docker-build.yml` (add job)

**Interfaces:**
- Produces:
  - CLI: `--dockerfile PATH` (default `Dockerfile`) `--manifests P...` (required) `--repo OWNER/NAME` (default `nousresearch/hermes-agent` — Task 4 Step 1 verifies) `--token T` (optional) `--out-json PATH` `--out-comment-file PATH` (optional). Exit codes: `0` no upstream change OR change without breaking markers; `10` breaking change detected; `2` fetch/parse failure.
  - `base_from_dockerfile(path) -> tuple[str, str]` — `(repo, tag)` from the `FROM` line.
  - `strip_sha(tag) -> str` — `v2026.9.24-6e01c6c` → `v2026.9.24` (strip the last `-<hex>` segment only if it looks like a sha suffix: 7+ hex chars).
  - `old_bases(manifest_paths) -> tuple[str, str]` — collect image base tags from each manifest's `spec.values` (both the `image` string's tag part and a separate `tag` key if present), strip sha, return `(repo, min(tags))` (date-based tags sort lexicographically).
  - `fetch_compare(repo, old_tag, new_tag, token) -> dict` — `GET https://api.github.com/repos/{repo}/compare/{old}...{new}` (Authorization header if token); raise `RuntimeError` with the HTTP status + body on 4xx/5xx.
  - `classify(payload) -> dict` — returns `{ahead_by, behind_by, commits: [(sha, message)], files: [filenames], changelog_diff: str, breaking: [matched lines], breaking_detected: bool}`. Breaking markers (Global Constraints regex) matched against: every commit message, and the patch text of files whose filename matches `*changelog*` (case-insensitive).
  - `render_comment(repo, old, new, cls) -> str` — markdown: header `## Upstream hermes-agent diff`, `old → new`, `+N commits`, commit list (capped at 50), breaking matches (if any) quoted, changelog file diff excerpt (capped so total ≤ 30 000 chars, `… [truncated]` marker).

- [ ] **Step 1: Verify the upstream repo assumption**

```bash
curl -s https://api.github.com/repos/nousresearch/hermes-agent | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('full_name'), d.get('message'))"
curl -s "https://api.github.com/repos/nousresearch/hermes-agent/tags?per_page=10" | python3 -c "import json,sys; [print(t['name']) for t in json.load(sys.stdin)]"
```

Expected: repo exists (no `message: API rate limit...`/`Not Found`) and tags include `v2026.9.24`. If 404, search GitHub (`curl -s "https://api.github.com/search/repositories?q=hermes-agent+nousresearch"`) for the real location and update the `--repo` default in this plan before implementing. If the repo exists but uses different tag names, record the mapping (the script must be able to find the old tag — if tags don't match image tags, fall back to comparing by commit date is out of scope: instead make `--repo` configurable in the workflow and document the limitation).

- [ ] **Step 2: Write the failing tests**

`tests/test_upstream_changelog.py`:

```python
from scripts import upstream_changelog as uc

def test_base_from_dockerfile():
    assert uc.base_from_dockerfile('Dockerfile') == ('nousresearch/hermes-agent', 'v2026.9.24')

def test_strip_sha():
    assert uc.strip_sha('v2026.9.24-6e01c6c') == 'v2026.9.24'
    assert uc.strip_sha('v2026.9.24') == 'v2026.9.24'
    assert uc.strip_sha('v1.2.3-abcdef0') == 'v1.2.3'

def test_old_bases_real_manifests():
    repo, tag = uc.old_bases(['flux/apps/hermes-jon.yaml', 'flux/apps/hermes-ana.yaml', 'flux/apps/hermes-wander.yaml'])
    assert repo == 'ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab'
    assert tag == 'v2026.9.24'

def test_equal_tags_no_diff():
    # manifests are in sync with the Dockerfile base today → old == new → no network call, exit 0
    rc = uc.main(['--dockerfile', 'Dockerfile', '--manifests', 'flux/apps/hermes-jon.yaml',
                  '--repo', 'nousresearch/hermes-agent'])
    assert rc == 0

def test_classify_breaking_in_commit_message():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'feat!: drop --insecure flag (BREAKING)'}}], 'files': []}
    cls = uc.classify(p)
    assert cls['breaking_detected'] and any('BREAKING' in l for l in cls['breaking'])

def test_classify_breaking_in_changelog_file_only():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'docs: update changelog'}}],
         'files': [{'filename': 'CHANGELOG.md', 'patch': '- removed `--no-open` (no longer supported)\n'}]}
    assert uc.classify(p)['breaking_detected']
    p2 = dict(p, files=[{'filename': 'src/util.py', 'patch': '- removed helper\n'}])
    assert not uc.classify(p2)['breaking_detected']

def test_classify_clean():
    p = {'ahead_by': 2, 'commits': [{'sha': 'a', 'commit': {'message': 'fix: typo'}}, {'sha': 'b', 'commit': {'message': 'feat: new tool'}}], 'files': []}
    assert not uc.classify(p)['breaking_detected']

def test_fetch_failure_exit_2(monkeypatch):
    monkeypatch.setattr(uc, 'old_bases', lambda paths: ('ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab', 'v2026.9.23'))
    monkeypatch.setattr(uc, 'fetch_compare', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('HTTP 404')))
    rc = uc.main(['--dockerfile', 'Dockerfile', '--manifests', 'flux/apps/hermes-jon.yaml',
                  '--repo', 'nousresearch/hermes-agent'])
    assert rc == 2

def test_render_comment_cap():
    p = {'ahead_by': 3, 'commits': [{'sha': f'c{i}', 'commit': {'message': 'm' * 500}} for i in range(3)],
         'files': [{'filename': 'CHANGELOG.md', 'patch': 'x' * 100000}]}
    assert len(uc.render_comment('r/o', 'a', 'b', uc.classify(p))) <= 30000
```

Note: `main(argv)` returns the exit code (also `sys.exit(main())` in `__main__`). Network paths are exercised purely by monkeypatching `old_bases`/`fetch_compare` — no test-only CLI flags.

- [ ] **Step 3: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_upstream_changelog.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement the script**

Implement the Interfaces list. `main` flow: parse base (new) from Dockerfile; parse old from manifests; if equal → print "no upstream base change", optional comment "no upstream change", exit 0; else fetch_compare → classify → write json/comment files → exit 0 or 10 (breaking). On `RuntimeError` from fetch: print the error, exit 2. The failure path's stdout must include the exact line `See the PR comment for the full diff.` (Review Focus 5 — tested implicitly via the comment step always running).

- [ ] **Step 5: Run tests, verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Add the workflow job**

Append to `.github/workflows/docker-build.yml`:

```yaml
  upstream-changelog:
    name: Upstream Changelog Diff
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
      pull-requests: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install Python deps
        run: python3 -m pip install --quiet pyyaml

      - name: Diff upstream base
        run: |
          python3 scripts/upstream-changelog.py \
            --dockerfile Dockerfile \
            --manifests flux/apps/hermes-jon.yaml flux/apps/hermes-ana.yaml flux/apps/hermes-wander.yaml \
            --token "${GITHUB_TOKEN}" \
            --out-json /tmp/changelog.json \
            --out-comment-file /tmp/changelog-comment.md

      - name: Post PR comment
        if: github.event_name == 'pull_request' && always()
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          [ -s /tmp/changelog-comment.md ] || { echo "nothing to post"; exit 0; }
          curl -sf -X POST \
            "https://api.github.com/repos/${{ github.repository }}/issues/${{ github.event.pull_request.number }}/comments" \
            -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
            -d "{\"body\": $(jq -Rs . /tmp/changelog-comment.md)}"
```

No `needs:` — fully parallel with everything.

- [ ] **Step 7: Validate + commit**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docker-build.yml'))"` → no error.

```bash
git add scripts/upstream-changelog.py tests/test_upstream_changelog.py .github/workflows/docker-build.yml
git commit -m "ci: add upstream-changelog job (compare old/new base tags, PR comment, breaking gate)"
```

---

### Task 5: End-to-end verification, docs, branch protection handoff

**Files:**
- Create: `docs/ci-gates.md`

**Interfaces:**
- Consumes: everything from Tasks 1–4.

- [ ] **Step 1: Write `docs/ci-gates.md`**

Sections (short, operator-facing): (1) What the two gates do and when they run; (2) Triage: contract-test failure → download `contract-test-logs` artifact, which container, log tail, likely cause (upstream behavior change vs our config); changelog failure → read the posted PR comment, judge the marked breaking lines, override with `/merge` authority if false positive; (3) How to update the chart pin (`flux/cluster/helmrepositories.yaml` commit) and the base tag (Dockerfile `FROM`); (4) Branch protection: both checks must be required on `main` (search "Contract Tests" and "Upstream Changelog" in Settings → Branches).

- [ ] **Step 2: Push the branch and open PR #1**

```bash
git push origin HEAD:ci-contract-gates
gh pr create --base main --head ci-contract-gates --title "ci: pre-merge breaking-change gates" --body "$(cat docs/ci-gates.md)"
```

The workflow's path filter only fires on `Dockerfile`/`requirements.txt`/`assets/**` — so PR #1 needs a trigger touch: add a comment line to `Dockerfile` (e.g. `# CI: see docs/ci-gates.md for pre-merge gates`) as part of the branch before pushing.

Verify (watch the run; `gh run watch`):
- `Contract Tests (manifest replay)`: unit tests green; image pull succeeds (if 403 → package is private: either set it public in repo Settings → Packages, or create a read-only PAT secret `GHCR_READ_TOKEN` and swap it into the login step; record which); all containers PASS.
- `Upstream Changelog Diff`: posts a comment saying no upstream base change (PR #1 doesn't bump the base).

- [ ] **Step 3: Scratch PR #2 — exercise the real diff path**

Create a scratch branch from `main` changing only the Dockerfile `FROM` tag to the **previous** upstream base tag (pick from the tag list in Task 4 Step 1, e.g. the tag before `v2026.9.24`). Push + open a PR (do **not** merge). Verify:
- `Upstream Changelog Diff` posts a real diff comment (commit list + any breaking lines) and the check state matches the marker scan (fail iff markers hit).
- `Contract Tests` runs the current manifests against the image built from the older base — this is exactly the protection scenario; record the outcome (PASS means our manifests tolerate the older base; FAIL with the log artifact means the gate did its job).
- Close PR #2 without merging.

- [ ] **Step 4: Merge PR #1 and confirm the push path**

After merge, the push run executes both jobs against the new tag (version-sha tag exists on push). Verify green.

- [ ] **Step 5: Branch protection (user action)**

Ask the user to add both checks as **required** on `main` (Settings → Branches → branch protection rule → Require status checks to pass before merging; search "Contract Tests" and "Upstream Changelog"). Confirm in chat when done.

- [ ] **Step 6: Final commit + report**

```bash
git add docs/ci-gates.md Dockerfile
git commit -m "docs: describe pre-merge CI gates and triage steps"
```

Report to the user: what's live, the PR evidence (run links), the branch-protection action taken, and the deferred open items from the earlier triage (py-global de-dup rebuild, delete `/opt/data/py-global-stale-hermes-20260928.tar` after a few days, desktop 768Mi limit already raised).