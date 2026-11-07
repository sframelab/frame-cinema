"""Remove exact zero-area triangles from already-baked ROCK meshes.

UV coordinates and all surviving vertex attributes remain unchanged, so the
existing atlases stay valid. Original mesh files are retained beside the bake.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import struct

import numpy as np


def clean(path):
    original = path.read_bytes()
    magic, count, index_count = struct.unpack_from('<III', original)
    assert magic == 0x524F434B and len(original) == 12 + count*48 + index_count*4
    offset, arrays = 12, []
    for components in (3, 3, 4, 2):
        arrays.append(np.frombuffer(original, dtype='<f4', count=count*components,
                                    offset=offset).reshape(count, components))
        offset += count*components*4
    indices = np.frombuffer(original, dtype='<u4', count=index_count, offset=offset).reshape(-1, 3)
    assert indices.max() < count
    points = arrays[0][indices].astype(np.float64)
    cross = np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0])
    keep = np.any(cross != 0.0, axis=1)
    removed = int((~keep).sum())
    used, inverse = np.unique(indices[keep].reshape(-1), return_inverse=True)
    compact = [a[used] for a in arrays]
    indices = inverse.astype('<u4')
    result = struct.pack('<III', magic, len(used), len(indices))
    result += b''.join(a.astype('<f4').tobytes() for a in compact) + indices.tobytes()
    if removed:
        backup = path.parent / 'unclean-mesh-backup' / path.name
        backup.parent.mkdir(exist_ok=True)
        if not backup.exists():
            shutil.copyfile(path, backup)
        path.write_bytes(result)
    return {'removed': removed, 'vertices': len(used), 'triangles': len(indices)//3,
            'bounds': [compact[0].min(axis=0).tolist(), compact[0].max(axis=0).tolist()]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--bake', type=Path, required=True)
    p.add_argument('--runtime', type=Path)
    args = p.parse_args()
    metadata_path = args.bake / 'starship.json'
    metadata = json.loads(metadata_path.read_text())
    total_removed = 0
    for part in metadata['parts']:
        result = clean(args.bake / (part['name'] + '.bin'))
        total_removed += result['removed']
        part['vertices'], part['triangles'], part['bounds'] = result['vertices'], result['triangles'], result['bounds']
        part['removed_zero_area_triangles'] = part.get('removed_zero_area_triangles', 0) + result['removed']
    metadata['triangles'] = sum(part['triangles'] for part in metadata['parts'])
    metadata['vertices'] = sum(part['vertices'] for part in metadata['parts'])
    metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
    if args.runtime:
        for name in ['starship.json'] + [part['name']+'.bin' for part in metadata['parts']]:
            shutil.copyfile(args.bake/name, args.runtime/name)
        package_path = args.runtime / 'package.json'
        if package_path.exists():
            package = json.loads(package_path.read_text())
            package['triangles'] = metadata['triangles']
            for name in ['starship.json'] + [part['name']+'.bin' for part in metadata['parts']]:
                data = (args.runtime/name).read_bytes()
                package['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            package_path.write_text(json.dumps(package, indent=2)+'\n')
    print(json.dumps({'removed_triangles': total_removed, 'triangles': metadata['triangles'],
                      'vertices': metadata['vertices'], 'runtime_updated': str(args.runtime)}, indent=2))


if __name__ == '__main__':
    main()
