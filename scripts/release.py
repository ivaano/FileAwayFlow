#!/usr/bin/env python3
"""Build a Linux x64 package and optionally publish it through a GitHub PR."""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile

if sys.version_info < (3, 11):
    sys.exit("Error: release.py requires Python 3.11 or newer")
import tomllib


def parse(version):
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", version
    )
    if not match:
        raise ValueError(f"Invalid SemVer: {version}")
    pre = match[4]
    if pre and any(p.isdigit() and len(p) > 1 and p[0] == "0" for p in pre.split('.')):
        raise ValueError(f"Invalid SemVer: {version}")
    return tuple(map(int, match.group(1, 2, 3))), pre


def compare(a, b):
    av, ap = parse(a)
    bv, bp = parse(b)
    if av != bv:
        return (av > bv) - (av < bv)
    if ap == bp:
        return 0
    if ap is None or bp is None:
        return 1 if ap is None else -1
    for x, y in zip(ap.split('.'), bp.split('.')):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return (int(x) > int(y)) - (int(x) < int(y))
        if x.isdigit() != y.isdigit():
            return -1 if x.isdigit() else 1
        return (x > y) - (x < y)
    return (len(ap.split('.')) > len(bp.split('.'))) - (len(ap.split('.')) < len(bp.split('.')))


def bump(root, version):
    manifest = root / 'Cargo.toml'
    lock = root / 'Cargo.lock'
    before = tomllib.loads(manifest.read_text())
    old = before['package']['version']
    name = before['package']['name']
    # Preserve formatting and every unrelated field. Validate both edits before writing.
    text = manifest.read_text()
    section = re.search(r'(?ms)^\[package\]\s*\n(.*?)(?=^\[|\Z)', text)
    if not section:
        raise ValueError('Cannot locate [package] section')
    body, count = re.subn(r'(?m)^version\s*=\s*"[^"]*"', f'version = "{version}"', section[1])
    if count != 1:
        raise ValueError('Expected exactly one package version')
    updated = text[:section.start(1)] + body + text[section.end(1):]
    expected = tomllib.loads(manifest.read_text())
    expected['package']['version'] = version
    if tomllib.loads(updated) != expected:
        raise ValueError('Unexpected manifest changes')
    lock_text = lock.read_text()
    lock_before = tomllib.loads(lock_text)
    entries = [p for p in lock_before['package'] if p['name'] == name and 'source' not in p]
    if len(entries) != 1 or entries[0]['version'] != old:
        raise ValueError('Expected one matching application entry in Cargo.lock')
    entries[0]['version'] = version
    pattern = r'(?ms)^\[\[package\]\]\s*\n(.*?)(?=^\[\[package\]\]|\Z)'
    def replace(match):
        entry = tomllib.loads('[package]\n' + match[1])['package']
        if entry.get('name') == name and 'source' not in entry:
            return '[[package]]\n' + re.sub(r'(?m)^version = "[^"]*"', f'version = "{version}"', match[1])
        return match[0]
    updated_lock = re.sub(pattern, replace, lock_text)
    if tomllib.loads(updated_lock) != lock_before:
        raise ValueError('Unexpected dependency changes in Cargo.lock')
    manifest.write_text(updated)
    lock.write_text(updated_lock)


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Release:
    def __init__(self, repo, version, publish):
        self.repo = repo
        self.version = version
        self.publish = publish
        self.package = f'fileawayflow-{version}-linux-x64'
        self.archive = repo / 'dist' / f'{self.package}.tar.gz'
        self.source = repo
        self.target = repo / 'target'
        self.tag = f'v{version}'
        self.branch = f'release/{self.tag}'
        self.github_repo = ''
        self.pr_url = ''
        self.release_url = ''
        self.sha = ''
        self.previous_tag = ''
        self.branch_created = False
        self.branch_pushed = False
        self.tag_created = False
        self.tag_pushed = False
        self.prerelease = False

    def run(self, *args, cwd=None, capture=True, check=True, env=None):
        result = subprocess.run(
            [str(arg) for arg in args], cwd=cwd or self.repo, env=env,
            text=True, stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None, check=check,
        )
        return result.stdout.strip() if capture and check else result

    def git(self, *args, **kwargs):
        return self.run('git', *args, **kwargs)

    def gh(self, *args):
        return self.run('gh', *args)

    def ref_exists(self, ref):
        result = self.git('show-ref', '--verify', '--quiet', ref, check=False)
        require(result.returncode in (0, 1), f'could not inspect Git reference {ref}')
        return result.returncode == 0

    def check_available(self):
        require(not self.ref_exists(f'refs/tags/{self.tag}'), f'tag {self.tag} already exists locally')
        require(not self.git('ls-remote', '--tags', 'origin', f'refs/tags/{self.tag}'),
                f'tag {self.tag} already exists on origin')
        tags = self.gh('api', '--paginate', f'repos/{self.github_repo}/releases', '--jq', '.[].tag_name')
        require(self.tag not in tags.splitlines(), f'GitHub release {self.tag} already exists')

    def preflight(self):
        parse(self.version)
        require(not self.git('status', '--porcelain', '--untracked-files=all'),
                'publishing requires a clean working tree; commit and merge release inputs into main first')
        self.git('var', 'GIT_AUTHOR_IDENT')
        self.gh('auth', 'status')
        origin = self.git('remote', 'get-url', 'origin')
        self.github_repo = self.gh('repo', 'view', origin, '--json', 'nameWithOwner', '--jq', '.nameWithOwner')
        require(self.github_repo, 'could not resolve GitHub repository from origin')
        permission = self.gh('api', f'repos/{self.github_repo}', '--jq', '.permissions.push')
        require(permission == 'true', 'GitHub identity requires repository write access to create tags and releases')
        self.prerelease = parse(self.version)[1] is not None
        self.check_available()
        self.git('fetch', 'origin', '+refs/heads/main:refs/remotes/origin/main', '--tags')
        self.check_available()
        require(not self.git('ls-remote', '--heads', 'origin', f'refs/heads/{self.branch}'),
                f'remote branch {self.branch} already exists; inspect its PR before retrying')
        require(not self.ref_exists(f'refs/heads/{self.branch}'),
                f'local branch {self.branch} already exists; inspect it before retrying')
        self.git('push', '--dry-run', 'origin', f'refs/remotes/origin/main:refs/heads/{self.branch}')

    def build(self, test=False):
        if test:
            self.run('cargo', 'test', '--manifest-path', self.source / 'Cargo.toml',
                     '--locked', '--target-dir', self.target, cwd=self.source, capture=False)
        env = {**os.environ, 'CARGO_PROFILE_RELEASE_OPT_LEVEL': '3',
               'CARGO_PROFILE_RELEASE_LTO': 'thin', 'CARGO_PROFILE_RELEASE_CODEGEN_UNITS': '1',
               'CARGO_PROFILE_RELEASE_STRIP': 'symbols'}
        self.run('cargo', 'build', '--manifest-path', self.source / 'Cargo.toml',
                 '--locked', '--release', '--target', 'x86_64-unknown-linux-gnu',
                 '--target-dir', self.target, '--bin', 'file_away_flow',
                 cwd=self.source, capture=False, env=env)
        if self.publish:
            require(self.run(self.binary, '--version') == f'Version {self.version}',
                    'built binary version does not match requested version')

    @property
    def binary(self):
        return self.target / 'x86_64-unknown-linux-gnu/release/file_away_flow'

    def prepare_version(self, temporary):
        current = tomllib.loads((self.source / 'Cargo.toml').read_text())['package']['version']
        ordering = compare(self.version, current)
        require(ordering >= 0, f'requested version {self.version} is older than main\'s {current}')
        require(ordering != 0 or self.version == current,
                'requested version differs only in build metadata; use a newer SemVer or the exact current version')
        if self.version == current:
            self.sha = self.git('rev-parse', 'HEAD', cwd=self.source)
            return
        self.git('switch', '-c', self.branch, cwd=self.source)
        self.branch_created = True
        bump(self.source, self.version)
        self.build(test=True)
        require(self.git('diff', '--name-only', cwd=self.source).splitlines() == ['Cargo.lock', 'Cargo.toml'],
                'version bump produced unexpected changed files')
        require(not self.git('ls-files', '--others', '--exclude-standard', cwd=self.source),
                'version bump produced unexpected untracked files')
        self.git('diff', '--check', cwd=self.source)
        self.git('add', '--', 'Cargo.toml', 'Cargo.lock', cwd=self.source)
        self.git('commit', '-m', f'chore: bump version to {self.version}', cwd=self.source)
        head = self.git('rev-parse', 'HEAD', cwd=self.source)
        self.git('push', 'origin', f'HEAD:refs/heads/{self.branch}', cwd=self.source)
        self.branch_pushed = True
        body = temporary / 'pr-body.md'
        body.write_text(f'Bump the application version to {self.version} in Cargo.toml and Cargo.lock.\n\n'
                        'Validation: locked tests and optimized Linux x64 build passed; dependency versions are unchanged.\n')
        self.pr_url = self.gh('pr', 'create', '--repo', self.github_repo, '--base', 'main',
                              '--head', self.branch, '--title', f'chore: bump version to {self.version}',
                              '--body-file', body)
        print(f'Created PR: {self.pr_url}', flush=True)
        self.gh('pr', 'merge', self.pr_url, '--repo', self.github_repo, '--squash', '--match-head-commit', head)
        state = self.gh('pr', 'view', self.pr_url, '--repo', self.github_repo, '--json', 'state', '--jq', '.state')
        require(state == 'MERGED', f'PR is not merged; inspect {self.pr_url} before releasing')
        self.sha = self.gh('pr', 'view', self.pr_url, '--repo', self.github_repo,
                           '--json', 'mergeCommit', '--jq', '.mergeCommit.oid')
        require(re.fullmatch(r'[0-9a-f]{40}', self.sha), 'GitHub did not return a valid merge commit')
        self.git('fetch', 'origin', '+refs/heads/main:refs/remotes/origin/main')
        self.git('merge-base', '--is-ancestor', self.sha, 'refs/remotes/origin/main')
        self.git('checkout', '--detach', self.sha, cwd=self.source)

    def previous_version_tag(self):
        matches = []
        for tag in self.git('tag', '--merged', self.sha).splitlines():
            if tag.startswith('v'):
                try:
                    parse(tag[1:])
                except ValueError:
                    continue
                matches.extend(['--match', tag])
        return self.git('describe', '--tags', '--abbrev=0', *matches, self.sha) if matches else ''

    def package_archive(self):
        self.archive.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.release.', dir=self.archive.parent) as temporary:
            staging = Path(temporary)
            package = staging / self.package
            (package / 'examples').mkdir(parents=True)
            shutil.copyfile(self.binary, package / 'fileawayflow')
            (package / 'fileawayflow').chmod(0o755)
            shutil.copyfile(self.source / 'scripts/packaging/fileaway.service', package / 'examples/fileaway.service')
            (package / 'examples/fileaway.service').chmod(0o644)
            packed = staging / 'archive.tar.gz'
            with tarfile.open(packed, 'w:gz') as archive:
                archive.add(package, arcname=self.package)
            # Publish atomically without overwriting another process's archive.
            os.link(packed, self.archive)
        print(f'Created {self.archive}', flush=True)

    def publish_release(self):
        self.check_available()
        self.git('tag', '-a', self.tag, self.sha, '-m', f'FileAwayFlow {self.version}')
        self.tag_created = True
        self.git('push', 'origin', f'refs/tags/{self.tag}:refs/tags/{self.tag}')
        self.tag_pushed = True
        notes = ['--generate-notes']
        if self.previous_tag:
            notes += ['--notes-start-tag', self.previous_tag]
        self.release_url = self.gh('release', 'create', self.tag, self.archive, '--repo', self.github_repo,
                                   '--verify-tag', '--draft', '--title', f'FileAwayFlow {self.version}',
                                   f'--prerelease={str(self.prerelease).lower()}', *notes)
        uploaded = self.gh('release', 'view', self.tag, '--repo', self.github_repo, '--json', 'assets',
                           '--jq', f'.assets[] | select(.name == "{self.package}.tar.gz" and .size > 0) | .name')
        require(uploaded == self.archive.name, 'draft release does not contain the expected archive')
        self.gh('release', 'edit', self.tag, '--repo', self.github_repo, '--draft=false')
        print(f'Published commit {self.sha} as {self.tag}\nRelease: {self.release_url}', flush=True)

    def recovery(self):
        print('Publishing stopped. Existing archives and remote changes were preserved.', file=sys.stderr)
        def command(label, *args):
            print(f'{label}: {shlex.join([str(arg) for arg in args])}', file=sys.stderr)
        if self.archive.exists():
            print(f'Archive: {self.archive}', file=sys.stderr)
        if self.branch_created:
            command('Inspect version branch', 'git', '-C', self.repo, 'show', self.branch)
        if self.branch_pushed:
            command('Inspect remote PRs', 'gh', 'pr', 'list', '--repo', self.github_repo, '--head', self.branch, '--base', 'main')
        if self.pr_url:
            print(f'PR: {self.pr_url}', file=sys.stderr)
        if self.tag_created and not self.tag_pushed:
            command('Verify local tag', 'git', '-C', self.repo, 'show', self.tag)
            command('Push the verified tag', 'git', '-C', self.repo, 'push', 'origin', f'refs/tags/{self.tag}:refs/tags/{self.tag}')
        if self.tag_pushed:
            print(f'Remote tag: {self.tag} (commit {self.sha})', file=sys.stderr)
            command('Inspect release', 'gh', 'release', 'view', self.tag, '--repo', self.github_repo)
            notes = ['--notes-start-tag', self.previous_tag] if self.previous_tag else []
            command('If no release exists, create a draft', 'gh', 'release', 'create', self.tag, self.archive,
                    '--repo', self.github_repo, '--verify-tag', '--draft', '--generate-notes',
                    f'--prerelease={str(self.prerelease).lower()}', *notes)
            command('If a draft exists, upload any missing asset', 'gh', 'release', 'upload', self.tag, self.archive, '--repo', self.github_repo)
            command('After verifying the asset, publish', 'gh', 'release', 'edit', self.tag, '--repo', self.github_repo, '--draft=false')

    def execute(self):
        for dependency in ['cargo'] + (['git', 'gh'] if self.publish else []):
            require(shutil.which(dependency), f'required dependency {dependency} is not installed or not on PATH')
        require(not os.path.lexists(self.archive), f'refusing to overwrite {self.archive}')
        try:
            if not self.publish:
                self.build()
                self.package_archive()
                return
            self.preflight()
            with tempfile.TemporaryDirectory(prefix='fileawayflow-release-') as temporary:
                temporary = Path(temporary)
                self.source = temporary / 'source'
                self.target = self.repo / 'target/publish' / temporary.name
                self.git('worktree', 'add', '--detach', self.source, 'refs/remotes/origin/main')
                try:
                    self.prepare_version(temporary)
                    current = tomllib.loads((self.source / 'Cargo.toml').read_text())['package']['version']
                    require(current == self.version, 'release commit version differs from requested version')
                    self.previous_tag = self.previous_version_tag()
                    self.build(test=True)
                    self.package_archive()
                    self.publish_release()
                finally:
                    result = self.git('worktree', 'remove', '--force', self.source, check=False)
                    if result.returncode:
                        print(f'Warning: could not unregister worktree {self.source}: {result.stderr}', file=sys.stderr)
        except BaseException:
            if self.publish:
                self.recovery()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', help='package version; publishing requires SemVer without a leading v')
    parser.add_argument('--publish', action='store_true', help='merge a version-bump PR when needed and publish to GitHub')
    args = parser.parse_args()
    if sys.argv.count('--publish') > 1:
        parser.error('--publish may only be specified once')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]*', args.version):
        parser.error('version must begin with a letter or digit and contain only letters, digits, ., _, +, or -')
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        Release(Path(__file__).resolve().parent.parent, args.version, args.publish).execute()
    except subprocess.CalledProcessError as error:
        print(f'Error: {shlex.join(error.cmd)} failed (exit {error.returncode}).', file=sys.stderr)
        if error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
