#!/usr/bin/env python3
"""Build Frame Cinema's public download from a tested headset release.

Runs on the Frame (or any Linux host) against an activated release project:
  python3 build_public.py --project ~/frame-cinema/releases/0.5.0/project --output DIR

1. Stage the runtime by rule: no tests, sources, probes, retired rooms, editor
   caches or alternate depth models (see `excluded`).
2. Add the release overlay: start.sh with the prerequisite check, preflight.py,
   documents, licenses and Steam library artwork (art/steam).
3. Check that every res:// path named by a shipped script, scene or resource
   exists in the package.
4. Write a deterministic tar.gz (public channel), a self-extracting installer
   (FrameCinema-<version>-installer.sh) and the double-click launcher that
   runs it ("Install Frame Cinema.desktop"). Publish the installer and launcher.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile

RELEASE = Path(__file__).resolve().parent
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?')

# Directories never shipped (retired rooms, caches, build trees, alternates).
EXCLUDED_DIRS = ('alpine/', '__pycache__/', '.godot/', 'stereo/model256/', 'stereo/model512/', 'build/', 'app-build/')
# Root-level development files.
EXCLUDED_ROOT = re.compile(r'(test_.*|probe_.*|run_.*_tests\.py|benchmark_.*|preview_.*|build_tree_models\.gd(\.uid)?'
                           r'|media_fixture_scripts\.py|fixture_activity|supervisor\.py\.orig|.*\.orig)$')
EXCLUDED_ANYWHERE = re.compile(r'(^|/)(test_[^/]*|benchmark_[^/]*|quality_scene\.[a-z]+|chrome_fixture\.py|CMakeLists\.txt)$')
SOURCE = re.compile(r'\.(cpp|c|cc|h|hpp)$')
# Editor caches that runtime and import do not need; extension_list.cfg is required.
GODOT_KEEP = ('.godot/extension_list.cfg', '.godot/global_script_class_cache.cfg', '.godot/uid_cache.bin')
RETIRED_THUMBS = re.compile(r'^environments/(alpine_night|blue_hour|moonless_golf|moonlit_lake|satara_night|stone_gallery)-thumb\.png(\.import)?$')
# Release overlay: (package path, source relative to this folder).
OVERLAY = {
    'preflight.py': 'preflight.py',
    'GETTING-STARTED.md': 'GETTING-STARTED.md',
    'PRIVACY.md': 'PRIVACY.md',
    'THIRD-PARTY-NOTICES.md': 'THIRD-PARTY-NOTICES.md',
    'licenses/GODOT-LICENSE.txt': 'licenses/GODOT-LICENSE.txt',
    'licenses/GODOT-COPYRIGHT.txt': 'licenses/GODOT-COPYRIGHT.txt',
    'licenses/GODOT-CPP-LICENSE.md': 'licenses/GODOT-CPP-LICENSE.md',
    'licenses/INTER-LICENSE.txt': 'licenses/INTER-LICENSE.txt',
    'licenses/OPENVR-LICENSE.txt': 'licenses/OPENVR-LICENSE.txt',
    'branding/steam/capsule.png': 'art/steam/capsule.png',
    'branding/steam/header.png': 'art/steam/header.png',
    'branding/steam/hero.png': 'art/steam/hero.png',
    'branding/steam/logo.png': 'art/steam/logo.png',
    'branding/steam/icon.png': 'art/steam/icon.png',
}
PREFLIGHT_HOOK = 'exec python3 supervisor.py "$@"'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def excluded(name):
    if name.startswith('.godot/'):
        return name not in GODOT_KEEP
    if name.startswith(EXCLUDED_DIRS) or SOURCE.search(name) or EXCLUDED_ANYWHERE.search(name) or RETIRED_THUMBS.match(name):
        return True
    return '/' not in name and bool(EXCLUDED_ROOT.fullmatch(name))


def collect(project):
    files = {}
    for directory, folders, names in os.walk(project):
        folders[:] = [f for f in folders if not (Path(directory) / f).is_symlink()]
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(project).as_posix()
            if path.is_symlink() or not path.is_file() or excluded(relative):
                continue
            files[relative] = path
    return files


def release_start(project_start):
    """The headset start.sh with the read-only prerequisite check before launch."""
    text = project_start.read_text()
    if text.count(PREFLIGHT_HOOK) != 1:
        raise ValueError('Unexpected start.sh; cannot add the prerequisite check.')
    check = ('if ! command -v python3 >/dev/null 2>&1; then\n'
             "  printf '%s\\n' 'Frame Cinema needs Python 3.11 or later. See GETTING-STARTED.md.' >&2\n"
             '  exit 2\nfi\npython3 preflight.py || exit $?\n')
    return text.replace(PREFLIGHT_HOOK, check + PREFLIGHT_HOOK)


RES_PATH = re.compile(r'res://([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+)')
TEXT = ('.gd', '.tscn', '.tres', '.gdshader', '.gdshaderinc', '.godot', '.json', '.import', '.cfg')


def unresolved_references(files):
    """res:// paths named by shipped text files that the package lacks."""
    missing = {}
    for name, data in files.items():
        if not name.endswith(TEXT) or name.endswith('.import'):
            continue
        for match in RES_PATH.finditer(data.decode('utf-8', errors='replace')):
            target = match.group(1)
            if target.startswith('.godot/') or target in files or target + '.import' in files:
                continue
            missing.setdefault(target, []).append(name)
    return missing


def deterministic_tar(output, entries):
    with output.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), mode, 0
                info.uid = info.gid = 0
                archive.addfile(info, io.BytesIO(data))


def self_extractor(archive, version):
    stub = (RELEASE / 'installer-stub.sh').read_text().replace('\r\n', '\n').replace('@VERSION@', version).replace('@SHA256@', digest(archive))
    if '@' in re.sub(r'"\$@"', '', stub):
        raise ValueError('Unfilled installer placeholder.')
    if not stub.endswith('\n__FRAME_CINEMA_ARCHIVE__\n'):
        raise ValueError('Installer stub must end with the archive marker line.')
    return stub.encode() + archive.read_bytes()


def desktop_launcher(single, version, output):
    """The double-click entry point on Steam Frame.

    Downloads lose the executable bit, a .sh opens in a text editor, and SteamOS
    has no archive manager (a zip does not open). Dolphin runs a .desktop file
    after one "Continue" prompt; it starts the installer from the same folder
    (%k is the launcher's own path), so any download folder works.
    """
    launcher = output / 'Install Frame Cinema.desktop'
    if launcher.exists():
        raise ValueError('Output exists: ' + launcher.name)
    # A second download of the same file gets renamed ("... (1).sh"), so look at
    # this version's names, and run only the exact installer this launcher was
    # built with.
    stem = single.name[:-len('.sh')]
    script = (f'd="$(dirname "$0")"; f=""; for c in "$d/{single.name}" "$d/{stem}"*.sh; do '
              f'[ -f "$c" ] && [ "$(sha256sum "$c" | cut -d " " -f 1)" = "{digest(single)}" ] && {{ f="$c"; break; }}; done; '
              'if [ -z "$f" ]; then command -v kdialog >/dev/null 2>&1 && '
              f'kdialog --title "Frame Cinema" --error "Put {single.name} in the same folder as this file, then try again."; '
              'exit 1; fi; exec sh "$f"')
    # Desktop Entry spec: in a quoted argument escape " ` $ \ with a backslash,
    # then the string escape doubles each backslash. Tested with Dolphin (KIO).
    quoted = '"' + ''.join('\\' + c if c in '"`$\\' else c for c in script) + '"'
    launcher.write_text('[Desktop Entry]\nType=Application\nVersion=1.0\n'
                        f'Name=Install Frame Cinema {version}\nComment=Installs Frame Cinema and adds it to your Steam library\n'
                        'Icon=system-software-install\nExec=sh -c ' + quoted.replace('\\', '\\\\') + ' %k\nTerminal=false\n')
    launcher.chmod(0o755)
    return launcher


def build(project, output, allow_unresolved=()):
    project, output = project.resolve(), output.resolve()
    scene = (project / 'cinema.gd').read_text()
    found = re.search(r'"version": "([^"]+)"', scene)
    if not found or not VERSION.fullmatch(found.group(1)) or '-dev' in found.group(1):
        raise ValueError('Build public packages from a release-versioned project (no -dev).')
    version = found.group(1)
    sources = collect(project)
    data = {name: path.read_bytes() for name, path in sources.items()}
    data['start.sh'] = release_start(project / 'start.sh').replace('\r\n', '\n').encode()
    for name, source in OVERLAY.items():
        data[name] = (RELEASE / source).read_bytes()
    missing = {k: v for k, v in unresolved_references(data).items() if k not in allow_unresolved}
    if missing:
        raise ValueError('Unresolved res:// references: ' + json.dumps(missing, indent=1)[:4000])
    required = {'start.sh', 'godot', 'preflight.py', 'project.godot', '.godot/extension_list.cfg', 'panel_host', 'ambient_sampler'}
    if not required <= data.keys():
        raise ValueError('Incomplete runtime: ' + ', '.join(sorted(required - data.keys())))
    files = {}
    for name in sorted(data):
        executable = data[name][:4] == b'\x7fELF' or name.endswith('.sh')
        files[name] = {'sha256': hashlib.sha256(data[name]).hexdigest(), 'size': len(data[name]), 'mode': 0o755 if executable else 0o644}
    manifest = {'schema': 1, 'product': 'frame-cinema', 'version': version, 'platform': 'linux-arm64',
                'channel': 'public', 'public_release': True, 'files': files}
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    installer = (RELEASE / 'install.py').read_bytes().replace(b'\r\n', b'\n')
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'frame-cinema-{version}-linux-arm64.tar.gz'
    single = output / f'FrameCinema-{version}-installer.sh'
    for path in (archive, single):
        if path.exists():
            raise ValueError('Output exists: ' + path.name)
    entries = [('app/' + name, data[name], files[name]['mode']) for name in sorted(data)]
    entries += [('package.json', manifest_bytes, 0o644), ('install.py', installer, 0o644)]
    deterministic_tar(archive, entries)
    single.write_bytes(self_extractor(archive, version))
    single.chmod(0o755)
    launcher = desktop_launcher(single, version, output)
    result = {'version': version, 'files': len(files), 'payload_bytes': sum(f['size'] for f in files.values()),
              'archive': archive.name, 'archive_sha256': digest(archive), 'archive_bytes': archive.stat().st_size,
              'installer': single.name, 'installer_sha256': digest(single), 'installer_bytes': single.stat().st_size,
              'launcher': launcher.name, 'launcher_sha256': digest(launcher)}
    (output / f'frame-cinema-{version}.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(f"{result['installer_sha256']}  {single.name}\n{result['launcher_sha256']}  {launcher.name}\n"
                                       f"{result['archive_sha256']}  {archive.name}\n")
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-unresolved', action='append', default=[], help='res:// path known to be optional')
    args = parser.parse_args()
    print(json.dumps(build(args.project, args.output, tuple(args.allow_unresolved)), indent=2))
