"""Read-only prerequisite checks for the packaged standalone Frame build.

Does not install software, contact services, enable debugging or modify settings.
Passing these checks is not a runtime compatibility or headset comfort guarantee.
"""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def command_output(args, stderr=False):
    # Steam launches with LD_PRELOAD=gameoverlayrenderer.so (x86 paths on ARM), so
    # every child prints ld.so warnings on stderr; 0.5.2 parsed those as the
    # Chrome ref and refused to start. Checks run without the preload and read
    # stdout unless the tool documents itself on stderr.
    env = {k: v for k, v in os.environ.items() if k != 'LD_PRELOAD'}
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8, env=env)
        return result.returncode, result.stdout + (result.stderr if stderr else '')
    except (OSError, subprocess.TimeoutExpired):
        return -1, ''


def check(root, *, system=None, machine=None, find=shutil.which, run=command_output,
          runtime_root=Path('/opt/steamvr'), uid=None):
    problems = []
    system = system or platform.system()
    machine = machine or platform.machine()
    if system != 'Linux' or machine.lower() not in ('aarch64', 'arm64'):
        return ['This package needs Steam Frame running SteamOS ARM64. It cannot run on this computer.']
    if (os.getuid() if uid is None else uid) == 0:
        problems.append('Start Frame Cinema as your normal user, without sudo.')
    if sys.version_info < (3, 11):
        problems.append('This build needs Python 3.11 or later.')
    for name in ('gamescope', 'flatpak'):
        if not find(name):
            problems.append(f'Required component is missing: {name}. See GETTING-STARTED.md.')
    if find('flatpak'):
        # Match the launcher's lookup: user and system installations, ARM64 only.
        code, ref = run(['flatpak', 'info', '--arch=aarch64', '--show-ref', 'com.google.Chrome'])
        parts = ref.strip().split('/')
        if code or len(parts) != 4 or parts[:3] != ['app', 'com.google.Chrome', 'aarch64'] or not parts[3]:
            problems.append('Google Chrome for ARM64 (Flatpak) could not be found. User and system installations are supported. See GETTING-STARTED.md.')
    if find('gamescope'):
        _, help_text = run(['gamescope', '--help'], stderr=True)
        required = ('--vr-overlay-key', '--virtual-connector-strategy', '--vr-overlay-enable-click-stabilization')
        if not all(flag in help_text for flag in required):
            problems.append('The installed Gamescope lacks options required by this build.')
    if not (runtime_root / 'steamxr_linuxarm64.json').is_file() or not (runtime_root / 'bin/linuxarm64/vrclient.so').is_file():
        problems.append('The SteamVR runtime required by this build is unavailable. Start Steam and check its installation.')
    for name in ('godot', 'panel_host', 'ambient_sampler', 'native-ui/native_ui_renderer'):
        path = root / name
        if not path.is_file():
            problems.append(f'The app package is incomplete: {name}. Download it again.')
            continue
        with path.open('rb') as stream:
            header = stream.read(20)
        if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
            problems.append(f'The app package contains the wrong executable: {name}. Download it again.')
        elif not os.access(path, os.X_OK):
            problems.append(f'The app executable cannot run: {name}. Reinstall using the supplied instructions.')
    return problems


if __name__ == '__main__':
    try:
        problems = check(Path(__file__).resolve().parent)
    except (OSError, ValueError):
        problems = ['Frame Cinema could not check its installation. See GETTING-STARTED.md.']
    if problems:
        print('Frame Cinema could not start:\n' + '\n'.join('- ' + p for p in problems), file=sys.stderr)
        raise SystemExit(2)
