"""Validate the exported ship meshes before handing them to Godot.

This reads the on-disk ROCK payload, independently of Blender. It checks buffer
integrity and useful geometric invariants, not the scene author's implementation.
Gates (v4): per-part triangle caps and a hard total limit; extras present (.res in
a runtime package, .exr in a bake directory); glow manifest sanity; projected lamp
width at the headset; same-facing coplanar overlaps (z-fighting); collapsed
triangles; the cabin envelope; the opaque sheet under the deck.
Usage: python verify_geometry.py --package <baked or runtime ship directory>
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct
import sys

HERE = Path(__file__).resolve().parent
# Keep the script folder off the import path. It used to hold inspect.py (now
# view_room.py), which shadowed the standard-library module numpy imports.
sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != HERE]

import numpy as np
MAGIC = 0x524F434B
CAPS = {'deck': 28000, 'shell': 42000, 'detail': 30000, 'trim': 8000, 'seating': 24000, 'viewer': 9000, 'emission': 6000}
TARGET_TRIANGLES = 135000
EYE = np.array([0.0, 1.65, 0.0])
FOCAL_PX = 748.0          # the Frame's OpenXR view: about 109.5 deg per eye over 2160 px
MIN_PX, MIN_PX_SCALED, LOW_SCALE = 2.5, 1.6, 0.62
COPLANAR_DISTANCE, COPLANAR_AREA, COPLANAR_DOT = 0.0005, 1e-6, 0.999
# The deck's slab footprint in room space (x, z) and the height band of the sheet under it.
DECK_X, DECK_Z = 4.69, (-6.585, 6.5)
UNDERLAY_Y = (0.43, 0.4495)


def validate_part(directory, metadata, keep):
    path = directory / (metadata['name'] + '.bin')
    data = path.read_bytes()
    result = {'part': metadata['name'], 'file': path.name, 'bytes': len(data),
              'sha256': hashlib.sha256(data).hexdigest(), 'errors': []}
    errors = result['errors']
    if len(data) < 12:
        errors.append('Mesh has no complete header.')
        return result
    magic, vertex_count, index_count = struct.unpack_from('<III', data)
    result.update(vertices=vertex_count, triangles=index_count // 3)
    if magic != MAGIC:
        errors.append('Unexpected ROCK format identifier.')
    expected_bytes = 12 + vertex_count * 48 + index_count * 4
    if len(data) != expected_bytes:
        errors.append(f'Buffer length is {len(data)}; header requires {expected_bytes}.')
        return result
    if not vertex_count or not index_count or index_count % 3:
        errors.append('Empty mesh or incomplete triangle index triplet.')
        return result
    offset = 12
    arrays = {}
    for key, components in [('position', 3), ('normal', 3), ('tangent', 4), ('uv', 2)]:
        arrays[key] = np.frombuffer(data, dtype='<f4', count=vertex_count * components,
                                   offset=offset).reshape(vertex_count, components).astype(np.float64)
        offset += vertex_count * components * 4
    indices = np.frombuffer(data, dtype='<u4', count=index_count, offset=offset).reshape(-1, 3)
    if int(indices.max()) >= vertex_count:
        errors.append('Triangle index exceeds the vertex buffer.')
        return result
    if vertex_count != int(metadata['vertices']) or index_count // 3 != int(metadata['triangles']):
        errors.append('Vertex/triangle count differs from starship.json.')
    if not all(np.isfinite(values).all() for values in arrays.values()):
        errors.append('Non-finite coordinate, normal, tangent or UV.')
        return result

    positions, normals, tangents, uv = [arrays[k] for k in ('position', 'normal', 'tangent', 'uv')]
    bounds = np.stack([positions.min(axis=0), positions.max(axis=0)])
    result['bounds_m'] = bounds.tolist()
    if not np.allclose(bounds, np.asarray(metadata['bounds']), rtol=0, atol=0.0001):
        errors.append('Actual mesh bounds differ from starship.json.')

    normal_error = np.abs(np.linalg.norm(normals, axis=1) - 1)
    tangent_error = np.abs(np.linalg.norm(tangents[:, :3], axis=1) - 1)
    tangent_dot = np.abs(np.einsum('ij,ij->i', normals, tangents[:, :3]))
    result['maximum_normal_length_error'] = float(normal_error.max())
    result['maximum_tangent_length_error'] = float(tangent_error.max())
    result['maximum_normal_tangent_dot'] = float(tangent_dot.max())
    if np.any(normal_error > .003):
        errors.append('A surface normal is not unit length (tolerance .003).')
    if np.any(tangent_error > .003) or np.any(tangent_dot > .003):
        errors.append('A tangent is not unit length or perpendicular to its normal.')
    if np.any(np.abs(np.abs(tangents[:, 3]) - 1) > .0001):
        errors.append('A tangent handedness value is not +1 or -1.')
    result['uv_bounds'] = [uv.min(axis=0).tolist(), uv.max(axis=0).tolist()]
    if np.any(uv < -.0001) or np.any(uv > 1.0001):
        errors.append('UV lies outside the non-repeating baked atlas.')

    a, b, c = [positions[indices[:, corner]] for corner in (0, 1, 2)]
    areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) * .5
    # A trillionth of a square metre is far below any authored bevel/rivet.
    # This catches collapsed faces without rejecting fine manufactured details.
    degenerate = areas <= 1e-12
    result['zero_area_triangles'] = int(degenerate.sum())
    result['smallest_triangle_area_m2'] = float(areas.min())
    result['surface_area_m2'] = float(areas.sum())
    if np.any(degenerate):
        result['zero_area_triangle_indices'] = np.flatnonzero(degenerate)[:20].tolist()
        errors.append(f'{int(degenerate.sum())} collapsed triangles found.')
    cap = CAPS.get(metadata['name'])
    result['triangle_cap'] = cap
    if cap is not None and index_count // 3 > cap:
        errors.append(f'{index_count // 3} triangles exceed the {cap} cap for this part.')
    keep[metadata['name']] = np.stack([a, b, c], axis=1)
    return result


def check_extras(directory, metadata):
    bake_directory = (directory / 'observation-deck-bake.blend').exists() or not (directory / 'package.json').exists()
    suffix = '.exr' if bake_directory else '.res'
    report = {'kind': 'bake' if bake_directory else 'package', 'expected_suffix': suffix, 'files': {}, 'errors': []}
    for extra in metadata.get('extras', []):
        name = str(extra['name']) + suffix
        present = (directory / name).is_file()
        report['files'][name] = present
        if not present:
            report['errors'].append(f'Extra {name} is missing.')
    return report


def check_glows(metadata, focal=FOCAL_PX, eye=EYE):
    glows = metadata.get('glows', [])
    report = {'count': len(glows), 'by_kind': {}, 'errors': [], 'projected': [], 'narrowest_px': None}
    if len(glows) > 120:
        report['errors'].append(f'{len(glows)} glows exceed the 120 limit.')
    narrow = None
    for index, glow in enumerate(glows):
        name = glow.get('name', f'glow {index}')
        report['by_kind'][glow.get('kind', '?')] = report['by_kind'].get(glow.get('kind', '?'), 0) + 1
        try:
            c, n, u = (np.asarray(glow[k], dtype=np.float64) for k in ('c', 'n', 'u'))
            size = np.asarray(glow['size'], dtype=np.float64)
        except (KeyError, ValueError, TypeError):
            report['errors'].append(f'{name}: malformed entry.')
            continue
        values = np.concatenate([c, n, u, size])
        if values.size != 11 or not np.isfinite(values).all():
            report['errors'].append(f'{name}: non-finite or wrongly sized vectors.')
            continue
        if abs(np.linalg.norm(n) - 1) > .01 or abs(np.linalg.norm(u) - 1) > .01:
            report['errors'].append(f'{name}: n or u is not unit length.')
        if abs(float(n @ u)) >= .01:
            report['errors'].append(f'{name}: n and u are not perpendicular ({float(n @ u):.4f}).')
        w = np.cross(n, u)
        w /= max(np.linalg.norm(w), 1e-12)
        offset = c - eye
        dist = float(np.linalg.norm(offset))
        d = offset / max(dist, 1e-12)
        facing = float(n @ -d)
        if facing <= 0:
            continue
        px = float(size[1] * np.linalg.norm(np.cross(w, d)) / dist * focal)
        entry = {'name': name, 'kind': glow.get('kind'), 'width_m': float(size[1]), 'distance_m': round(dist, 3),
                 'px': round(px, 2), 'px_at_0.62': round(px * LOW_SCALE, 2)}
        report['projected'].append(entry)
        if narrow is None or px < narrow['px']:
            narrow = entry
        if px < MIN_PX:
            report['errors'].append(f'{name}: projected width {px:.2f} px < {MIN_PX} px.')
        if px * LOW_SCALE < MIN_PX_SCALED:
            report['errors'].append(f'{name}: projected width at scale 0.62 is {px * LOW_SCALE:.2f} px < {MIN_PX_SCALED} px.')
    report['narrowest_px'] = narrow
    return report


def check_underlay(triangles_by_part):
    """Level triangles just under the slab must span the whole deck: plate bottoms are culled, so
    without this sheet a ray down a seam leaves the cabin and sees the sky (and the Earth's cities)."""
    report = {'triangles': 0, 'area_m2': 0.0, 'errors': []}
    tris = triangles_by_part.get('deck')
    if tris is None:
        report['errors'].append('No deck part to check for its underlay.')
        return report
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    length = np.linalg.norm(cross, axis=1)
    level = np.abs(cross[:, 1]) > .99 * np.maximum(length, 1e-12)
    height = tris[:, :, 1].mean(axis=1)
    sheet = tris[level & (height > UNDERLAY_Y[0]) & (height < UNDERLAY_Y[1])]
    area = float(length[level & (height > UNDERLAY_Y[0]) & (height < UNDERLAY_Y[1])].sum() * .5)
    report.update(triangles=int(len(sheet)), area_m2=round(area, 3))
    need = 2 * DECK_X * (DECK_Z[1] - DECK_Z[0])
    if not len(sheet):
        report['errors'].append('The deck has no underlay: seams can see the sky.')
    elif (sheet[:, :, 0].min() > -DECK_X or sheet[:, :, 0].max() < DECK_X or sheet[:, :, 2].min() > DECK_Z[0]
          or sheet[:, :, 2].max() < DECK_Z[1] or area < need):
        report['errors'].append(f'The deck underlay ({area:.1f} m2) does not span the slab ({need:.1f} m2).')
    return report


def _plane_basis(normal):
    axis = np.array([1.0, 0, 0]) if abs(normal[0]) < .9 else np.array([0, 1.0, 0])
    u = np.cross(normal, axis)
    u /= np.linalg.norm(u)
    return u, np.cross(normal, u)


def _clip_area(subject, clip):
    """Area of the intersection of two counter-clockwise convex 2D polygons."""
    output = list(subject)
    for i in range(len(clip)):
        if not output:
            return 0.0
        a, b = clip[i], clip[(i + 1) % len(clip)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        inputs, output = output, []
        for j in range(len(inputs)):
            p, q = inputs[j], inputs[(j + 1) % len(inputs)]
            sp = ex * (p[1] - a[1]) - ey * (p[0] - a[0])
            sq = ex * (q[1] - a[1]) - ey * (q[0] - a[0])
            if sp >= 0:
                output.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                output.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    area = 0.0
    for i in range(len(output)):
        area += output[i][0] * output[(i + 1) % len(output)][1] - output[(i + 1) % len(output)][0] * output[i][1]
    return abs(area) * .5


def check_coplanar(triangles_by_part):
    names, chunks = [], []
    for name, tris in triangles_by_part.items():
        names.extend([name] * len(tris))
        chunks.append(tris)
    report = {'checked_triangles': 0, 'candidate_pairs': 0, 'overlaps': 0, 'examples': [], 'errors': []}
    if not chunks:
        return report
    tris = np.concatenate(chunks)
    names = np.array(names)
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    length = np.linalg.norm(cross, axis=1)
    valid = length > 2e-10
    tris, names, cross, length = tris[valid], names[valid], cross[valid], length[valid]
    normals = cross / length[:, None]
    offsets = np.einsum('ij,ij->i', normals, tris.mean(axis=1))
    report['checked_triangles'] = int(len(tris))
    nkeys = np.round(normals / .01).astype(np.int64)
    dkeys = np.round(offsets / COPLANAR_DISTANCE).astype(np.int64)
    bins = {}
    for index, key in enumerate(zip(nkeys[:, 0], nkeys[:, 1], nkeys[:, 2], dkeys)):
        bins.setdefault(key, []).append(index)
    keys = sorted(bins)
    key_set = set(keys)
    position_ids = {}
    vertex_ids = np.zeros((len(tris), 3), dtype=np.int64)
    rounded = np.round(tris / 1e-6).astype(np.int64)
    for i in range(len(tris)):
        for k in range(3):
            vertex_ids[i, k] = position_ids.setdefault(tuple(rounded[i, k]), len(position_ids))
    neighbours = [(a, b, c, e) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1) for e in (-1, 0, 1)]
    seen_pairs = set()
    found = []
    for key in keys:
        group_a = np.array(bins[key])
        for delta in neighbours:
            other = (key[0] + delta[0], key[1] + delta[1], key[2] + delta[2], key[3] + delta[3])
            if other not in key_set or other < key:
                continue
            group_b = np.array(bins[other])
            basis_u, basis_v = _plane_basis(normals[group_a[0]])
            pa = np.stack([tris[group_a] @ basis_u, tris[group_a] @ basis_v], axis=-1)
            pb = np.stack([tris[group_b] @ basis_u, tris[group_b] @ basis_v], axis=-1)
            amin, amax = pa.min(axis=1), pa.max(axis=1)
            bmin, bmax = pb.min(axis=1), pb.max(axis=1)
            for start in range(0, len(group_a), 512):
                sl = slice(start, start + 512)
                hit = ((amin[sl, None, 0] < bmax[None, :, 0] - 1e-7) & (amax[sl, None, 0] > bmin[None, :, 0] + 1e-7) &
                       (amin[sl, None, 1] < bmax[None, :, 1] - 1e-7) & (amax[sl, None, 1] > bmin[None, :, 1] + 1e-7))
                ii, jj = np.nonzero(hit)
                for i_local, j_local in zip(ii + start, jj):
                    i, j = int(group_a[i_local]), int(group_b[j_local])
                    if i >= j and other == key:
                        continue
                    pair = (min(i, j), max(i, j))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    if float(normals[i] @ normals[j]) <= COPLANAR_DOT:
                        continue
                    if abs(float(offsets[i] - offsets[j])) >= COPLANAR_DISTANCE:
                        continue
                    if len(set(vertex_ids[i]) & set(vertex_ids[j])) >= 2:
                        continue
                    report['candidate_pairs'] += 1
                    poly_a = [tuple(v) for v in pa[i_local]]
                    poly_b = [tuple(v) for v in pb[j_local]]
                    if _signed(poly_a) < 0: poly_a.reverse()
                    if _signed(poly_b) < 0: poly_b.reverse()
                    area = _clip_area(poly_a, poly_b)
                    if area > COPLANAR_AREA:
                        found.append((area, i, j))
    report['overlaps'] = len(found)
    found.sort(reverse=True)
    for area, i, j in found[:25]:
        report['examples'].append({'parts': [str(names[i]), str(names[j])], 'area_m2': round(area, 8),
                                   'plane_distance_m': round(abs(float(offsets[i] - offsets[j])), 6),
                                   'centroid': np.round(tris[i].mean(axis=0), 4).tolist(), 'normal': np.round(normals[i], 4).tolist()})
    if found:
        pairs = {}
        for area, i, j in found:
            key = ' / '.join(sorted({str(names[i]), str(names[j])}))
            pairs[key] = pairs.get(key, 0) + 1
        report['by_parts'] = pairs
        report['errors'].append(f'{len(found)} same-facing coplanar overlaps (z-fighting) found: {pairs}.')
    return report


def _signed(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=HERE / 'verification/geometry.json')
    parser.add_argument('--max-triangles', type=int, default=150000)
    parser.add_argument('--skip-coplanar', action='store_true', help='Skip the z-fighting search (diagnostic runs only)')
    args = parser.parse_args()
    directory = args.package.resolve()
    manifest_path = directory / 'starship.json'
    metadata = json.loads(manifest_path.read_text())
    report = {'schema': 2, 'date': '2026-11-02', 'scope': 'Offline structural mesh validation; no headset performance or comfort claim',
              'source_directory': str(directory), 'revision': metadata['revision'],
              'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              'coordinate_system': 'Godot: X right, Y up, forward -Z; metres', 'parts': [], 'errors': [], 'warnings': []}
    keep = {}
    for part in metadata['parts']:
        try:
            result = validate_part(directory, part, keep)
        except (OSError, ValueError, KeyError, struct.error) as exc:
            result = {'part': part.get('name', '?'), 'errors': [str(exc)]}
        report['parts'].append(result)
        report['errors'].extend(f"{result['part']}: {error}" for error in result['errors'])

    vertices = sum(p.get('vertices', 0) for p in report['parts'])
    triangles = sum(p.get('triangles', 0) for p in report['parts'])
    report.update(vertices=vertices, triangles=triangles, triangle_target=TARGET_TRIANGLES, max_triangles=args.max_triangles)
    if vertices != metadata['vertices'] or triangles != metadata['triangles']:
        report['errors'].append('Total mesh counts differ from manifest totals.')
    if triangles > args.max_triangles:
        report['errors'].append(f'{triangles} triangles exceed the hard limit of {args.max_triangles}.')
    elif triangles > TARGET_TRIANGLES:
        report['warnings'].append(f'{triangles} triangles exceed the {TARGET_TRIANGLES} target.')
    actual_bounds = [np.asarray(p['bounds_m']) for p in report['parts'] if 'bounds_m' in p]
    if actual_bounds:
        lower = np.min([b[0] for b in actual_bounds], axis=0)
        upper = np.max([b[1] for b in actual_bounds], axis=0)
        report['bounds_m'] = [lower.tolist(), upper.tolist()]
        floor = float(metadata['floor_height_m'])
        # Broad physical sanity checks catch swapped axes, centimetres/metres,
        # missing floor or ceiling, without tying this to exact authored parts.
        if not (floor-.35 <= lower[1] <= floor+.1 and floor+3.0 <= upper[1] <= floor+5.5):
            report['errors'].append('Floor/ceiling bounds are outside the expected metre-scale cabin.')
        if not (7 <= upper[0]-lower[0] <= 12 and 8 <= upper[2]-lower[2] <= 14):
            report['errors'].append('Cabin width/depth is outside the expected metre scale.')
        report['authored_floor_m'] = floor
        report['ceiling_top_m'] = float(upper[1])
        report['depth_m'] = float(upper[2] - lower[2])
    for key, check in (('extras', lambda: check_extras(directory, metadata)), ('glows', lambda: check_glows(metadata)),
                       ('underlay', lambda: check_underlay(keep)),
                       ('coplanar', (lambda: {'skipped': True, 'errors': []}) if args.skip_coplanar else (lambda: check_coplanar(keep)))):
        result = check()
        report[key] = result
        report['errors'].extend(f'{key}: {error}' for error in result['errors'])
    report['passed'] = not report['errors']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    glow = report['glows']
    print(json.dumps({'passed': report['passed'], 'parts': len(report['parts']),
                      'vertices': vertices, 'triangles': triangles,
                      'per_part': {p['part']: [p.get('triangles'), p.get('triangle_cap')] for p in report['parts']},
                      'glows': {'count': glow['count'], 'by_kind': glow['by_kind'], 'narrowest_px': glow['narrowest_px']},
                      'underlay_m2': report['underlay'].get('area_m2'),
                      'coplanar_overlaps': report['coplanar'].get('overlaps'), 'extras': report['extras']['files'],
                      'errors': report['errors'][:40], 'warnings': report['warnings'],
                      'report': str(args.output.resolve())}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
