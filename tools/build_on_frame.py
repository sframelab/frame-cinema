#!/usr/bin/env python3
"""Build, check and package Frame Cinema, then optionally install it.

Run on a Steam Frame in Desktop Mode after fetching the release assets with
tools/fetch_assets.py.

    python3 tools/build_on_frame.py             # build and package into dist/<version>/
    python3 tools/build_on_frame.py --install   # build, then run the installer

Build steps:
 1. Checks that every file in assets.json is in place.
 2. Runs the installer's own tests (release/test_*.py).
 3. Copies app/ to build/<version>/project and checks the Observation Deck's
    files against app/starship/package.json.
 4. Imports Godot resources and runs headless checks with XR off, using a
    separate data folder for test settings.
 5. Runs release/build_public.py to make the installer, its archive and the
    double-click launcher in dist/<version>/.
 6. With --install: refuses if Frame Cinema is open or the headset is being worn,
    or if this version is already installed (installers never overwrite a
    version; change "version" in app/cinema.gd first). Installing restarts Steam.

Use --skip-tests --skip-godot to check packaging on a PC. That skips steps 2
and 4, so install only what you built on the headset.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
APP = REPO / 'app'
RELEASE = REPO / 'release'
STEAMVR_LIBS = '/opt/steamvr/bin/linuxarm64'


def say(text):
    print(text, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def run(label, command, cwd, env, log_dir, timeout=900, script_errors=True):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                            stdin=subprocess.DEVNULL)
    output = result.stdout + result.stderr
    (log_dir / (label + '.log')).write_text(output)
    if result.returncode != 0 or (script_errors and ('Parse Error' in output or 'SCRIPT ERROR' in output)):
        sys.exit(f'{label} failed. The last lines of {log_dir / (label + ".log")}:\n{output[-3000:]}')
    say(f'{label}: passed')
    return result.stdout


def app_version():
    found = re.search(r'"version": "([^"]+)"', (APP / 'cinema.gd').read_text())
    if not found:
        sys.exit('Cannot find "version" in app/cinema.gd.')
    return found.group(1)


def check_assets():
    manifest = json.loads((REPO / 'assets.json').read_text())
    missing = [p for p, e in manifest['files'].items()
               if not (REPO / p).is_file() or (REPO / p).stat().st_size != e['bytes']]
    if missing:
        sys.exit(f'{len(missing)} data files are missing (first: {missing[0]}). '
                 'Run: python3 tools/fetch_assets.py <Frame Cinema installer>')
    say(f'assets: all {len(manifest["files"])} files in place')


def check_deck(project):
    deck = project / 'starship'
    package = json.loads((deck / 'package.json').read_text())
    for name, entry in package['files'].items():
        path = deck / name
        if not path.is_file() or path.stat().st_size != entry['bytes'] or sha256(path) != entry['sha256']:
            sys.exit('Observation Deck file differs from app/starship/package.json: ' + name +
                     '\nIf you changed it on purpose, update its entry (bytes and sha256) in package.json.')
    listed = set(package['files']) | {'package.json'}
    extra = sorted(p.name for p in deck.iterdir() if p.is_file() and p.name not in listed and not p.name.endswith('.uid'))
    if extra:
        sys.exit('app/starship has files its package.json does not list: ' + ', '.join(extra))
    say(f'observation-deck-files: {len(listed)} files match package.json')


def app_is_open():
    return subprocess.run(['pgrep', '-f', r'[f]rame-cinema/app/versions/.*/godot'], capture_output=True).returncode == 0


def headset_worn():
    status = Path.home() / '.local/share/FrameCinema/scene-status.json'
    try:
        return int(json.loads(status.read_text()).get('session_state') or 0) >= 4
    except (OSError, ValueError):
        return False


def installed_versions():
    state = Path.home() / '.local/share/frame-cinema/app/state.json'
    try:
        data = json.loads(state.read_text())
        return {data.get('current'), data.get('previous')} - {None}
    except (OSError, ValueError):
        return set()


def main():
    parser = argparse.ArgumentParser(description='Build, check and package Frame Cinema.')
    parser.add_argument('--install', action='store_true', help='install the package after building it')
    parser.add_argument('--skip-tests', action='store_true', help='do not run the installer tests')
    parser.add_argument('--skip-godot', action='store_true', help='do not import or run the Godot checks (PC trial only)')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        sys.exit('Needs Python 3.11 or later.')
    version = app_version()
    say(f'Frame Cinema {version}')
    check_assets()
    build = REPO / 'build' / version
    project = build / 'project'
    dist = REPO / 'dist' / version
    build.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OMP_WAIT_POLICY='PASSIVE', XDG_DATA_HOME=str(build / 'build-data'),
               LD_LIBRARY_PATH=STEAMVR_LIBS + (':' + os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else ''))

    if not args.skip_tests:
        run('release-tests', [sys.executable, '-m', 'unittest', 'test_installer', 'test_steam_shortcut',
                              'test_desktop_launcher', 'test_chrome_launch', 'test_service_profiles'],
            RELEASE, env, build, script_errors=False)

    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(APP, project, ignore=shutil.ignore_patterns('__pycache__'))
    check_deck(project)
    godot = project / 'godot'
    godot.chmod(0o755)

    if not args.skip_godot:
        base = [str(godot), '--headless', '--path', str(project), '--xr-mode', 'off']
        extensions = (project / '.godot/extension_list.cfg').read_bytes()
        run('picture-fit', base + ['--script', 'res://test_picture_fit.gd'], project, env, build)
        run('import', base + ['--editor', '--import'], project, env, build)
        # The editor import rewrites the extension list; the shipped one is the pinned list.
        (project / '.godot/extension_list.cfg').write_bytes(extensions)
        run('observation-deck', base + ['--audio-driver', 'Dummy', '--script', 'res://test_starship_surround.gd'], project, env, build)

    if dist.exists():
        shutil.rmtree(dist)
    say(run('package', [sys.executable, str(RELEASE / 'build_public.py'), '--project', str(project), '--output', str(dist)],
            RELEASE, env, build, script_errors=False)[-1500:])
    built = json.loads((dist / f'frame-cinema-{version}.json').read_text())
    say(f'Built {dist / built["installer"]} ({built["installer_bytes"]:,} bytes)')

    if not args.install:
        say('To install it, copy both files in that folder to the headset and double-click "Install Frame Cinema",\n'
            'or run this script again with --install on the headset.')
        return
    if version in installed_versions():
        sys.exit(f'{version} is already installed, and the installer never overwrites a version. '
                 'Raise "version" in app/cinema.gd and build again.')
    if app_is_open():
        sys.exit('Frame Cinema is open. Close it first; installing restarts Steam.')
    if headset_worn():
        sys.exit('The last session ended with the headset on. Take it off (or start and close Frame Cinema once), then try again.')
    result = subprocess.run(['sh', str(dist / built['installer'])], env=dict(os.environ, FRAME_CINEMA_INSTALLER_TERMINAL='1'),
                            capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)
    (build / 'install.log').write_text(result.stdout + result.stderr)
    say((result.stdout + result.stderr)[-1500:])
    if result.returncode != 0:
        sys.exit('Install failed; see ' + str(build / 'install.log'))
    say('Installed. Steam restarts; start Frame Cinema from your library.')


if __name__ == '__main__':
    main()
