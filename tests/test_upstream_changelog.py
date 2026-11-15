import re

from scripts import upstream_changelog as uc

# Tests must not pin the live Dockerfile/manifest tags: a base-bump PR changes
# them, and that PR is exactly the one these gates exist to run on.
MANIFESTS = ['flux/apps/hermes-jon.yaml', 'flux/apps/hermes-ana.yaml', 'flux/apps/hermes-wander.yaml']


def _dockerfile(tmp_path, tag):
    p = tmp_path / 'Dockerfile'
    p.write_text(f'FROM nousresearch/hermes-agent:{tag}\n# comment\nENV X=1\n')
    return str(p)


def _manifest(tmp_path, name, tag):
    p = tmp_path / f'{name}.yaml'
    p.write_text(
        'apiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\nspec:\n  values:\n    image:\n'
        f'      repository: ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab\n      tag: "{tag}"\n'
    )
    return str(p)


def _main_argv(tmp_path):
    return ['--dockerfile', _dockerfile(tmp_path, 'v2026.9.24'),
            '--manifests', _manifest(tmp_path, 'a', 'v2026.9.23-6e01c6c')]


def test_base_from_dockerfile(tmp_path):
    assert uc.base_from_dockerfile(_dockerfile(tmp_path, 'v2026.9.24')) == ('nousresearch/hermes-agent', 'v2026.9.24')

def test_base_from_real_dockerfile_parses():
    repo, tag = uc.base_from_dockerfile('Dockerfile')
    assert repo == 'nousresearch/hermes-agent' and re.fullmatch(r'v[\d.]+', tag)

def test_strip_sha():
    assert uc.strip_sha('v2026.9.24-6e01c6c') == 'v2026.9.24'
    assert uc.strip_sha('v2026.9.24') == 'v2026.9.24'
    assert uc.strip_sha('v1.2.3-abcdef0') == 'v1.2.3'

def test_old_bases_takes_oldest(tmp_path):
    paths = [_manifest(tmp_path, 'a', 'v2026.9.24-6e01c6c'), _manifest(tmp_path, 'b', 'v2026.9.14-0000000')]
    assert uc.old_bases(paths) == ('ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab', 'v2026.9.14')

def test_old_bases_real_manifests_parse():
    repo, tag = uc.old_bases(MANIFESTS)
    assert repo == 'ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab'
    assert re.fullmatch(r'v[\d.]+', tag)

def test_equal_tags_no_diff(tmp_path, monkeypatch):
    # old == new → no network call, exit 0
    monkeypatch.setattr(uc, 'fetch_compare', lambda *a, **k: (_ for _ in ()).throw(AssertionError('fetched')))
    rc = uc.main(['--dockerfile', _dockerfile(tmp_path, 'v2026.9.24'),
                  '--manifests', _manifest(tmp_path, 'a', 'v2026.9.24-6e01c6c')])
    assert rc == 0

def test_classify_bang_subject_is_hard():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'feat!: drop --insecure flag'}}], 'files': []}
    cls = uc.classify(p)
    assert cls['breaking_detected'] and cls['hard'] and not cls['soft']

def test_classify_breaking_footer_is_hard():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'feat: flag cleanup\n\nBREAKING CHANGE: --insecure is gone'}}], 'files': []}
    cls = uc.classify(p)
    assert cls['breaking_detected'] and any('BREAKING CHANGE' in l for l in cls['hard'])

def test_classify_changelog_added_breaking_marker_is_hard():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'docs: update changelog'}}],
         'files': [{'filename': 'CHANGELOG.md', 'patch': '+ ## v2\n+ - `--no-open` was removed (BREAKING)\n'}]}
    assert uc.classify(p)['breaking_detected']

def test_classify_changelog_added_keyword_is_soft_only():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'docs: update changelog'}}],
         'files': [{'filename': 'CHANGELOG.md', 'patch': '+ - `--no-open` is no longer supported\n'}]}
    cls = uc.classify(p)
    assert not cls['breaking_detected'] and cls['soft']

def test_classify_changelog_removed_lines_ignored():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'docs: update changelog'}}],
         'files': [{'filename': 'CHANGELOG.md', 'patch': '- removed `--no-open` (no longer supported, BREAKING)\n'}]}
    cls = uc.classify(p)
    assert not cls['breaking_detected'] and not cls['soft']

def test_classify_non_changelog_patch_ignored():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'refactor: cleanup'}}],
         'files': [{'filename': 'src/util.py', 'patch': '+ removed helper (BREAKING)\n'}]}
    cls = uc.classify(p)
    assert not cls['breaking_detected'] and not cls['soft']

def test_classify_commit_body_noise_not_flagged():
    # The v0.23.0 → v0.23.1 false-positive class: keyword hits in commit
    # message bodies (review notes, rebase notes, CI plumbing) must not fire.
    p = {'ahead_by': 1,
         'commits': [{'sha': 'a1b2c3d',
                      'commit': {'message': 'fix(ci): self-updater gate order\n\n'
                                            'The gate now runs before anything is removed; it requires the aux host pin.'}}],
         'files': []}
    cls = uc.classify(p)
    assert not cls['breaking_detected'] and not cls['soft']

def test_classify_subject_keyword_is_soft_only():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'chore: fixture now requires a pnpm pin'}}], 'files': []}
    cls = uc.classify(p)
    assert not cls['breaking_detected'] and cls['soft']

def test_classify_clean():
    p = {'ahead_by': 2, 'commits': [{'sha': 'a', 'commit': {'message': 'fix: typo'}}, {'sha': 'b', 'commit': {'message': 'feat: new tool'}}], 'files': []}
    assert not uc.classify(p)['breaking_detected']

def test_classify_release_notes_heading_is_hard():
    r = uc.classify_release('# Hermes Agent v2\n\n### Breaking changes\n- removed `--no-open` flag\n')
    assert r['hard'] and not r['soft']

def test_classify_release_notes_clean():
    r = uc.classify_release('# Hermes Agent v2\n\n## About this release\nSmall patch.\n')
    assert not r['hard'] and not r['soft']

def test_fetch_failure_exit_2(tmp_path, monkeypatch):
    monkeypatch.setattr(uc, 'fetch_compare', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('HTTP 404')))
    monkeypatch.setattr(uc, 'fetch_release', lambda *a, **k: None)
    rc = uc.main(_main_argv(tmp_path))
    assert rc == 2

def test_main_soft_only_exit_0(tmp_path, monkeypatch):
    payload = {'ahead_by': 1,
               'commits': [{'sha': 'a', 'commit': {'message': 'chore: fixture now requires a pnpm pin'}}],
               'files': []}
    monkeypatch.setattr(uc, 'fetch_compare', lambda *a, **k: payload)
    monkeypatch.setattr(uc, 'fetch_release', lambda *a, **k: None)
    assert uc.main(_main_argv(tmp_path)) == 0

def test_main_hard_exit_10(tmp_path, monkeypatch):
    payload = {'ahead_by': 1,
               'commits': [{'sha': 'a', 'commit': {'message': 'feat!: drop --insecure flag'}}],
               'files': []}
    monkeypatch.setattr(uc, 'fetch_compare', lambda *a, **k: payload)
    monkeypatch.setattr(uc, 'fetch_release', lambda *a, **k: None)
    assert uc.main(_main_argv(tmp_path)) == 10

def test_main_release_notes_block(tmp_path, monkeypatch):
    payload = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'feat: x'}}], 'files': []}
    monkeypatch.setattr(uc, 'fetch_compare', lambda *a, **k: payload)
    monkeypatch.setattr(uc, 'fetch_release',
                        lambda *a, **k: {'tag': 'v2026.9.24', 'body': '### Breaking changes\n- removed flag\n'})
    assert uc.main(_main_argv(tmp_path)) == 10

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

def test_render_comment_lists_soft_as_review():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'chore: now requires a restart'}}], 'files': []}
    text = uc.render_comment('r/o', 'a', 'b', uc.classify(p))
    assert 'Possible breaking changes' in text and 'not blocking' in text

def test_render_comment_no_soft_section_when_clean():
    p = {'ahead_by': 1, 'commits': [{'sha': 'a', 'commit': {'message': 'fix: typo'}}], 'files': []}
    text = uc.render_comment('r/o', 'a', 'b', uc.classify(p))
    assert 'Possible breaking changes' not in text and 'Breaking changes (blocking)' not in text

def test_render_comment_flags_truncated_compare():
    p = {'ahead_by': 5173, 'commits': [{'sha': f'c{i}', 'commit': {'message': 'fix'}} for i in range(250)]}
    text = uc.render_comment('r/o', 'a', 'b', uc.classify(p))
    assert 'only 250 of 5173 commits' in text

def test_render_comment_no_truncation_warning_when_complete():
    p = {'ahead_by': 2, 'commits': [{'sha': f'c{i}', 'commit': {'message': 'fix'}} for i in range(2)]}
    assert 'only' not in uc.render_comment('r/o', 'a', 'b', uc.classify(p))
