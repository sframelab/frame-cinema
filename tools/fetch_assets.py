#!/usr/bin/env python3
"""Copy Frame Cinema assets from a release into this checkout.

Textures, meshes, Godot and native binaries are stored in releases. assets.json
records their sizes and SHA-256 hashes. This script verifies each file it copies
into app/. Existing files are checked by size; add --verify to check their hashes.

The source can be:
  - an installer:        FrameCinema-0.5.21-installer.sh
  - its archive:         frame-cinema-0.5.21-linux-arm64.tar.gz
  - an installed copy:   ~/.local/share/frame-cinema/app/versions/0.5.21  (on a Steam Frame)

    python tools/fetch_assets.py FrameCinema-0.5.21-installer.sh
    python tools/fetch_assets.py --check          # only list what is missing

An older release supplies matching files and reports the rest as missing or
different. Requires Python 3.8 or later, with no additional packages.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

REPO = Path(__file__).resolve().parents[1]
MARKER = b'\n__FRAME_CINEMA_ARCHIVE__\n'


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def present(path, entry, verify):
    if not path.is_file() or path.stat().st_size != entry['bytes']:
        return False
    return digest(path) == entry['sha256'] if verify else True


def members(source):
    """Yield (path inside app/, reader) from an installer, a .tar.gz or a folder."""
    if source.is_dir():
        for path in source.rglob('*'):
            if path.is_file():
                yield path.relative_to(source).as_posix(), path.open('rb')
        return
    stream = open(source, 'rb')
    head = stream.read(262144)
    at = head.find(MARKER)
    stream.seek(at + len(MARKER) if at >= 0 else 0)
    with tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for member in archive:
            if member.isfile() and member.name.startswith('app/'):
                yield member.name[4:], archive.extractfile(member)
    stream.close()


def copy_checked(reader, target, entry):
    """Write to a temporary name, keep it only if size and hash match."""
    h = hashlib.sha256()
    size = 0
    temporary = target.with_name(target.name + '.part')
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(temporary, 'wb') as out:
        for block in iter(lambda: reader.read(1 << 20), b''):
            h.update(block)
            size += len(block)
            out.write(block)
    if size != entry['bytes'] or h.hexdigest() != entry['sha256']:
        temporary.unlink()
        return False
    os.replace(temporary, target)
    if entry.get('exec'):
        target.chmod(0o755)
    return True


def main():
    parser = argparse.ArgumentParser(description='Copy release assets into this checkout.')
    parser.add_argument('source', nargs='?', type=Path, help='installer, .tar.gz or installed app folder')
    parser.add_argument('--check', action='store_true', help='report missing files and size mismatches without copying')
    parser.add_argument('--verify', action='store_true', help='also check hashes of existing files')
    args = parser.parse_args()
    manifest = json.loads((REPO / 'assets.json').read_text(encoding='utf-8'))
    wanted = {path: entry for path, entry in manifest['files'].items()
              if not present(REPO / path, entry, args.verify)}
    total = len(manifest['files'])
    if args.check or not wanted:
        print(f'{total - len(wanted)} of {total} files present for Frame Cinema {manifest["version"]}.')
        for path in sorted(wanted)[:40]:
            print('  missing', path)
        if len(wanted) > 40:
            print(f'  ...and {len(wanted) - 40} more')
        return 0 if not wanted else 1
    if args.source is None or not args.source.exists():
        parser.error('give the installer, archive or installed folder to copy from')
    filled, mismatched = [], []
    for inner, reader in members(args.source):
        public = 'app/' + inner
        if public not in wanted:
            continue
        with reader:
            (filled if copy_checked(reader, REPO / public, wanted[public]) else mismatched).append(public)
    missing = sorted(set(wanted) - set(filled) - set(mismatched))
    print(f'Copied {len(filled)} files from {args.source.name}.')
    if mismatched:
        print(f'{len(mismatched)} files in that release differ from this version (a different release?):')
        for path in sorted(mismatched)[:20]:
            print('  differs', path)
    if missing:
        print(f'{len(missing)} files are not in that release:')
        for path in missing[:20]:
            print('  missing', path)
    if mismatched or missing:
        print(f'Use the Frame Cinema {manifest["version"]} release to fill in the rest.')
        return 1
    print(f'All {total} files are in place.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
