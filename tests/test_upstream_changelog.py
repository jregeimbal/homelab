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

def test_fetch_compare_read_timeout_is_runtime_error(monkeypatch):
    class SlowBody:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): raise TimeoutError('The read operation timed out')
    monkeypatch.setattr(uc.urllib.request, 'urlopen', lambda *a, **k: SlowBody())
    import pytest
    with pytest.raises(RuntimeError, match='timed out'):
        uc.fetch_compare('nousresearch/hermes-agent', 'v1', 'v2')

def test_render_comment_cap():
    p = {'ahead_by': 3, 'commits': [{'sha': f'c{i}', 'commit': {'message': 'm' * 500}} for i in range(3)],
         'files': [{'filename': 'CHANGELOG.md', 'patch': 'x' * 100000}]}
    assert len(uc.render_comment('r/o', 'a', 'b', uc.classify(p))) <= 30000
