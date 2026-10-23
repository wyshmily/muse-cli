#!/usr/bin/env python3
"""Pinned Muse source bootstrap / credential-free doctor; never recovers login.
Run only on an independently verified, authorized repository/commit.
bootstrap needs registry access; doctor performs offline checks only.
"""
import argparse
import io
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile


def run(argv, *, cwd=None, env=None, log=None, expected=0):
    p = subprocess.run([str(x) for x in argv], cwd=cwd, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if log:
        Path(log).write_text(p.stdout + p.stderr)
    if p.returncode != expected:
        raise RuntimeError(f'{Path(str(argv[0])).name} failed (exit {p.returncode}); see local logs')
    return p.stdout


def isolated_env(root):
    # Do not inherit Muse identity/cookies, GUI/keyring access, Python hooks.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MUSE_', 'PYTHON', 'XDG_', 'DBUS_'))
           and k not in ('DISPLAY', 'WAYLAND_DISPLAY')}
    home = root / 'empty-home'
    home.mkdir(exist_ok=True)
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
               MUSE_NO_UPDATE_CHECK='1', PYTHONDONTWRITEBYTECODE='1',
               DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent-muse-local-test-bus')
    return env


def doctor(root, commit):
    if (root / 'SOURCE-COMMIT').read_text().strip() != commit:
        raise RuntimeError('Runtime source commit does not match')
    source, logs = root / 'source', root / 'logs'
    logs.mkdir(exist_ok=True)
    env = isolated_env(root)
    py = root / 'venv/bin/python'
    run([py, source / 'tools/verify_source.py', source], env=env, log=logs / 'manifest.txt')
    installed = Path(run([py, '-c', 'import muse_cli; print(muse_cli.__file__)'], env=env).strip()).parent
    # Compare every shipped package file, not just the shared version string.
    source_files = {p.relative_to(source / 'src/muse_cli') for p in (source / 'src/muse_cli').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    installed_files = {p.relative_to(installed) for p in installed.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if source_files != installed_files:
        raise RuntimeError('Installed package file inventory differs from pinned source snapshot')
    count = 0
    for original in (source / 'src/muse_cli').rglob('*'):
        if not original.is_file() or '__pycache__' in original.parts:
            continue
        target = installed / original.relative_to(source / 'src/muse_cli')
        if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
            raise RuntimeError('Installed package differs from pinned source snapshot')
        count += 1
    (logs / 'installed-snapshot.txt').write_text(f'{count} package files match pinned source snapshot\n')
    checks = [('muse-cli', ['--version'], 'version.txt'),
              ('muse-cli', ['--help'], 'cli-help.txt'),
              ('muse-login', ['--help'], 'login-help.txt'),
              ('muse-read', ['--help'], 'read-help.txt'),
              ('muse-read', ['discover'], 'discover.json'),
              ('muse-read', ['describe', 'quota'], 'describe-quota.json'),
              ('muse-read', ['capabilities', '--limit', '1'], 'capabilities.json')]
    for cmd, args, name in checks:
        run([root / 'venv/bin' / cmd, *args], env=env, log=logs / name)
    # Known unavailable synthetic bus: fail closed before any account/network use.
    for cmd, args, error in [
        ('muse-login', ['preflight', '--store', 'secretservice'], 'STORE_UNAVAILABLE'),
        ('muse-read', ['sessions'], 'STORE_UNAVAILABLE'),
    ]:
        path = logs / (cmd + '-no-store.txt')
        run([root / 'venv/bin' / cmd, *args], env=env, log=path, expected=2)
        if error not in path.read_text():
            raise RuntimeError('Unexpected no-store diagnostic')
    run([py, '-m', 'unittest', 'discover', '-s', str(source / 'tests'), '-v'],
        cwd=source, env=env, log=logs / 'tests.txt')
    run([py, '-m', 'pip', 'freeze'], env=env, log=logs / 'requirements-observed.txt')
    print(json.dumps({'status': 'offline_checks_passed', 'commit': commit,
                      'runtime': str(root), 'credentials_used': False,
                      'live_gateway_verified': False}))


def main():
    if sys.version_info < (3, 12):
        raise RuntimeError('This Linux cloud bootstrap tool requires Python 3.12+; library requirements are unchanged')
    if not sys.platform.startswith('linux'):
        raise RuntimeError('This bootstrap tool is tested for Linux cloud runtimes only')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['bootstrap', 'doctor'])
    p.add_argument('--commit', required=True, help='Independently verified full commit SHA')
    p.add_argument('--runtime', required=True, type=Path, help='New directory for bootstrap')
    p.add_argument('--source', type=Path, help='Existing trusted Git checkout; bootstrap only')
    a = p.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', a.commit):
        p.error('Full lowercase 40-character commit SHA required')
    root = a.runtime.resolve()
    if a.mode == 'bootstrap':
        if not a.source or root.exists():
            p.error('bootstrap requires --source and a nonexistent --runtime directory')
        source = a.source.resolve()
        actual = run(['git', '-C', source, 'rev-parse', a.commit + '^{commit}']).strip()
        if actual != a.commit:
            raise RuntimeError('Source commit mismatch')
        # Archive committed files, never a mutable working tree or .git secrets.
        archive = subprocess.check_output(['git', '-C', str(source), 'archive', a.commit])
        root.mkdir(parents=True)
        (root / 'source').mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root / 'source', filter='data')
        (root / 'SOURCE-COMMIT').write_text(a.commit + '\n')
        logs = root / 'logs'
        logs.mkdir()
        env = isolated_env(root)
        # Manifest checked BEFORE package build/install.
        run([sys.executable, root / 'source/tools/verify_source.py', root / 'source'],
            env=env, log=logs / 'manifest-before-install.txt')
        run([sys.executable, '-m', 'venv', root / 'venv'], log=logs / 'venv.txt')
        run([root / 'venv/bin/python', '-m', 'pip', 'install', '--disable-pip-version-check',
             '--retries', '0', '--timeout', '30', str(root / 'source') + '[linux-login]'],
            env=env, log=logs / 'install.txt')
    doctor(root, a.commit)

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
