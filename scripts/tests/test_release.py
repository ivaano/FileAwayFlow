#!/usr/bin/env python3
"""Release integration tests: real temporary Git repositories, mocked Cargo/GitHub."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
REAL_GIT = shutil.which('git')


def mock(tool, args):
    state = Path(os.environ['RELEASE_TEST_STATE'])
    with (state / 'calls').open('a') as log:
        log.write(json.dumps([tool, *args]) + '\n')
    scenario = os.environ.get('RELEASE_TEST_SCENARIO', '')
    remote = os.environ['RELEASE_TEST_REMOTE']
    def git(*command):
        return subprocess.check_output([REAL_GIT, '--git-dir', remote, *command], text=True).strip()
    if tool == 'cargo':
        if scenario == 'build-failure' and args[0] == 'build':
            return 42
        if scenario == 'test-failure' and args[0] == 'test':
            return 43
        manifest = Path(args[args.index('--manifest-path') + 1])
        version = tomllib.loads(manifest.read_text())['package']['version']
        if args[0] == 'build':
            if scenario == 'wrong-version':
                version = '0.0.0'
            target = Path(args[args.index('--target-dir') + 1])
            binary = target / 'x86_64-unknown-linux-gnu/release/file_away_flow'
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text(f'#!/bin/sh\nprintf "Version {version}\\n"\n')
            binary.chmod(0o755)
        return 0
    if args[:2] == ['auth', 'status']:
        return 1 if scenario == 'auth-failure' else 0
    if args[:2] == ['repo', 'view']:
        print('owner/project')
    elif args[0] == 'api':
        endpoint = next(a for a in args[1:] if a.startswith('repos/'))
        if endpoint.endswith('/releases'):
            if scenario == 'api-failure':
                return 1
            if scenario == 'existing-release' or (state / 'draft').exists():
                print(os.environ['RELEASE_TEST_TAG'])
        else:
            print('false' if scenario == 'no-permission' else 'true')
    elif args[:2] == ['pr', 'create']:
        (state / 'pr').write_text('created')
        print('https://github.com/owner/project/pull/1')
    elif args[:2] == ['pr', 'merge']:
        if scenario in ('blocked-merge', 'changed-head'):
            return 1
        if scenario == 'pending-merge':
            return 0
        branch = os.environ['RELEASE_TEST_BRANCH']
        expected = args[args.index('--match-head-commit') + 1]
        assert git('rev-parse', branch) == expected
        tree = git('rev-parse', branch + '^{tree}')
        parent = git('rev-parse', 'main')
        merged = git('commit-tree', tree, '-p', parent, '-m', 'squashed bump')
        git('update-ref', 'refs/heads/main', merged)
        (state / 'merged').write_text(merged)
        # Simulate main moving after the merge. Packaging must use the PR merge SHA.
        if scenario == 'moving-main':
            later = git('commit-tree', tree, '-p', merged, '-m', 'subsequent main change')
            git('update-ref', 'refs/heads/main', later)
    elif args[:2] == ['pr', 'view']:
        if args[-1] == '.state':
            print('MERGED' if (state / 'merged').exists() else 'OPEN')
        else:
            print((state / 'merged').read_text())
    elif args[:2] == ['release', 'create']:
        if scenario == 'release-create-failure':
            return 1
        (state / 'draft').write_text('draft')
        if scenario == 'upload-failure':
            return 1
        (state / 'asset').write_text(Path(args[3]).name)
        print('https://github.com/owner/project/releases/tag/' + args[2])
    elif args[:2] == ['release', 'view']:
        if (state / 'asset').exists() and scenario != 'missing-asset':
            print((state / 'asset').read_text())
    elif args[:2] == ['release', 'edit']:
        if scenario == 'publish-failure':
            return 1
        (state / 'published').write_text('published')
    else:
        raise AssertionError(args)
    return 0


class VersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = runpy.run_path(str(ROOT / 'scripts/release.py'))

    def test_semver_precedence(self):
        versions = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta',
                    '1.0.0-beta', '1.0.0-beta.2', '1.0.0-beta.11',
                    '1.0.0-rc.1', '1.0.0', '1.0.1', '1.1.0', '2.0.0']
        for lower, higher in zip(versions, versions[1:]):
            with self.subTest(lower=lower, higher=higher):
                self.assertEqual(self.helper['compare'](lower, higher), -1)
                self.assertEqual(self.helper['compare'](higher, lower), 1)
        self.assertEqual(self.helper['compare']('1.0.0+build.1', '1.0.0+build.2'), 0)

    def test_semver_validation(self):
        for version in ('1.2', 'v1.2.3', '01.2.3', '1.2.3-01', '1.2.3-', '1.2.3+ab..cd'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.helper['parse'](version)
        for version in ('1.2.3', '1.2.3-rc.1+build.02', '0.0.0'):
            self.helper['parse'](version)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.remote = self.base / 'remote.git'
        self.state = self.base / 'state'
        self.state.mkdir()
        self.tools = self.base / 'bin'
        self.tools.mkdir()
        self.scratch = self.base / 'worktrees'
        self.scratch.mkdir()
        self.env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_AUTHOR_NAME': 'Release Tests',
                    'GIT_AUTHOR_EMAIL': 'tests@example.invalid', 'GIT_COMMITTER_NAME': 'Release Tests',
                    'GIT_COMMITTER_EMAIL': 'tests@example.invalid',
                    'RELEASE_TEST_STATE': str(self.state), 'RELEASE_TEST_REMOTE': str(self.remote),
                    'RELEASE_TEST_TAG': 'v1.2.0', 'RELEASE_TEST_BRANCH': 'release/v1.2.0',
                    'TMPDIR': str(self.scratch),
                    'PATH': str(self.tools) + ':' + os.environ['PATH']}
        for name in ('cargo', 'gh'):
            self.make_mock(name)
        self.git('init', '-b', 'main')
        subprocess.run([REAL_GIT, 'init', '--bare', str(self.remote)], check=True,
                       capture_output=True, env=self.env)
        (self.repo / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/release.py', self.repo / 'scripts/release.py')
        (self.repo / 'scripts/packaging').mkdir()
        shutil.copy2(ROOT / 'scripts/packaging/fileaway.service', self.repo / 'scripts/packaging/fileaway.service')
        (self.repo / '.gitignore').write_text('/target/\n/dist/\n')
        (self.repo / 'Cargo.toml').write_text('[package]\nname = "file_away_flow"\nversion = "1.1.0"\nedition = "2021"\n')
        (self.repo / 'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "bytes"\nversion = "1.11.1"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n\n[[package]]\nname = "file_away_flow"\nversion = "1.1.0"\ndependencies = ["bytes"]\n')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.git('tag', 'v1.0.0')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', 'origin', 'main', '--tags')
        self.git('switch', '-c', 'caller')
        self.before = self.git('rev-parse', 'HEAD')

    def make_mock(self, name):
        wrapper = self.tools / name
        # Python executable avoids dependence on a shell PATH in dependency tests.
        wrapper.write_text(f'#!{sys.executable}\nimport runpy, sys\nsys.argv = [{str(Path(__file__).resolve())!r}, "--mock", {name!r}, *sys.argv[1:]]\nrunpy.run_path({str(Path(__file__).resolve())!r}, run_name="__main__")\n')
        wrapper.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output([REAL_GIT, '-C', str(self.repo), *args], env=self.env,
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def run_script(self, version='1.2.0', scenario='', args=None, publish=True):
        self.env['RELEASE_TEST_SCENARIO'] = scenario
        self.env['RELEASE_TEST_TAG'] = 'v' + version
        self.env['RELEASE_TEST_BRANCH'] = 'release/v' + version
        command = [str(self.repo / 'scripts/release.py')]
        command += args if args is not None else [version] + (['--publish'] if publish else [])
        result = subprocess.run(command, cwd=self.base, env=self.env, capture_output=True, text=True)
        self.assertEqual(self.git('branch', '--show-current'), 'caller')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.before)
        self.assertEqual(len(self.git('worktree', 'list', '--porcelain').split('worktree ')), 2)
        self.assertFalse(list((self.repo / 'dist').glob('.release.*')))
        self.assertEqual(list(self.scratch.iterdir()), [])
        return result

    def calls(self):
        return [json.loads(line) for line in (self.state / 'calls').read_text().splitlines()] if (self.state / 'calls').exists() else []

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_version(self):
        result = self.run_script()
        self.assert_success(result)
        self.assertTrue((self.state / 'published').exists())
        calls = self.calls()
        create = next(c for c in calls if c[:3] == ['gh', 'release', 'create'])
        self.assertIn('--notes-start-tag', create)
        self.assertIn('v1.0.0', create)
        sha = self.git('rev-parse', 'v1.2.0^{commit}')
        self.assertEqual(sha, (self.state / 'merged').read_text())
        main_lock = tomllib.loads(self.git('show', sha + ':Cargo.lock'))
        self.assertEqual(main_lock['package'][0]['version'], '1.11.1')
        self.assertEqual(main_lock['package'][1]['version'], '1.2.0')
        self.assertEqual(self.git('diff', '--name-only', self.before, sha).splitlines(), ['Cargo.lock', 'Cargo.toml'])
        archive = self.repo / 'dist/fileawayflow-1.2.0-linux-x64.tar.gz'
        with tarfile.open(archive) as tar:
            base = 'fileawayflow-1.2.0-linux-x64'
            self.assertEqual(set(tar.getnames()), {base, base + '/examples', base + '/fileawayflow', base + '/examples/fileaway.service'})
            self.assertEqual(tar.getmember(base + '/fileawayflow').mode, 0o755)
            self.assertEqual(tar.extractfile(base + '/examples/fileaway.service').read(), (self.repo / 'scripts/packaging/fileaway.service').read_bytes())
            self.assertIn(b'Version 1.2.0', tar.extractfile(base + '/fileawayflow').read())

    def test_same_version_skips_pr(self):
        self.assert_success(self.run_script('1.1.0'))
        self.assertFalse((self.state / 'pr').exists())
        self.assertEqual(self.git('rev-parse', 'v1.1.0^{commit}'), self.before)

    def test_merge_sha_when_main_moves(self):
        self.assert_success(self.run_script(scenario='moving-main'))
        sha = self.git('rev-parse', 'v1.2.0^{commit}')
        self.assertEqual(sha, (self.state / 'merged').read_text())
        self.assertNotEqual(sha, self.git('rev-parse', 'origin/main'))

    def test_prerelease(self):
        self.assert_success(self.run_script('1.2.0-rc.1'))
        self.assertIn('--prerelease=true', next(c for c in self.calls() if c[:3] == ['gh', 'release', 'create']))

    def test_first_release(self):
        self.git('tag', '-d', 'v1.0.0')
        self.git('push', 'origin', ':refs/tags/v1.0.0')
        self.assert_success(self.run_script())
        self.assertNotIn('--notes-start-tag', next(c for c in self.calls() if c[:3] == ['gh', 'release', 'create']))

    def test_local_without_gh(self):
        (self.tools / 'gh').unlink()
        self.assert_success(self.run_script('package-name', publish=False))
        self.assertFalse(any(c[0] == 'gh' for c in self.calls()))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_invalid_arguments(self):
        for args in ([], [''], ['1', '2'], ['-x'], ['a/b'], ['1', '--publish', '--publish'], ['1', '--other']):
            with self.subTest(args=args):
                result = self.run_script(args=args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('usage:', result.stderr.lower())
        for version in ('hello', 'v1.2.0', '1.02.0', '1.2.0-01'):
            with self.subTest(version=version):
                self.assertNotEqual(self.run_script(version).returncode, 0)

    def test_older_or_metadata_only(self):
        for version in ('1.0.9', '1.1.0+build'):
            with self.subTest(version=version):
                self.assertNotEqual(self.run_script(version).returncode, 0)
        self.assertFalse((self.state / 'pr').exists())

    def test_dirty_tree(self):
        (self.repo / 'untracked').touch()
        self.assertIn('clean working tree', self.run_script().stderr)
        self.assertEqual(self.calls(), [])

    def test_existing_archive(self):
        (self.repo / 'dist').mkdir()
        archive = self.repo / 'dist/fileawayflow-1.2.0-linux-x64.tar.gz'
        archive.write_bytes(b'preserve')
        self.assertIn('refusing to overwrite', self.run_script().stderr)
        self.assertEqual(archive.read_bytes(), b'preserve')

    def test_local_tag(self):
        self.git('tag', 'v1.2.0')
        self.assertIn('already exists locally', self.run_script().stderr)

    def test_remote_tag(self):
        self.git('tag', 'v1.2.0')
        self.git('push', 'origin', 'v1.2.0')
        self.git('tag', '-d', 'v1.2.0')
        self.assertIn('already exists on origin', self.run_script().stderr)

    def test_branch_conflicts(self):
        self.git('branch', 'release/v1.2.0')
        self.assertIn('local branch', self.run_script().stderr)
        self.git('push', 'origin', 'release/v1.2.0')
        self.git('branch', '-D', 'release/v1.2.0')
        self.assertIn('remote branch', self.run_script().stderr)

    def test_missing_dependency(self):
        (self.tools / 'gh').unlink()
        # Remove system gh while retaining basic utilities needed before dependency validation.
        limited = self.base / 'limited'
        limited.mkdir()
        for tool in ('cargo', 'git', 'python3'):
            (limited / tool).symlink_to(shutil.which(tool, path=self.env['PATH']))
        self.env['PATH'] = str(limited)
        result = self.run_script()
        self.assertIn('dependency gh', result.stderr)

    def test_preflight_and_build_failures(self):
        # Remove an unpushed version branch before testing the next failure.
        cases = ('auth-failure', 'no-permission', 'api-failure', 'existing-release', 'build-failure', 'test-failure', 'wrong-version')
        for scenario in cases:
            with self.subTest(scenario=scenario):
                if self.git('branch', '--list', 'release/v1.2.0'):
                    self.git('branch', '-D', 'release/v1.2.0')
                result = self.run_script(scenario=scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((self.state / 'pr').exists())
                self.assertFalse((self.repo / 'dist/fileawayflow-1.2.0-linux-x64.tar.gz').exists())

    def test_blocked_merge(self):
        result = self.run_script(scenario='blocked-merge')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('https://github.com/owner/project/pull/1', result.stderr)
        self.assertFalse((self.state / 'draft').exists())
        self.assertEqual(self.git('tag', '--list', 'v1.2.0'), '')

    def test_changed_head(self):
        result = self.run_script(scenario='changed-head')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('tag', '--list', 'v1.2.0'), '')

    def test_pending_merge(self):
        result = self.run_script(scenario='pending-merge')
        self.assertIn('PR is not merged', result.stderr)
        self.assertEqual(self.git('tag', '--list', 'v1.2.0'), '')

    def test_packaging_failure(self):
        (self.repo / 'scripts/packaging/fileaway.service').unlink()
        self.git('add', '-u')
        self.git('commit', '-m', 'missing service fixture')
        self.before = self.git('rev-parse', 'HEAD')
        self.git('push', 'origin', 'HEAD:main')
        result = self.run_script('1.1.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / 'dist/fileawayflow-1.1.0-linux-x64.tar.gz').exists())
        self.assertEqual(self.git('tag', '--list', 'v1.1.0'), '')

    def test_upload_failure(self):
        result = self.run_script(scenario='upload-failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.state / 'draft').exists())
        self.assertFalse((self.state / 'published').exists())
        self.assertIn('gh release upload', result.stderr)
        self.assertTrue((self.repo / 'dist/fileawayflow-1.2.0-linux-x64.tar.gz').exists())
        self.assertEqual(self.git('rev-parse', 'v1.2.0^{commit}'), (self.state / 'merged').read_text())

    def test_missing_asset(self):
        result = self.run_script(scenario='missing-asset')
        self.assertIn('expected archive', result.stderr)
        self.assertFalse((self.state / 'published').exists())

    def test_release_creation_failure(self):
        result = self.run_script(scenario='release-create-failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('gh release create', result.stderr)
        self.assertFalse((self.state / 'published').exists())

    def test_publish_failure(self):
        result = self.run_script(scenario='publish-failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.state / 'draft').exists())
        self.assertFalse((self.state / 'published').exists())
        self.assertIn('gh release edit', result.stderr)

    def test_tag_push_failure(self):
        hook = self.remote / 'hooks/update'
        hook.write_text('#!/bin/sh\ncase "$1" in refs/tags/*) exit 1 ;; esac\n')
        hook.chmod(0o755)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Push the verified tag:', result.stderr)
        self.assertFalse((self.state / 'draft').exists())
        self.assertTrue((self.repo / 'dist/fileawayflow-1.2.0-linux-x64.tar.gz').exists())
        self.assertEqual(self.git('ls-remote', '--tags', 'origin', 'refs/tags/v1.2.0'), '')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--mock']:
        sys.exit(mock(sys.argv[2], sys.argv[3:]))
    unittest.main()
