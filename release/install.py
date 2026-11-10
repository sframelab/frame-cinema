#!/usr/bin/env python3
"""Frame Cinema per-user installer. No root; user data is deleted only on request.

Install:   python3 install.py install <archive.tar.gz>   (review packages: --allow-review)
           Adds "Frame Cinema" with artwork to every local Steam user's library
           (--no-steam to skip) and "Uninstall Frame Cinema" to the desktop menu.
Manage:    python3 <root>/manage.py status|rollback|steam|uninstall [--remove-data]
           uninstall-gui asks with dialogs (the desktop menu entry runs it).
Launch:    <root>/launch

Steam rewrites shortcuts.vdf when it exits, so the running client is asked to
shut down, the entry is written as the old process ends, and the session's new
Steam client (or one started here in a plain desktop session) loads it.
Uninstall removes only what this installer added.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time

OWNER = 'frame-cinema-install-v1\n'
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?')
MAX_SIZE = 4 * 1024**3


def safe_path(root, name):
    parts = PurePosixPath(name)
    if not name or parts.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')) or '\\' in name or ':' in name:
        raise ValueError('Invalid package path.')
    path = root.joinpath(*parts.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes installation.')
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Symlinks are not accepted in managed paths.')
    return path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic(path, text, mode=0o600):
    descriptor, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def state(root):
    path = safe_path(root, 'state.json')
    data = json.loads(path.read_text()) if path.exists() else {'current': None, 'previous': None}
    for key in ('current', 'previous'):
        if data.get(key) is not None and not VERSION.fullmatch(data[key]):
            raise ValueError('Invalid installation state.')
    return data


@contextmanager
def locked(root, create=False):
    import fcntl
    if root.is_symlink() or root != root.resolve():
        raise ValueError('Use a real installation path without symlink parents.')
    if not root.exists():
        if not create:
            raise ValueError('No managed installation at this location.')
        root.mkdir(parents=True, mode=0o700)
    marker = safe_path(root, '.frame-cinema-owner')
    if not marker.exists():
        if not create or any(root.iterdir()):
            raise ValueError('Refusing to use a nonempty, unrecognized installation directory.')
        marker.write_text(OWNER)
    if marker.read_text() != OWNER:
        raise ValueError('Unrecognized installation owner.')
    with safe_path(root, '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Frame Cinema is running or another installation operation is active.') from None
        yield


def inspect_package(archive, allow_review):
    members = archive.getmembers()
    if len(members) > 4096:
        raise ValueError('Too many package files.')
    mapping = {}
    for member in members:
        safe_path(Path('/package-validation'), member.name)
        if not member.isfile() or member.name in mapping or member.size > MAX_SIZE:
            raise ValueError('Package contains a link, duplicate, non-file or oversized entry.')
        mapping[member.name] = member
    if 'package.json' not in mapping or mapping['package.json'].size > 1024**2:
        raise ValueError('Missing or oversized package manifest.')
    manifest = json.load(archive.extractfile(mapping['package.json']))
    if manifest.get('schema') != 1 or manifest.get('product') != 'frame-cinema' or manifest.get('platform') != 'linux-arm64':
        raise ValueError('Incompatible package.')
    if not VERSION.fullmatch(manifest.get('version', '')):
        raise ValueError('Invalid version.')
    channel = (manifest.get('channel'), manifest.get('public_release'))
    if channel == ('review', False):
        if not allow_review:
            raise ValueError('This installer requires an explicit --allow-review for review packages.')
    elif channel != ('public', True):
        raise ValueError('Unknown package channel.')
    files = manifest['files']
    if not files or not {'start.sh', 'godot', 'preflight.py', 'project.godot', '.godot/extension_list.cfg'} <= files.keys():
        raise ValueError('Incomplete runtime.')
    if set(mapping) != {'package.json', 'install.py'} | {'app/' + n for n in files}:
        raise ValueError('Archive contents differ from manifest.')
    total = 0
    for name, item in files.items():
        safe_path(Path('/package-validation'), name)
        if not re.fullmatch(r'[0-9a-f]{64}', item['sha256']) or item['mode'] not in (0o644, 0o755) or item['size'] != mapping['app/' + name].size:
            raise ValueError('Invalid file description.')
        total += item['size']
    if total > MAX_SIZE:
        raise ValueError('Package is too large.')
    return manifest, mapping, total


def verify(folder, manifest):
    for name, item in manifest['files'].items():
        path = safe_path(folder, name)
        if not path.is_file() or path.stat().st_size != item['size'] or sha(path) != item['sha256']:
            raise ValueError('Missing or changed runtime file: ' + name)


def prepare_runtime(folder):
    env = os.environ.copy()
    # Flatpak resolves user installations through the real XDG_DATA_HOME.
    # Check prerequisites before isolating Godot's import-only data directory.
    subprocess.run([sys.executable, str(folder / 'preflight.py')], cwd=folder, env=env, check=True, timeout=30)
    # Imports must not touch saved settings or initialize XR.
    env['XDG_DATA_HOME'] = str(folder / '.import-data')
    env['LD_LIBRARY_PATH'] = '/opt/steamvr/bin/linuxarm64' + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    extensions = (folder / '.godot/extension_list.cfg').read_bytes()
    with (folder / 'import.log').open('wb') as log:
        subprocess.run([str(folder / 'godot'), '--headless', '--editor', '--import', '--xr-mode', 'off', '--path', str(folder)],
                       cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    (folder / '.godot/extension_list.cfg').write_bytes(extensions)
    log = (folder / 'import.log').read_text(errors='replace')
    if 'SCRIPT ERROR:' in log or 'ERROR:' in log:
        raise ValueError('Resource import reported an error; the current installation was preserved.')


def register_launcher(root):
    # Install only our manager and launcher; Steam registration stays in Steam's UI.
    atomic(safe_path(root, 'manage.py'), Path(__file__).read_text(), 0o644)
    # Steam discards a shortcut's output; keep the last launch's log for support.
    log = 'logs="${XDG_STATE_HOME:-$HOME/.local/state}/frame-cinema"\nmkdir -p "$logs" && exec >"$logs/launch.log" 2>&1\n'
    command = 'exec python3 ' + shlex.quote(str(root / 'manage.py')) + ' run --root ' + shlex.quote(str(root)) + ' "$@"\n'
    atomic(safe_path(root, 'launch'), '#!/bin/sh\n' + log + command, 0o755)


def install(root, package, allow_review=False):
    with tarfile.open(package, 'r:gz') as archive:
        manifest, mapping, total = inspect_package(archive, allow_review)
        with locked(root, create=True):
            versions = safe_path(root, 'versions')
            versions.mkdir(exist_ok=True)
            target = safe_path(versions, manifest['version'])
            if target.exists():
                if state(root)['current'] != manifest['version']:
                    raise ValueError('This version already exists; choose rollback or a new version.')
                # Running the same installer again is how people repair it: keep the
                # installed files, rewrite the launcher, and let main() re-add the
                # Steam and desktop entries.
                try:
                    verify(target, manifest)
                except ValueError:
                    raise ValueError('This version is installed but damaged. Uninstall Frame Cinema from the '
                                     'application menu, then run the installer again.') from None
                register_launcher(root)
                return dict(state(root), repaired=True)
            if shutil.disk_usage(root).free < total * 2 + 128 * 1024**2:
                raise ValueError('Not enough free space for installation and resource import.')
            # A fresh install (not an update) never inherits sign-ins or settings
            # left behind by an earlier installation.
            fresh = state(root)['current'] is None
            stage = Path(tempfile.mkdtemp(prefix='.install-', dir=versions))
            try:
                for name, item in manifest['files'].items():
                    path = safe_path(stage, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(mapping['app/' + name]) as source, path.open('xb') as destination:
                        shutil.copyfileobj(source, destination)
                    path.chmod(item['mode'])
                verify(stage, manifest)
                prepare_runtime(stage)
                # Godot may rewrite .import metadata; the original package is the authority.
                for name in manifest['files']:
                    path = safe_path(stage, name)
                    if sha(path) != manifest['files'][name]['sha256']:
                        with archive.extractfile(mapping['app/' + name]) as source, path.open('wb') as destination:
                            shutil.copyfileobj(source, destination)
                verify(stage, manifest)
                (stage / 'package.json').write_text(json.dumps(manifest, indent=2) + '\n')
                stage.rename(target)
                previous = state(root)['current']
                register_launcher(root)
                atomic(root / 'state.json', json.dumps({'current': manifest['version'], 'previous': previous}) + '\n')
            finally:
                # stage is our freshly-created directory, never an input path.
                if stage.exists():
                    shutil.rmtree(stage)
                # A failed activation must be retryable under the same version.
                # Never remove a target if its state switch actually committed.
                if target.exists() and state(root)['current'] != manifest['version']:
                    shutil.rmtree(target)
    if fresh:
        clear_user_data()
    return state(root)


def rollback(root):
    with locked(root):
        old = state(root)
        if old['previous'] is None:
            raise ValueError('No previous version is available.')
        target = safe_path(root, 'versions/' + old['previous'])
        manifest = json.loads(safe_path(target, 'package.json').read_text())
        verify(target, manifest)
        atomic(root / 'state.json', json.dumps({'current': old['previous'], 'previous': old['current']}) + '\n')
    return state(root)


def user_data_folders():
    """Frame Cinema's settings and its own Chrome profiles; nothing else."""
    data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    chrome = Path.home() / '.var/app/com.google.Chrome/config'
    names = ('frame-cinema', 'frame-cinema-hbomax', 'frame-cinema-disneyplus',
             'frame-cinema-primevideo', 'frame-cinema-plex', 'frame-cinema-control')
    return [data_home / 'FrameCinema'] + [chrome / name for name in names]


def clear_user_data():
    """Delete Frame Cinema's settings and service sign-ins (its own Chrome profiles)."""
    removed = []
    for folder in user_data_folders():
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder)
            removed.append(str(folder))
    return removed


def uninstall(root, keep_data=False):
    # Sign-ins belong to one installation: uninstalling always signs out of
    # every service, so a reinstall starts fresh (keep_data is for support only).
    with locked(root):
        unregister_steam(root)
        unregister_desktop(root)
        versions = safe_path(root, 'versions')
        if versions.exists():
            # Every removal stays below the verified managed root. rmtree does not follow child links.
            shutil.rmtree(versions)
        for name in ('state.json', 'manage.py', 'launch', 'icon.png'):
            safe_path(root, name).unlink(missing_ok=True)
        # Keep owner/lock tombstones for a race-safe reinstall.
    removed = [] if keep_data else clear_user_data()
    return {'installed': False, 'saved_data': 'preserved' if keep_data else 'removed', 'removed': removed}


def desktop_entry():
    data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return data_home / 'applications' / 'frame-cinema-uninstall.desktop'


def register_desktop(root, icon):
    """'Uninstall Frame Cinema' in Desktop Mode's application menu."""
    entry = desktop_entry()
    entry.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon, safe_path(root, 'icon.png'))
    atomic(entry, '[Desktop Entry]\nType=Application\nName=Uninstall Frame Cinema\n'
           'Comment=Remove Frame Cinema and its Steam library entry\n'
           f'Exec=python3 "{root / "manage.py"}" uninstall-gui --root "{root}"\n'
           f'Icon={root / "icon.png"}\nTerminal=false\nCategories=Game;\n', 0o644)
    for tool in ('kbuildsycoca6', 'update-desktop-database'):
        if shutil.which(tool):
            subprocess.run([tool] if tool.startswith('kbuild') else [tool, str(entry.parent)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)


def unregister_desktop(root):
    entry = desktop_entry()
    if entry.is_file() and f'--root "{root}"' in entry.read_text(errors='replace'):
        entry.unlink()


def has_display():
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def ask(question, warning=False):
    if shutil.which('kdialog') and has_display():
        style = '--warningyesno' if warning else '--yesno'
        return subprocess.run(['kdialog', '--title', 'Frame Cinema', style, question], check=False).returncode == 0
    if sys.stdin.isatty():
        return input(question + ' [y/N] ').strip().lower().startswith('y')
    return False


def tell(message, error=False):
    print(message, file=sys.stderr if error else sys.stdout, flush=True)
    if shutil.which('kdialog') and has_display():
        subprocess.run(['kdialog', '--title', 'Frame Cinema', '--error' if error else '--msgbox', message], check=False)


def uninstall_gui(root):
    if not ask('Remove Frame Cinema from this headset?\n\nThis also removes its Steam library entry, its settings, '
               'and your sign-ins to every service in Frame Cinema.', warning=True):
        return {'cancelled': True}
    try:
        result = uninstall(root)
    except (OSError, ValueError) as error:
        tell('Frame Cinema could not be removed: ' + str(error), error=True)
        raise
    tell('Frame Cinema has been removed, and you are signed out of every service in it.')
    return result


STEAM_NAME = 'Frame Cinema'
STEAM_ART = {'capsule.png': '{id}p.png', 'header.png': '{id}.png', 'hero.png': '{id}_hero.png', 'logo.png': '{id}_logo.png'}


def vdf_load(data):
    """Steam's binary KeyValues (shortcuts.vdf): maps, strings and int32s."""
    def parse(i):
        node = {}
        while True:
            kind = data[i]
            i += 1
            if kind == 8:
                return node, i
            end = data.index(b'\0', i)
            key = data[i:end].decode('utf-8')
            i = end + 1
            if kind == 0:
                node[key], i = parse(i)
            elif kind == 1:
                end = data.index(b'\0', i)
                node[key] = data[i:end].decode('utf-8')
                i = end + 1
            elif kind == 2:
                node[key] = int.from_bytes(data[i:i + 4], 'little')
                i += 4
            else:
                raise ValueError('Unsupported shortcuts.vdf entry type.')
    root, end = parse(0)
    if data[end:] not in (b'', b'\x08'):
        raise ValueError('Unexpected data after shortcuts.vdf.')
    return root


def vdf_dump(node):
    out = bytearray()
    for key, value in node.items():
        name = key.encode('utf-8') + b'\0'
        if isinstance(value, dict):
            out += b'\0' + name + vdf_dump(value)
        elif isinstance(value, int):
            out += b'\2' + name + (value & 0xffffffff).to_bytes(4, 'little')
        else:
            out += b'\1' + name + str(value).encode('utf-8') + b'\0'
    return bytes(out + b'\x08')


def steam_userdata():
    homes = [Path.home() / '.local/share/Steam', Path.home() / '.steam/steam']
    seen, found = set(), []
    for home in homes:
        for user in sorted((home / 'userdata').glob('[0-9]*')):
            if user.is_dir() and user.resolve() not in seen and user.name != '0':
                seen.add(user.resolve())
                found.append(user)
    return found


def steam_shortcut_id(exe):
    """Steam's id for a non-Steam shortcut; also names its grid artwork."""
    import zlib
    return (zlib.crc32((exe + STEAM_NAME).encode('utf-8')) & 0xffffffff) | 0x80000000


def steam_pids():
    try:
        out = subprocess.run(['pgrep', '-x', 'steam'], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(pid) for pid in out.split() if pid.isdigit()}


def steam_running():
    return bool(steam_pids())


def steam_units(pids, proc=Path('/proc')):
    """The systemd units the Steam clients run in: steam.service in Gaming Mode,
    app-steam@autostart.service when Plasma started it in Desktop Mode, or a scope
    when someone opened it from a menu or a terminal."""
    units = set()
    for pid in pids:
        try:
            lines = (proc / str(pid) / 'cgroup').read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            names = [name for name in line.split(':', 2)[-1].split('/') if name.endswith(('.service', '.scope'))]
            if names:
                units.add(names[-1])
    return units


def steam_stop(purpose='add Frame Cinema to'):
    """Ask the running Steam client to exit; it saves shortcuts.vdf as it closes.

    Gaming Mode starts a new client immediately, so wait only for the old process
    to end and write before the new client loads its library. Returns the units
    Steam ran in, or None if it was not running."""
    old = steam_pids()
    if not old:
        return None
    units = steam_units(old)
    print(f'Restarting Steam to {purpose} your library...', flush=True)
    subprocess.run(['steam', '-shutdown'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    for _ in range(900):
        if not old & steam_pids():
            return units
        time.sleep(0.1)
    raise ValueError('Steam did not close. Restart the headset, then run the installer again.')


def steam_start(units):
    """Start Steam again through the unit it ran in, never as a child of the installer.

    A client started from here stays alive after a switch to Gaming Mode. SteamOS's
    own Steam then quits at once because one is already open, five times, and
    SteamOS resets the Steam install and stops trying."""
    for _ in range(80):
        if steam_running():  # Gaming Mode's steam.service restarts by itself
            return True
        time.sleep(0.1)
    started = False
    for unit in sorted(units):
        if unit == 'steam.service' or (unit.startswith('app-steam') and unit.endswith('.service')):
            result = subprocess.run(['systemctl', '--user', 'start', '--no-block', unit], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=30, check=False)
            started = started or result.returncode == 0
    if not started:
        print('Steam was closed to update your library. Open Steam again to see Frame Cinema.', flush=True)
    return started

def steam_entries(shortcuts, exe):
    return [key for key, item in shortcuts.items() if isinstance(item, dict) and item.get('Exe') == exe]


def write_shortcuts(config, data):
    """Replace shortcuts.vdf in one step. The first copy we ever saw is kept as
    shortcuts.vdf.frame-cinema-backup and never overwritten; the copy from just
    before this change is shortcuts.vdf.frame-cinema-previous."""
    path = config / 'shortcuts.vdf'
    blob = vdf_dump(data)
    vdf_load(blob)
    mode = 0o644
    if path.exists():
        mode = path.stat().st_mode & 0o777
        first = config / 'shortcuts.vdf.frame-cinema-backup'
        if not first.exists():
            shutil.copy2(path, first)
        shutil.copy2(path, config / 'shortcuts.vdf.frame-cinema-previous')
    descriptor, temporary = tempfile.mkstemp(prefix='.shortcuts-', dir=config)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def register_steam(root, art):
    users = steam_userdata()
    if not users:
        raise ValueError('No Steam user found on this device. Start Steam once, then install again.')
    exe = '"' + str(root / 'launch') + '"'
    appid = steam_shortcut_id(exe)
    units = steam_stop()
    restarted = False
    try:
        icon = root / 'steam-icon.png'
        shutil.copyfile(art / 'icon.png', icon)
        for user in users:
            config = user / 'config'
            config.mkdir(exist_ok=True)
            path = config / 'shortcuts.vdf'
            data = vdf_load(path.read_bytes()) if path.exists() else {'shortcuts': {}}
            key = next(iter(data)) if data else 'shortcuts'
            shortcuts = data.setdefault(key, {})
            for old in steam_entries(shortcuts, exe):
                del shortcuts[old]
            index = str(max([int(k) for k in shortcuts if k.isdigit()] + [-1]) + 1)
            shortcuts[index] = {
                'appid': appid, 'AppName': STEAM_NAME, 'Exe': exe, 'StartDir': '"' + str(root) + '"',
                'icon': str(icon), 'ShortcutPath': '', 'LaunchOptions': '', 'IsHidden': 0,
                'AllowDesktopConfig': 1, 'AllowOverlay': 1, 'OpenVR': 0, 'Devkit': 0, 'DevkitGameID': '',
                'DevkitOverrideAppID': 0, 'LastPlayTime': 0, 'FlatpakAppID': '', 'sortas': '', 'tags': {}}
            data = {key: dict(sorted(shortcuts.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 1 << 30))}
            write_shortcuts(config, data)
            grid = config / 'grid'
            grid.mkdir(exist_ok=True)
            for source, pattern in STEAM_ART.items():
                shutil.copyfile(art / source, grid / pattern.format(id=appid))
        atomic(safe_path(root, 'steam.json'), json.dumps({'appid': appid, 'exe': exe, 'users': [str(u) for u in users]}) + '\n')
    finally:
        if units is not None:
            restarted = steam_start(units)
    return {'steam_appid': appid, 'steam_users': len(users), 'steam_restarted': restarted}


def unregister_steam(root):
    record = safe_path(root, 'steam.json')
    if not record.exists():
        return False
    info = json.loads(record.read_text())
    units = steam_stop('remove Frame Cinema from')
    try:
        for user in info.get('users', []):
            config = Path(user) / 'config'
            path = config / 'shortcuts.vdf'
            if path.exists():
                data = vdf_load(path.read_bytes())
                key = next(iter(data)) if data else 'shortcuts'
                shortcuts = data.get(key, {})
                for old in steam_entries(shortcuts, info['exe']):
                    del shortcuts[old]
                write_shortcuts(config, data)
            for pattern in STEAM_ART.values():
                (config / 'grid' / pattern.format(id=info['appid'])).unlink(missing_ok=True)
        record.unlink()
        safe_path(root, 'steam-icon.png').unlink(missing_ok=True)
    finally:
        if units is not None:
            steam_start(units)
    return True


def run(root, arguments):
    with locked(root):
        current = state(root)['current']
        if not current:
            raise ValueError('Frame Cinema is not installed.')
        folder = safe_path(root, 'versions/' + current)
        process = subprocess.Popen([str(safe_path(folder, 'start.sh')), *arguments], cwd=folder, start_new_session=True)
        old_handlers = {}
        def stop(signum, _frame):
            if process.poll() is None:
                process.send_signal(signum)
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, stop)
        try:
            return process.wait()
        finally:
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'status', 'rollback', 'uninstall', 'uninstall-gui', 'steam', 'run'))
    parser.add_argument('package', type=Path, nargs='?')
    parser.add_argument('--root', type=Path, default=Path.home() / '.local/share/frame-cinema/app')
    parser.add_argument('--allow-review', action='store_true')
    parser.add_argument('--steam', action='store_true', help=argparse.SUPPRESS)  # default since 0.5.2
    parser.add_argument('--no-steam', action='store_true', help='do not add Frame Cinema to the Steam library')
    # 0.5.4: uninstall always deletes settings and sign-ins; --remove-data is accepted for old instructions.
    parser.add_argument('--remove-data', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--keep-data', action='store_true', help=argparse.SUPPRESS)  # support only
    args = parser.parse_args()
    if sys.platform != 'linux' or os.getuid() == 0:
        parser.exit(2, 'Run as your normal Linux user, without sudo.\n')
    root = args.root.absolute()
    try:
        if args.action == 'install':
            if args.package is None:
                raise ValueError('Supply the downloaded archive.')
            result = install(root, args.package, args.allow_review)
            art = safe_path(root, 'versions/' + result['current'] + '/branding/steam')
            register_desktop(root, art / 'icon.png')
            if not args.no_steam:
                try:
                    result.update(register_steam(root, art))
                except (OSError, ValueError) as error:
                    # The app is installed; only the library entry is missing.
                    result['steam_error'] = str(error)
                    print('Frame Cinema is installed, but it could not be added to Steam: ' + str(error) +
                          '\nRun the installer again, or: python3 ' + str(root / 'manage.py') + ' steam', file=sys.stderr)
        elif args.action == 'steam':
            with locked(root):
                current = state(root)['current']
            if not current:
                raise ValueError('Frame Cinema is not installed.')
            result = register_steam(root, safe_path(root, 'versions/' + current + '/branding/steam'))
        elif args.action == 'rollback':
            result = rollback(root)
        elif args.action == 'uninstall':
            result = uninstall(root, keep_data=args.keep_data)
        elif args.action == 'uninstall-gui':
            result = uninstall_gui(root)
        elif args.action == 'run':
            return run(root, [])
        else:
            with locked(root):
                result = state(root)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(2, str(error) + '\n')
    # 3: installed, but the Steam library entry is missing (the installer says so).
    return 3 if result.get('steam_error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
