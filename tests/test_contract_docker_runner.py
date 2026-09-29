import socket, threading, http.server, subprocess, shutil
import pytest
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