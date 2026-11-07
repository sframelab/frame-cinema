"""Author the Observation Deck meshes in metres (X right, Y forward, Z up).

This is source geometry for Frame Cinema, not a panorama.  The caller owns scene
reset, cameras, baking, export and screen placement.  Import this module with
Blender's Python and call build_interior(), then optionally build_lights().

v4 (2026-11-02): re-stationed structure (heavy armoured ribs at -2.62/+1.40,
slim frames, forward fin, raised brow), a deep enclosed aft bay (REAR -6.5),
the planned deck layout on the shared height table, flat gasket lips
on every glazed opening, slot lamps with a baked core gradient, soft seating
and per-lamp bake lights.  Objects carry the tags build_runtime.py reads:
bake_group, glow/glow_c/facing/along/glow_size and light_kind.
"""
from __future__ import annotations

import math
import bpy
import bmesh
from mathutils import Vector, Matrix, Euler

FLOOR = 0.45
EYE = (0.0, 0.0, 1.65)
FRONT = 6.6
REAR = -6.5
HALF_WIDTH = 4.7

# Shared deck height table (Blender z).
SLAB_TOP = .450
VENT_BED = .456
GROOVE_BED = .472
VENT_GRILLE = .470
PLATE_TOP = .480
BAR_TOP = .484
CURB_TOP = .515
DECK_TOP = PLATE_TOP
MIRROR_EYE = (0.0, 0.0, 2 * PLATE_TOP - EYE[2])

# Stations (Blender y).
AFT_PILASTERS = (-5.60, -4.25)
HEAVY_RIBS = (-2.62, 1.40)
SLIM_FRAMES = (-1.35, .05, 3.05)
FIN = 4.75
FIN_SPAN = (4.30, 5.20)
CABIN_STATIONS = (-2.62, -1.35, .05, 1.40, 3.05, 4.75)
STATION_KIND = {-2.62: 'heavy', -1.35: 'slim', .05: 'slim', 1.40: 'heavy', 3.05: 'slim', 4.75: 'fin'}
STATION_WIDTH = {'heavy': .58, 'slim': .12, 'fin': .90}

# Canopy profile on the member-centreline glass plane, right side (x, z).
P0, P1, P2, P3 = (4.66, 1.72), (3.87, 3.62), (2.99, 4.38), (1.25, 4.58)
BROW = [(4.66, .45), (4.66, 1.70), (3.95, 3.75), (3.05, 4.95), (1.25, 5.20)]
LEDGE_TOP = 1.73
INTERIOR_XZ = (0.0, 2.5)

OBJECTS = []
MATS = {}
LAMPS = []          # amber lens records for bake lights
BLUES = []          # blue strip records for bake lights
POOLS = []          # practical pool lights requested by authoring code
COVERS = []         # deck footprints (x0, x1, y0, y1[, top z]) hiding the slab top
WIDENED = []        # lenses widened to meet the projected-width gate
GLOW_PX_TARGET = 2.75
FOCAL_PX = 748.0     # the Frame's OpenXR view: about 109.5 deg per eye over 2160 px


# ---------------------------------------------------------------- vector helpers
def v3(p):
    return Vector((float(p[0]), float(p[1]), float(p[2])))


def xz(x, z, y=0.0):
    return Vector((x, y, z))


def unit2(a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dz)
    return dx / n, dz / n


def inward2(a, b):
    """Unit normal of segment a-b (x, z) pointing toward the cabin interior."""
    tx, tz = unit2(a, b)
    nx, nz = tz, -tx
    mx, mz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if nx * (INTERIOR_XZ[0] - mx) + nz * (INTERIOR_XZ[1] - mz) < 0:
        nx, nz = -nx, -nz
    return nx, nz


def side_pts(points, side):
    return [(side * x, z) for x, z in points]


def along_profile(a, b, z, offset=0.0):
    """Point on segment a-b at profile height z, moved `offset` toward the room."""
    t = (z - a[1]) / (b[1] - a[1])
    nx, nz = inward2(a, b)
    return (a[0] + t * (b[0] - a[0]) + nx * offset, z + nz * offset)


def line_intersect(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + t * d[0], p[1] + t * d[1])


def offset_polyline(points, offsets):
    """Offset an open 2D polyline; offsets[i] applies to segment i (signed, left = +)."""
    segs = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        tx, tz = unit2(a, b)
        nx, nz = -tz, tx
        o = offsets[i]
        segs.append(((a[0] + nx * o, a[1] + nz * o), (tx, tz)))
    out = [segs[0][0]]
    for i in range(1, len(segs)):
        hit = line_intersect(segs[i - 1][0], segs[i - 1][1], segs[i][0], segs[i][1])
        out.append(hit if hit is not None else segs[i][0])
    a, b = points[-2], points[-1]
    tx, tz = unit2(a, b)
    o = offsets[-1]
    out.append((b[0] - tz * o, b[1] + tx * o))
    return out


def band_polygon(points, widths, centre=0.0):
    """Closed polygon of an open polyline band; widths per segment, centred at `centre` offset."""
    left = offset_polyline(points, [centre + w / 2 for w in widths])
    right = offset_polyline(points, [centre - w / 2 for w in widths])
    return left + list(reversed(right))


def clip_start_z(poly_line, z):
    """Move the first point of a 2D polyline onto the horizontal z along its first segment."""
    a, b = poly_line[0], poly_line[1]
    t = (z - a[1]) / (b[1] - a[1])
    return [(a[0] + t * (b[0] - a[0]), z)] + list(poly_line[1:])


def polygon_signed_area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2


# ---------------------------------------------------------------- object creation
def make_object(name, verts, faces, recalc=True, drop=None):
    """drop: world directions; faces whose normal points along one (dot > .95) are
    deleted. Used for faces that only ever face away from the cabin (outer member
    faces beyond the glass, tops hidden above ceilings) so they take no atlas space."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update()
    if recalc or drop:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        if drop:
            bm.normal_update()
            dirs = [v3(d).normalized() for d in drop]
            doomed = [f for f in bm.faces if any(f.normal.dot(d) > .95 for d in dirs)]
            if doomed:
                bmesh.ops.delete(bm, geom=doomed, context='FACES')
        bm.to_mesh(mesh)
        bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def finish(obj, name, mat, group, bevel=0.0, segments=2, smooth=False, weighted=True):
    obj.name = name
    obj['bake_group'] = group
    obj['author'] = 'Frame Lab'
    for m in (mat if isinstance(mat, (list, tuple)) else [mat]):
        obj.data.materials.append(MATS[m] if isinstance(m, str) else m)
    if bevel:
        bpy.context.view_layer.objects.active = obj
        mod = obj.modifiers.new('Soft manufactured edges', 'BEVEL')
        mod.width = bevel
        mod.segments = segments
        mod.affect = 'EDGES'
        mod.limit_method = 'ANGLE'
        mod.angle_limit = math.radians(30)
        mod.harden_normals = False
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if smooth:
        for face in obj.data.polygons:
            face.use_smooth = True
    elif bevel and weighted:
        # Weighted normals retain a broad flat face between the rounded edges.
        for face in obj.data.polygons:
            face.use_smooth = True
        bpy.context.view_layer.objects.active = obj
        mod = obj.modifiers.new('Weighted face normals', 'WEIGHTED_NORMAL')
        mod.keep_sharp = True
        mod.weight = 45
        bpy.ops.object.modifier_apply(modifier=mod.name)
    OBJECTS.append(obj)
    return obj


CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def frame_box(name, center, axes, half, mat, group, bevel, segments=2, smooth=False, drop=None):
    """Box from a centre, three unit axes and half extents."""
    c = v3(center)
    verts = [c + axes[0] * (sx * half[0]) + axes[1] * (sy * half[1]) + axes[2] * (sz * half[2])
             for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    obj = make_object(name, verts, CUBE_FACES, drop=drop)
    return finish(obj, name, mat, group, bevel, segments, smooth)


def clamp_bevel(bevel, size):
    if min(size) < .006:
        return 0.0
    return min(bevel, .4 * min(size))


def box(name, center, size, mat, group='shell', bevel=.012, segments=2, rotation=None, cover=False, drop=None):
    bevel = clamp_bevel(bevel, size)
    R = Euler(rotation).to_matrix() if rotation else Matrix.Identity(3)
    axes = [R.col[0].copy(), R.col[1].copy(), R.col[2].copy()]
    if cover:
        COVERS.append((center[0] - size[0] / 2, center[0] + size[0] / 2, center[1] - size[1] / 2, center[1] + size[1] / 2,
                       center[2] + size[2] / 2))
    return frame_box(name, center, axes, [s / 2 for s in size], mat, group, bevel, segments, drop=drop)


def zbox(name, x0, x1, y0, y1, z0, z1, mat, group, bevel=0.0, segments=1, cover=False, drop=None):
    """Axis-aligned box from extents (deck parts use exact heights)."""
    return box(name, ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), (x1 - x0, y1 - y0, z1 - z0),
               mat, group, bevel, segments, cover=cover, drop=drop)


def oriented_box(name, center, size, along, facing, mat, group='shell', bevel=.012, segments=2, drop=None):
    """size = (along, across, facing); columns (along, cross(facing, along), facing)."""
    a = v3(along).normalized()
    f = v3(facing)
    f = (f - a * a.dot(f)).normalized()
    c = f.cross(a)
    bevel = clamp_bevel(bevel, size)
    if drop == 'back':
        drop = [-f]
    return frame_box(name, center, [a, c, f], [s / 2 for s in size], mat, group, bevel, segments, drop=drop)


def extrude(name, points, vector, mat, group='shell', bevel=.015, segments=2, smooth=False, drop=None):
    """Prism from a planar 3D polygon swept by `vector`."""
    n = len(points)
    vec = v3(vector)
    base = [v3(p) for p in points]
    verts = base + [p + vec for p in base]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    bevel = min(bevel, .4 * vec.length) if vec.length >= .006 else 0.0
    obj = make_object(name, verts, faces, drop=drop)
    return finish(obj, name, mat, group, bevel, segments, smooth)


def prism(name, points, depth, center_y, mat, group='shell', bevel=.015, segments=2, drop=None):
    """Extrude an X/Z polygon along Y; points follow its perimeter."""
    pts = [(x, center_y - depth / 2, z) for x, z in points]
    return extrude(name, pts, (0, depth, 0), mat, group, bevel, segments, drop=drop)


def xy_prism(name, points, z0, z1, mat, group='deck', bevel=0.0, segments=1):
    """Extrude an X/Y polygon from z0 up to z1."""
    pts = [(x, y, z0) for x, y in points]
    return extrude(name, pts, (0, 0, z1 - z0), mat, group, bevel, segments)


def cell_solid(name, outline, holes, z0, z1, mat, group='deck', bevel=0.0, segments=2, cover=True, drop=None):
    """Axis-aligned plate (x0, x1, y0, y1) with rectangular holes, as one manifold mesh.

    The top is a grid split at the hole edges; the bevel's 30 degree angle limit
    leaves the flat internal grid edges alone, so only real edges are rounded.
    """
    x0, x1, y0, y1 = outline
    xs = sorted({x0, x1} | {h[i] for h in holes for i in (0, 1) if x0 < h[i] < x1})
    ys = sorted({y0, y1} | {h[i] for h in holes for i in (2, 3) if y0 < h[i] < y1})
    nx, ny = len(xs) - 1, len(ys) - 1

    def kept(i, j):
        if i < 0 or j < 0 or i >= nx or j >= ny:
            return False
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        return not any(h[0] < cx < h[1] and h[2] < cy < h[3] for h in holes)

    index = {}
    verts = []

    def vid(i, j, top):
        key = (i, j, top)
        if key not in index:
            index[key] = len(verts)
            verts.append((xs[i], ys[j], z1 if top else z0))
        return index[key]

    faces = []
    for i in range(nx):
        for j in range(ny):
            if not kept(i, j):
                continue
            faces.append((vid(i, j, 1), vid(i + 1, j, 1), vid(i + 1, j + 1, 1), vid(i, j + 1, 1)))
            faces.append((vid(i, j + 1, 0), vid(i + 1, j + 1, 0), vid(i + 1, j, 0), vid(i, j, 0)))
            if not kept(i - 1, j):
                faces.append((vid(i, j, 0), vid(i, j, 1), vid(i, j + 1, 1), vid(i, j + 1, 0)))
            if not kept(i + 1, j):
                faces.append((vid(i + 1, j + 1, 0), vid(i + 1, j + 1, 1), vid(i + 1, j, 1), vid(i + 1, j, 0)))
            if not kept(i, j - 1):
                faces.append((vid(i + 1, j, 0), vid(i + 1, j, 1), vid(i, j, 1), vid(i, j, 0)))
            if not kept(i, j + 1):
                faces.append((vid(i, j + 1, 0), vid(i, j + 1, 1), vid(i + 1, j + 1, 1), vid(i + 1, j + 1, 0)))
    if cover:
        COVERS.append(tuple(outline) + (z1,))
    bevel = clamp_bevel(bevel, (x1 - x0, y1 - y0, z1 - z0))
    obj = make_object(name, verts, faces, drop=drop)
    return finish(obj, name, mat, group, bevel, segments)


def lathe(name, profile, center, mats, mat_index, group='detail', segments=24, cap_top=True):
    """Revolve (radius, z) profile points about a vertical axis; per-band material index."""
    cx, cy = center[0], center[1]
    verts, faces, fmat = [], [], []
    for r, z in profile:
        for k in range(segments):
            a = 2 * math.pi * k / segments
            verts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    for p in range(len(profile) - 1):
        for k in range(segments):
            a, b = p * segments + k, p * segments + (k + 1) % segments
            faces.append((a, b, b + segments, a + segments))
            fmat.append(mat_index[p])
    if cap_top:
        top = (len(profile) - 1) * segments
        faces.append(tuple(top + k for k in range(segments)))
        fmat.append(mat_index[-1])
    obj = make_object(name, verts, faces)
    for poly, m in zip(obj.data.polygons, fmat):
        poly.material_index = m
    finish(obj, name, list(mats), group, smooth=True)
    for poly in obj.data.polygons:
        poly.use_smooth = len(poly.vertices) == 4
    return obj


def line(name, points, radius, mat, group='detail', closed=False, resolution=1):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 1
    curve.bevel_depth = radius
    curve.bevel_resolution = resolution
    spline = curve.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for dst, p in zip(spline.points, points):
        dst.co = (*p, 1)
    spline.use_cyclic_u = closed
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    obj = bpy.context.object
    obj.select_set(False)
    return finish(obj, name, mat, group, smooth=True)


def rounded_rectangle(cx, cy, z, width, length, radius=.08):
    result = []
    for x, y, angle in ((cx + width/2-radius, cy + length/2-radius, 0),
                        (cx - width/2+radius, cy + length/2-radius, 90),
                        (cx - width/2+radius, cy - length/2+radius, 180),
                        (cx + width/2-radius, cy - length/2+radius, 270)):
        for k in range(5):
            a = math.radians(angle + k * 22.5)
            result.append((x + radius * math.cos(a), y + radius * math.sin(a), z))
    return result


# ---------------------------------------------------------------- safe detail helpers
def flush_bolt(name, pos, normal, group='trim'):
    """Hex flush fastener: r .017, 3 mm deep (1.5 mm proud), 1.5 mm top chamfer.

    Only the visible crown is modelled (16 triangles); the embedded half adds nothing.
    """
    n = v3(normal).normalized()
    a = Vector((1, 0, 0)) if abs(n.x) < .9 else Vector((0, 1, 0))
    u = n.cross(a).normalized()
    w = n.cross(u)
    p = v3(pos)
    top, ring = [], []
    for k in range(6):
        ang = math.radians(60 * k + 30)
        d = u * math.cos(ang) + w * math.sin(ang)
        top.append(p + n * .0015 + d * (.017 - .0015))
        ring.append(p - n * .0003 + d * .017)
    verts = top + ring
    faces = [tuple(range(6))] + [(k, k + 6, (k + 1) % 6 + 6, (k + 1) % 6) for k in range(6)]
    obj = make_object(name, verts, faces, recalc=False)
    mesh = obj.data
    if mesh.polygons[0].normal.dot(n) < 0:
        for poly in mesh.polygons:
            poly.flip()
    return finish(obj, name, 'fastener matte', group)


def projected_px(c, facing, along, W):
    """Lens width W projected at the headset from the seat eye (B)."""
    n, u = v3(facing).normalized(), v3(along).normalized()
    w = n.cross(u).normalized()
    off = v3(c) - v3(EYE)
    dist = off.length
    d = off / dist
    if n.dot(-d) <= 0:
        return None
    return W * w.cross(d).length / dist * FOCAL_PX


def lens_slot(name, c, facing, along, L, W, slot_group='trim', autowiden=True):
    """Dark slot (L+.04, W+.012) from -9 to +3 mm with a warm lens from +2 to +5 mm."""
    f = v3(facing).normalized()
    a = v3(along)
    a = (a - f * f.dot(a)).normalized()
    c = v3(c)
    if autowiden:
        px = projected_px(c, f, a, W)
        if px is not None and px < GLOW_PX_TARGET:
            new_w = W * GLOW_PX_TARGET / px
            WIDENED.append({'name': name, 'W': round(W, 4), 'widened_to': round(new_w, 4), 'px_before': round(px, 2)})
            W = new_w
    oriented_box(name + ' slot', c + f * (-.003), (L + .04, W + .012, .012), a, f, 'shadow', slot_group, 0)
    lens = oriented_box(name + ' lens', c + f * .0035, (L, W, .003), a, f, 'warm lens', 'emission', 0, drop='back')
    tag_lens(lens, c, f, a, L, W)
    return lens


def tag_lens(lens, c, f, a, L, W, kind='amber'):
    """Glow tags plus the per-vertex coordinate across W that drives the lens core gradient."""
    lens['glow'] = kind
    lens['glow_c'] = list(c)
    lens['facing'] = list(f)
    lens['along'] = list(a)
    lens['glow_size'] = [float(L), float(W)]
    across = f.cross(a).normalized()
    mesh = lens.data
    attr = mesh.attributes.new('lens_t', 'FLOAT', 'POINT')
    values = []
    for vert in mesh.vertices:
        t = (vert.co - c).dot(across) / max(W, 1e-6) + .5
        values.append(min(1.0, max(0.0, t)))
    attr.data.foreach_set('value', values)
    if kind == 'amber':
        LAMPS.append({'name': lens.name, 'c': c.copy(), 'f': f.copy(), 'a': a.copy(), 'L': float(L), 'W': float(W)})


def blue_strip(name, c, facing, along, L, H, proud=.004, top=None):
    """Blue diode strip on a vertical face: L along, H tall, `proud` thick.

    With `top`, H is a hairline target: the strip hangs from z = top and is widened (like
    lens_slot) only where it would project under GLOW_PX_TARGET at the headset, so the near
    segments stay thin LED lines and the far ones still pass the projected-width gate.
    """
    f = v3(facing).normalized()
    a = v3(along).normalized()
    c = v3(c)
    if top is not None:
        c.z = top - H / 2
        px = projected_px(c, f, a, H)
        if px is not None and px < GLOW_PX_TARGET:
            new_h = H * GLOW_PX_TARGET / px
            WIDENED.append({'name': name, 'W': round(H, 4), 'widened_to': round(new_h, 4), 'px_before': round(px, 2)})
            H = new_h
        c.z = top - H / 2
    # Long strips are split into <= .8 m meshes so they do not cap the emission
    # atlas scale; the first piece carries the glow tags for the whole strip.
    pieces = max(1, math.ceil(L / .8))
    step = L / pieces
    strip = None
    for k in range(pieces):
        pc = c + a * (-L / 2 + step * (k + .5))
        obj = oriented_box(name if k == 0 else f'{name} piece {k}', pc + f * (proud / 2), (step, H, proud), a, f,
                           'blue diode', 'emission', 0, drop='back')
        strip = strip or obj
    strip['glow'] = 'blue'
    strip['glow_c'] = list(c)
    strip['facing'] = list(f)
    strip['along'] = list(a)
    strip['glow_size'] = [float(L), float(H)]
    BLUES.append({'name': name, 'c': c.copy(), 'f': f.copy(), 'a': a.copy(), 'L': float(L)})
    return strip


def lip_ring(name, corners, plane_normal, tuck=.005, inset=.028, radius=.05, segs=3, offset=.010, thick=.006):
    """Flat gasket lip around a glazed opening.

    corners: the clear opening (3D, on the member-centreline glass plane).  The
    outer boundary tucks 5 mm under the members, the inner boundary sits 28 mm into
    the opening with r .05 inner corners; the lip lies 10 mm room-side of the glass
    and is 6 mm thick.  Only room-visible faces are built (front and inner wall).
    """
    N = v3(plane_normal).normalized()
    pts = [v3(p) for p in corners]
    n = len(pts)
    centre = sum(pts, Vector()) / n
    edge_n = []
    for i in range(n):
        e = (pts[(i + 1) % n] - pts[i])
        m = N.cross(e).normalized()
        mid = (pts[(i + 1) % n] + pts[i]) / 2
        if m.dot(centre - mid) < 0:
            m = -m
        edge_n.append(m)
    outer, inner = [], []
    for i in range(n):
        n1, n2 = edge_n[i - 1], edge_n[i]
        k = 1 + n1.dot(n2)
        miter = (n1 + n2) / k
        outer.append(pts[i] - miter * tuck)
        a0, a1 = -n1, -n2
        ang = a0.angle(a1)
        axis = a0.cross(a1)
        if ang < math.radians(4) or axis.length < 1e-9:
            inner.append([pts[i] + miter * inset])
            continue
        cc = pts[i] + miter * (inset + radius)
        steps = segs if ang > math.radians(25) else 1
        inner.append([cc + (Matrix.Rotation(ang * s / steps, 3, axis.normalized()) @ a0) * radius
                      for s in range(steps + 1)])
    front = N * (offset + thick)
    back = N * offset
    # Disconnected pieces (corner fan + straight run, runs split <= 1.2 m) keep every
    # UV island short; one perimeter-long island would cap the 1K trim atlas scale.
    verts, faces, kinds = [], [], []

    def add(points):
        base = len(verts)
        verts.extend(points)
        return base

    for i in range(n):
        arc, nxt = inner[i], inner[(i + 1) % n]
        run = max((outer[(i + 1) % n] - outer[i]).length, (nxt[0] - arc[-1]).length)
        k = max(1, math.ceil(run / 1.2))
        for s_ in range(k):
            t0, t1 = s_ / k, (s_ + 1) / k
            o0 = outer[i].lerp(outer[(i + 1) % n], t0)
            o1 = outer[i].lerp(outer[(i + 1) % n], t1)
            i0 = arc[-1].lerp(nxt[0], t0)
            i1 = arc[-1].lerp(nxt[0], t1)
            b = add([o0 + front, o1 + front, i1 + front, i0 + front, i0 + back, i1 + back])
            faces.append((b, b + 3, b + 2, b + 1)); kinds.append('front')
            faces.append((b + 3, b + 4, b + 5, b + 2)); kinds.append('wall')
            if s_ == 0 and len(arc) > 1:
                fan = add([outer[i] + front] + [q + front for q in arc] + [q + back for q in arc])
                m_ = len(arc)
                for j in range(m_ - 1):
                    faces.append((fan, fan + 1 + j, fan + 2 + j)); kinds.append('front')
                    faces.append((fan + 1 + j, fan + 1 + m_ + j, fan + 2 + m_ + j, fan + 2 + j)); kinds.append('wall')
    obj = make_object(name, verts, faces, recalc=False)
    mesh = obj.data
    for poly, kind in zip(mesh.polygons, kinds):
        if kind == 'front':
            if poly.normal.dot(N) < 0:
                poly.flip()
        else:
            towards = centre - poly.center
            towards -= N * towards.dot(N)
            if poly.normal.dot(towards) < 0:
                poly.flip()
    mesh.update()
    return finish(obj, name, 'gasket steel', 'trim')


def crease_cube(name, center, size, rotation, mat, group):
    """cushion(): a cube with Blender 4.x edge creases, Subdivision level 2, smooth."""
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    verts = [(sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    obj = make_object(name, verts, CUBE_FACES)
    mesh = obj.data
    attr = mesh.attributes.get('crease_edge') or mesh.attributes.new('crease_edge', 'FLOAT', 'EDGE')
    values = []
    for edge in mesh.edges:
        a, b = (mesh.vertices[i].co for i in edge.vertices)
        if abs(a.z - b.z) > 1e-6:
            values.append(.7)
        elif a.z > 0:
            values.append(.4)
        else:
            values.append(1.0)
    attr.data.foreach_set('value', values)
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new('Cushion subdivision', 'SUBSURF')
    mod.levels = 2
    mod.render_levels = 2
    bpy.ops.object.modifier_apply(modifier=mod.name)
    R = Euler(rotation or (0, 0, 0)).to_matrix().to_4x4()
    mesh.transform(Matrix.Translation(v3(center)) @ R)
    mesh.update()
    return finish(obj, name, mat, group, smooth=True)


def cushion(name, center, size, mat, group='seating', rotation=None):
    return crease_cube(name, center, size, rotation, mat, group)


def pillow(name, c, size, yaw, lean, mat, group='seating', side=1):
    """Two puffed 8x8 grids with pinched edges and a perimeter piping strip (~320 tris).

    size = (width, height, thickness); the pillow faces -side X (toward the aisle),
    leans `lean` degrees back toward the wall and yaws `yaw` degrees.
    """
    w, h, t = size
    n = 8
    verts, faces = [], []
    grids = []
    for sgn in (1, -1):
        idx = []
        for j in range(n + 1):
            row = []
            for i in range(n + 1):
                u = -1 + 2 * i / n
                v = -1 + 2 * j / n
                puff = t / 2 * max(0.0, (1 - abs(u) ** 2.2) * (1 - abs(v) ** 2.2)) ** .55
                x = u * w / 2 * (1 - .06 * (1 - v * v))
                z = v * h / 2 * (1 - .04 * (1 - u * u))
                row.append(len(verts))
                verts.append((sgn * (puff + .004), x, z))
            idx.append(row)
        grids.append(idx)
    front, back = grids
    for j in range(n):
        for i in range(n):
            faces.append((front[j][i], front[j][i + 1], front[j + 1][i + 1], front[j + 1][i]))
            faces.append((back[j][i], back[j + 1][i], back[j + 1][i + 1], back[j][i + 1]))
    rim = [front[0][i] for i in range(n)] + [front[j][n] for j in range(n)] + \
          [front[n][n - i] for i in range(n)] + [front[n - j][0] for j in range(n)]
    rim_b = [back[0][i] for i in range(n)] + [back[j][n] for j in range(n)] + \
            [back[n][n - i] for i in range(n)] + [back[n - j][0] for j in range(n)]
    m = len(rim)
    # Piping: a short outward band joining both halves round the perimeter.
    pipe = []
    for k in range(m):
        p = Vector(verts[rim[k]])
        q = Vector((0.0, p.y, p.z))
        out = q.normalized() * .006 if q.length > 1e-6 else Vector()
        pipe.append(len(verts)); verts.append(tuple(q + out))
    for k in range(m):
        a, b = rim[k], rim[(k + 1) % m]
        pa, pb = pipe[k], pipe[(k + 1) % m]
        ba, bb = rim_b[k], rim_b[(k + 1) % m]
        faces.append((a, pa, pb, b))
        faces.append((pa, ba, bb, pb))
    obj = make_object(name, verts, faces)
    R = (Matrix.Rotation(math.radians(yaw), 4, 'Z') @
         Matrix.Rotation(math.radians(side * lean), 4, 'Y'))
    flip = Matrix.Identity(4)
    if side > 0:
        flip = Matrix.Rotation(math.pi, 4, 'Z')
    obj.data.transform(Matrix.Translation(v3(c)) @ R @ flip)
    obj.data.update()
    return finish(obj, name, mat, group, smooth=True)


def area_rect(name, c, facing, along, L, W, watts, color, spread=150, kind='amber'):
    """Rectangular area light; columns (along, cross(-facing, along), -facing), size L on X."""
    f = v3(facing).normalized()
    a = v3(along)
    a = (a - f * f.dot(a)).normalized()
    data = bpy.data.lights.new(name, 'AREA')
    data.shape = 'RECTANGLE'
    data.size = L
    data.size_y = W
    data.energy = watts
    data.color = color
    data.spread = math.radians(spread)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    zc = -f
    yc = zc.cross(a)
    obj.matrix_world = Matrix.Translation(v3(c)) @ Matrix((a, yc, zc)).transposed().to_4x4()
    obj['light_kind'] = kind
    return obj


def point_light(name, c, watts, color, radius=.02, kind='practical'):
    data = bpy.data.lights.new(name, 'POINT')
    data.energy = watts
    data.color = color
    data.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = c
    obj['light_kind'] = kind
    return obj


def spot_light(name, c, direction, watts, color, size_deg, blend, radius=.02, kind='practical'):
    data = bpy.data.lights.new(name, 'SPOT')
    data.energy = watts
    data.color = color
    data.spot_size = math.radians(size_deg)
    data.spot_blend = blend
    data.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = c
    obj.rotation_euler = v3(direction).to_track_quat('-Z', 'Y').to_euler()
    obj['light_kind'] = kind
    return obj


# ---------------------------------------------------------------- materials
FABRICS = ('navy upholstery', 'fabric piping', 'grey pillow', 'oxblood cushion', 'navy pillow')


def _new_material(name, color, roughness, metallic):
    mat = bpy.data.materials.new('OD ' + name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1)
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    MATS[name] = mat
    return mat, nodes, mat.node_tree.links, bsdf


def _position(nodes):
    # Generated coordinates change when meshes merge for baking. World position
    # preserves the same physical grain size before and after the join.
    return nodes.new('ShaderNodeNewGeometry').outputs['Position']


def _grain(nodes, links, bsdf, color, noise, fabric, normal_in=None):
    """Fine bump grain and a x0.82..1.08 colour ramp; returns the colour socket."""
    tex = nodes.new('ShaderNodeTexNoise')
    tex.inputs['Scale'].default_value = 30 if fabric else 58
    tex.inputs['Detail'].default_value = 2
    links.new(_position(nodes), tex.inputs['Vector'])
    bump = nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = noise
    bump.inputs['Distance'].default_value = .0015 if fabric else .002
    links.new(tex.outputs['Fac'], bump.inputs['Height'])
    if normal_in is not None:
        links.new(normal_in, bump.inputs['Normal'])
    links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    ramp = nodes.new('ShaderNodeValToRGB')
    lo, hi = (.70, 1.12) if fabric else (.82, 1.08)
    ramp.color_ramp.elements[0].color = (*[v * lo for v in color], 1)
    ramp.color_ramp.elements[1].color = (*[min(1, v * hi) for v in color], 1)
    links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
    return ramp.outputs['Color']


def _mix(nodes, links, fac, a, b, blend='MIX'):
    mix = nodes.new('ShaderNodeMixRGB')
    mix.blend_type = blend
    if isinstance(fac, (int, float)):
        mix.inputs['Fac'].default_value = fac
    else:
        links.new(fac, mix.inputs['Fac'])
    for socket, value in ((mix.inputs['Color1'], a), (mix.inputs['Color2'], b)):
        if isinstance(value, (tuple, list)):
            socket.default_value = (*value[:3], 1)
        else:
            links.new(value, socket)
    return mix.outputs['Color']


def _math(nodes, links, op, a, b=None):
    node = nodes.new('ShaderNodeMath')
    node.operation = op
    for socket, value in zip(node.inputs, (a, b)):
        if value is None:
            continue
        if isinstance(value, (int, float)):
            socket.default_value = value
        else:
            links.new(value, socket)
    return node.outputs[0]


def _ao(nodes, links, distance, samples=16, only_local=False):
    ao = nodes.new('ShaderNodeAmbientOcclusion')
    ao.samples = samples
    ao.only_local = only_local
    ao.inputs['Distance'].default_value = distance
    return ao.outputs['AO']


def material(name, color, roughness=.55, metallic=0.0, noise=0.0, emission=None, emission_strength=1.0, sheen=0.0,
             sheen_tint=(1.0, 1.0, 1.0)):
    mat, nodes, links, bsdf = _new_material(name, color, roughness, metallic)
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*emission, 1)
        bsdf.inputs['Emission Strength'].default_value = emission_strength
    if sheen:
        bsdf.inputs['Sheen Weight'].default_value = sheen
        bsdf.inputs['Sheen Roughness'].default_value = .5
        bsdf.inputs['Sheen Tint'].default_value = (*sheen_tint, 1)
    if noise:
        links.new(_grain(nodes, links, bsdf, color, noise, name in FABRICS), bsdf.inputs['Base Color'])
    return mat


ARMOR_COLOR = (.47, .455, .43)      # off-white ceramic, barely warm (look pass: was .50/.46/.40 cream)
BENCH_IVORY = (.26, .26, .265)      # bench foundations: darker off-white so they sit under the lamps
UPPER_ARMOR = (.15, .155, .165)     # fin's 49 deg upper plates: graphite-grey, keeps the front view's top corners dark
DECK_METAL = (.031, .035, .045)     # navy-graphite satin plate (look pass: was .050/.052/.058)
RIBBED_DECK = (.034, .038, .048)    # slatted grille, same steel as the plates


def armor_material(name='warm ceramic armor', color=ARMOR_COLOR, foot_gradient=False):
    """Ceramic armour: bevel-normal grain, broad value noise and AO grime in the creases.

    foot_gradient darkens the lower part of a bench foundation (z .55 -> .95) so the base
    reads as a lit top edge falling into the toe kick instead of one flat bright box.
    """
    mat, nodes, links, bsdf = _new_material(name, color, .45, 0.0)
    bevel = nodes.new('ShaderNodeBevel')
    bevel.samples = 8
    bevel.inputs['Radius'].default_value = .006
    base = _grain(nodes, links, bsdf, color, .08, False, bevel.outputs['Normal'])
    broad = nodes.new('ShaderNodeTexNoise')
    broad.inputs['Scale'].default_value = 4
    broad.inputs['Detail'].default_value = 3
    links.new(_position(nodes), broad.inputs['Vector'])
    value = nodes.new('ShaderNodeMapRange')
    value.inputs['To Min'].default_value = .94
    value.inputs['To Max'].default_value = 1.06
    links.new(broad.outputs['Fac'], value.inputs['Value'])
    shaded = _mix(nodes, links, 1.0, base, (1, 1, 1), 'MULTIPLY')
    links.new(value.outputs['Result'], shaded.node.inputs['Color2'])
    grime = _math(nodes, links, 'MULTIPLY', _math(nodes, links, 'SUBTRACT', 1.0, _ao(nodes, links, .06)), .6)
    dirt = tuple(v * .36 for v in color)
    result = _mix(nodes, links, grime, shaded, dirt)
    if foot_gradient:
        sep = nodes.new('ShaderNodeSeparateXYZ')
        links.new(_position(nodes), sep.inputs['Vector'])
        ramp = nodes.new('ShaderNodeMapRange')
        ramp.inputs['From Min'].default_value = FOUNDATION[0]
        ramp.inputs['From Max'].default_value = FOUNDATION[1]
        ramp.inputs['To Min'].default_value = .62
        ramp.inputs['To Max'].default_value = 1.0
        links.new(sep.outputs['Z'], ramp.inputs['Value'])
        result = _mix(nodes, links, 1.0, result, (1, 1, 1), 'MULTIPLY')
        links.new(ramp.outputs['Result'], result.node.inputs['Color2'])
    links.new(result, bsdf.inputs['Base Color'])
    return mat


def deck_material():
    color = DECK_METAL
    mat, nodes, links, bsdf = _new_material('deck metal', color, .50, 0.0)
    base = _grain(nodes, links, bsdf, color, .12, False)
    sep = nodes.new('ShaderNodeSeparateXYZ')
    links.new(_position(nodes), sep.inputs['Vector'])
    gx = _math(nodes, links, 'FLOOR', _math(nodes, links, 'DIVIDE', _math(nodes, links, 'ADD', sep.outputs['X'], 3.255), 2.17))
    gy = _math(nodes, links, 'FLOOR', _math(nodes, links, 'DIVIDE', _math(nodes, links, 'ADD', sep.outputs['Y'], 7.235), 1.73))
    comb = nodes.new('ShaderNodeCombineXYZ')
    links.new(gx, comb.inputs['X'])
    links.new(gy, comb.inputs['Y'])
    white = nodes.new('ShaderNodeTexWhiteNoise')
    white.noise_dimensions = '3D'
    links.new(comb.outputs['Vector'], white.inputs['Vector'])
    plate = nodes.new('ShaderNodeMapRange')
    plate.inputs['To Min'].default_value = .85
    plate.inputs['To Max'].default_value = 1.12
    links.new(white.outputs['Value'], plate.inputs['Value'])
    varied = _mix(nodes, links, 1.0, base, (1, 1, 1), 'MULTIPLY')
    links.new(plate.outputs['Result'], varied.node.inputs['Color2'])
    occl = _math(nodes, links, 'SUBTRACT', 1.0, _ao(nodes, links, .05, 16, True))
    links.new(_mix(nodes, links, occl, varied, (.012, .014, .019)), bsdf.inputs['Base Color'])
    return mat


def vent_material():
    deck = DECK_METAL
    mat, nodes, links, bsdf = _new_material('vent grille', deck, .50, 0.0)
    brick = nodes.new('ShaderNodeTexBrick')
    brick.offset = .5
    brick.inputs['Scale'].default_value = 1.0
    brick.inputs['Brick Width'].default_value = .060
    brick.inputs['Row Height'].default_value = .024
    brick.inputs['Mortar Size'].default_value = .010
    brick.inputs['Color1'].default_value = (.007, .010, .015, 1)
    brick.inputs['Color2'].default_value = (.007, .010, .015, 1)
    brick.inputs['Mortar'].default_value = (*deck, 1)
    links.new(_position(nodes), brick.inputs['Vector'])
    links.new(brick.outputs['Color'], bsdf.inputs['Base Color'])
    return mat


def warm_lens_material():
    """Lens with a white-hot core across W from the per-vertex 'lens_t' attribute."""
    mat, nodes, links, bsdf = _new_material('warm lens', (.9, .6, .4), .45, 0.0)
    attr = nodes.new('ShaderNodeAttribute')
    attr.attribute_type = 'GEOMETRY'
    attr.attribute_name = 'lens_t'
    x = _math(nodes, links, 'DIVIDE', _math(nodes, links, 'SUBTRACT', attr.outputs['Fac'], .5), .18)
    g = _math(nodes, links, 'EXPONENT', _math(nodes, links, 'MULTIPLY', _math(nodes, links, 'MULTIPLY', x, x), -1.0))
    edge = tuple(v * 1.2 for v in (1.0, .36, .07))
    core = tuple(v * 1.5 for v in (1.0, .86, .68))
    links.new(_mix(nodes, links, g, edge, core), bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = 1.0
    return mat


def build_materials():
    armor_material()
    armor_material('bench ivory', BENCH_IVORY, foot_gradient=True)
    armor_material('upper armor', UPPER_ARMOR)
    material('structural graphite', (.032, .038, .052), .42, .35, .10)
    material('hatch graphite', (.047, .057, .07), .44, .52, .09)
    # Door leaves: lighter graphite (was .022/.026/.032, 3 luma against a target of 14).
    material('door graphite', (.085, .095, .11), .45, .30, .06)
    deck_material()
    material('ribbed deck', RIBBED_DECK, .45, 0.0, .10)
    vent_material()
    material('shadow', (.007, .010, .015), .61, .30)
    material('fastener', (.115, .13, .15), .40, .60)
    material('muted red stripe', (.24, .020, .018), .50, 0.0)
    material('gasket steel', (.17, .19, .22), .42, .10)
    material('trim', (.30, .31, .33), .40, 0.0)
    material('fastener matte', (.10, .10, .11), .55, 0.0)
    # Final look pass: navy fabric bright enough to stay navy under the warm practicals (it read as
    # brown leather at .010/.016/.040), a cool velvet sheen that the seated-camera gloss bake turns
    # into a rim from the earthshine, and a grain coarse enough to read as weave and tufting.
    material('navy upholstery', (.018, .028, .070), .90, 0, .30, sheen=.6, sheen_tint=(.5, .6, 1.0))
    material('fabric piping', (.030, .040, .066), .80, 0)
    material('grey pillow', (.16, .165, .175), .92, 0, .22, sheen=.4, sheen_tint=(.6, .7, 1.0))
    material('oxblood cushion', (.075, .010, .014), .91, 0, .20, sheen=.4, sheen_tint=(1.0, .6, .6))
    material('navy pillow', (.024, .036, .090), .92, 0, .25, sheen=.6, sheen_tint=(.5, .6, 1.0))
    # Groove beds of the slatted runners, inserts and side grates: dark steel, not the 'shadow'
    # void (black-and-grey zebra stripes); the vent beds stay 'shadow'.
    material('groove bed', (.045, .050, .062), .50, 0.0)
    # The side-table tumblers: polished steel that the seated-camera gloss bake turns into a
    # bright accent (it read as a dark post in 'fastener').
    material('polished steel', (.60, .62, .65), .18, 1.0)
    warm_lens_material()
    # Emission .4 (was 1.5, then .6): a hairline deep-blue LED through AgX, not a neon bar (the
    # guide-light pools come from the blue bake lights; blue_emit_gain scales this in the bake).
    material('blue diode', (.02, .16, .39), .45, 0.0, emission=(.015, .28, 1.0), emission_strength=.4)


# ---------------------------------------------------------------- deck
ROW_CENTRES = (-6.0025, -4.64, -2.91, -1.18, .55, 2.28, 4.01, 5.74)
ROWS = ((-6.48, -5.505), (-5.485, -3.795), (-3.755, -2.065), (-2.025, -.335),
        (-.295, 1.395), (1.435, 3.125), (3.165, 4.855), (4.895, 6.585))
SIDE_HALVES = ((1.10, 2.03), (2.05, 2.98))
GRATE_X = (3.00, 3.38)
OUTBOARD_X = (3.47, 4.19)
GUTTER_X = (4.21, 4.69)
CURB_X = 3.42
SEATING_Y = ((-4.40, -3.30), (-2.90, 1.65), (3.35, 4.40), (5.60, 6.02))
SCREEN_VENT_Y = (4.27, 4.39)
SCREEN_VENT_FRAME = .02
SIDE_VENTS = [(-1, (1.45, 1.75, -4.85, -3.95)), (1, (1.45, 1.75, -4.85, -3.95)), (1, (1.30, 1.60, 3.20, 4.10))]


def deck_plate(name, outline, holes=(), mat='deck metal', bevel=.008):
    return cell_solid(name, outline, list(holes), SLAB_TOP, PLATE_TOP, mat, 'deck', bevel, 2)


def vent(name, x0, x1, y0, y1, frame=.03):
    """Recessed vent: bed .456, frame bars top .484 (non-overlapping), grille plate top .470."""
    zbox(name + ' bed', x0, x1, y0, y1, SLAB_TOP, VENT_BED, 'shadow', 'deck', cover=True)
    zbox(name + ' frame bar', x0, x0 + frame, y0, y1, VENT_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    zbox(name + ' frame bar', x1 - frame, x1, y0, y1, VENT_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    zbox(name + ' frame bar', x0 + frame, x1 - frame, y0, y0 + frame, VENT_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    zbox(name + ' frame bar', x0 + frame, x1 - frame, y1 - frame, y1, VENT_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    zbox(name + ' grille', x0 + frame, x1 - frame, y0 + frame, y1 - frame, VENT_BED, VENT_GRILLE, 'vent grille', 'deck')


def slat(name, x0, x1, y0, y1, top=PLATE_TOP, bottom=GROOVE_BED, mat='ribbed deck', bevel=.004):
    return zbox(name, x0, x1, y0, y1, bottom, top, mat, 'deck', bevel, 1)


def grooved_panel(name, cx, y0, y1, slats, slat_len, half=1.07):
    """Grooved runner: 'groove bed' .472, .080 slats at .096 pitch (16 mm grooves, top .480),
    side frame bars .05 wide (top .484) and end bars between them."""
    cy = (y0 + y1) / 2
    slat_len = min(slat_len, (y1 - y0) - .03)
    zbox(name + ' bed', cx - half, cx + half, y0, y1, SLAB_TOP, GROOVE_BED, 'groove bed', 'deck', cover=True)
    span = (slats - 1) * .096 + .080
    for k in range(slats):
        x = cx - span / 2 + .04 + k * .096
        slat(f'{name} slat {k:02d}', x - .04, x + .04, cy - slat_len / 2, cy + slat_len / 2)
    for sgn in (-1, 1):
        zbox(name + ' side frame bar', cx + sgn * 1.02 - .025 + .025 * sgn, cx + sgn * 1.02 + .025 + .025 * sgn,
             y0, y1, GROOVE_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    for yy in ((y0, y0 + .03), (y1 - .03, y1)):
        zbox(name + ' end bar', cx - 1.02, cx + 1.02, yy[0], yy[1], GROOVE_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)


def deck_latch(name, x, y):
    """.10 x .12 latch (top .484) with a .05 x .04 'shadow' notch recessed 2 mm."""
    outline = (x - .05, x + .05, y - .06, y + .06)
    notch = (x - .025, x + .025, y - .02, y + .02)
    cell_solid(name, outline, [notch], .470, BAR_TOP, 'deck metal', 'deck', .002, 1, cover=False)
    zbox(name + ' notch', *notch, .470, BAR_TOP - .002, 'shadow', 'deck')


def plate_bolts(name, outline, holes=()):
    x0, x1, y0, y1 = outline
    ym = (y0 + y1) / 2
    for i, (x, y) in enumerate(((x0 + .04, y0 + .04), (x1 - .04, y0 + .04), (x0 + .04, y1 - .04),
                                (x1 - .04, y1 - .04), (x0 + .04, ym), (x1 - .04, ym))):
        if any(h[0] - .03 < x < h[1] + .03 and h[2] - .03 < y < h[3] + .03 for h in holes):
            continue
        flush_bolt(f'{name} flush bolt {i}', (x, y, PLATE_TOP), (0, 0, 1))


def subtract_ranges(span, ranges, clearance=.01, minimum=.15):
    pieces = [span]
    for a, b in ranges:
        out = []
        for p, q in pieces:
            if b + clearance <= p or a - clearance >= q:
                out.append((p, q))
                continue
            if a - clearance > p:
                out.append((p, a - clearance))
            if b + clearance < q:
                out.append((b + clearance, q))
        pieces = out
    return [(p, q) for p, q in pieces if q - p >= minimum]


def centre_column():
    # Rows -6.0025 (trimmed), -2.91, -1.18 and 5.74 are flat plates.
    deck_plate('Deck plate centre aft', (-1.07, 1.07, -6.17, ROWS[0][1]))
    deck_plate('Deck plate centre 02', (-1.07, 1.07, *ROWS[2]))
    deck_plate('Deck plate centre 03', (-1.07, 1.07, *ROWS[3]))
    deck_plate('Deck plate centre 07', (-1.07, 1.07, *ROWS[7]))
    # Aft and front grooved runners, then the flat plates either side of the screen vent.
    grooved_panel('Aft runner', 0.0, *ROWS[1], 21, 1.64)
    grooved_panel('Front runner', 0.0, 1.415, 4.00, 21, 2.585)
    deck_plate('Deck plate centre 06a', (-1.07, 1.07, 4.02, SCREEN_VENT_Y[0] - SCREEN_VENT_FRAME))
    deck_plate('Deck plate centre 06b', (-1.07, 1.07, SCREEN_VENT_Y[1] + SCREEN_VENT_FRAME, ROWS[6][1]))
    # Row .55: a flat centre plate with two transverse seams,
    # grooved inserts either side with a vent each, and latches at the seam ends.
    y0, y1 = ROWS[4]
    for k, (a, b) in enumerate(((y0, .50), (.52, 1.00), (1.02, y1))):
        deck_plate(f'Deck plate centre 04 piece {k}', (-.47, .47, a, b))
    for a, b in ((.50, .52), (1.00, 1.02)):
        zbox('Deck centre seam shadow', -.47, .47, a, b, SLAB_TOP, PLATE_TOP - .002, 'shadow', 'deck', cover=True)
    for sgn in (-1, 1):
        vx = (.52, .70) if sgn > 0 else (-.70, -.52)
        vrect = (vx[0], vx[1], .55, .98)
        bed = (.47, 1.07) if sgn > 0 else (-1.07, -.47)
        cell_solid(f'Insert bed {sgn}', (bed[0], bed[1], y0, y1), [vrect], SLAB_TOP, GROOVE_BED, 'groove bed', 'deck')
        for k in range(6):
            x = sgn * (.55 + k * .096)
            xa, xb = x - .04, x + .04
            if xb > vx[0] - .001 and xa < vx[1] + .001:
                for a, b in ((y0 + .025, .53), (1.00, y1 - .025)):
                    slat(f'Insert slat {sgn}-{k}', xa, xb, a, b)
            else:
                slat(f'Insert slat {sgn}-{k}', xa, xb, y0 + .025, y1 - .025)
        vent(f'Insert vent {sgn}', *vrect, frame=.03)
        for yy in (.51, 1.01):
            deck_latch(f'Deck latch {sgn}-{yy}', sgn * .47, yy)


def side_columns():
    for side in (-1, 1):
        for r, (y0, y1) in enumerate(ROWS):
            spans = [(y0, y1)]
            if r == 6:
                spans = [(y0, SCREEN_VENT_Y[0] - SCREEN_VENT_FRAME), (SCREEN_VENT_Y[1] + SCREEN_VENT_FRAME, y1)]
            if r == 0:
                spans = [(-6.17, y1)]
            for s, (a, b) in enumerate(spans):
                for h, (xa, xb) in enumerate(SIDE_HALVES):
                    x0, x1 = (xa, xb) if side > 0 else (-xb, -xa)
                    outline = (x0, x1, a, b)
                    holes = []
                    for vs, (vx0, vx1, vy0, vy1) in SIDE_VENTS:
                        if vs != side:
                            continue
                        rect = (vx0, vx1, vy0, vy1) if side > 0 else (-vx1, -vx0, vy0, vy1)
                        if rect[0] >= x0 and rect[1] <= x1 and rect[2] >= a and rect[3] <= b:
                            holes.append(rect)
                    name = f'Deck plate side {side}-{r}-{s}-{h}'
                    deck_plate(name, outline, holes)
                    cx, cy = (x0 + x1) / 2, (a + b) / 2
                    if math.hypot(cx, cy) <= 3.0:
                        plate_bolts(name, outline, holes)
        for vs, (vx0, vx1, vy0, vy1) in SIDE_VENTS:
            if vs == side:
                rect = (vx0, vx1, vy0, vy1) if side > 0 else (-vx1, -vx0, vy0, vy1)
                vent(f'Deck vent {side}-{vy0}', *rect, frame=.03)


def grates_and_edges():
    rail_xs = [GRATE_X[0] + .0035 + .0215 + k * .066 for k in range(6)]
    for side in (-1, 1):
        g0, g1 = (GRATE_X if side > 0 else (-GRATE_X[1], -GRATE_X[0]))
        spans = [(-6.15, ROWS[0][1])] + list(ROWS[1:6]) + [(ROWS[7][0], 5.58)]
        for k, (a, b) in enumerate(spans):
            zbox(f'Side grate bed {side}-{k}', g0, g1, a, b, SLAB_TOP, GROOVE_BED, 'groove bed', 'deck', cover=True)
            for j, x in enumerate(rail_xs):
                x = side * x
                slat(f'Grate rail {side}-{k}-{j}', x - .0215, x + .0215, a + .02, b - .02, bevel=.004)
        # Filler plates where the grate stops (under the diagonal curb and the tables).
        fx = (3.00, 3.44) if side > 0 else (-3.44, -3.00)
        deck_plate(f'Deck filler plate {side}-6', (fx[0], fx[1], *ROWS[6]))
        deck_plate(f'Deck filler plate {side}-7', (fx[0], fx[1], 5.60, ROWS[7][1]))
        # Outboard plates between the guide and the gutter, wherever no seating stands.
        ox = OUTBOARD_X if side > 0 else (-OUTBOARD_X[1], -OUTBOARD_X[0])
        for r, (y0, y1) in enumerate(ROWS):
            span = (-6.05, y1) if r == 0 else (y0, y1)
            for k, (a, b) in enumerate(subtract_ranges(span, SEATING_Y)):
                deck_plate(f'Deck outboard plate {side}-{r}-{k}', (ox[0], ox[1], a, b))
        gx = GUTTER_X if side > 0 else (-GUTTER_X[1], -GUTTER_X[0])
        for k, (a, b) in enumerate(subtract_ranges((-6.05, 6.40), SEATING_Y + ((1.85, 3.20),))):
            zbox(f'Outer deck gutter {side}-{k}', gx[0], gx[1], a, b, SLAB_TOP, BAR_TOP, 'deck metal', 'deck', .006, 2, cover=True)


def guide_curbs():
    """'shadow' curbs (top .515) at x +/-3.42 with hairline blue diodes at the top of their aisle faces."""
    zc = (PLATE_TOP + .002 + PLATE_TOP + .032) / 2
    diode_top, diode_h = .512, .012
    for side in (-1, 1):
        x = side * CURB_X
        zbox(f'Guide curb rear {side}', x - .03, x + .03, -6.30, -3.30, SLAB_TOP, CURB_TOP, 'shadow', 'deck', .004, 1, cover=True)
        blue_strip(f'Curb blue diode rear {side}', (x - side * .03, -4.80, zc), (-side, 0, 0), (0, 1, 0), 2.98, diode_h, top=diode_top)
        pts = [(x, 1.70), (x, 3.30), (side * 2.42, 4.20), (side * 2.42, 4.26)]
        poly = band_polygon(pts, [.06, .06, .06])
        xy_prism(f'Guide curb front {side}', poly, SLAB_TOP, CURB_TOP, 'shadow', 'deck', .004, 1)
        for k in range(3):
            a, b = pts[k], pts[k + 1]
            tx, ty = unit2(a, b)
            nx, ny = ty, -tx
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if nx * (0 - mx) < 0 or (abs(nx) < 1e-6 and ny * (0 - my) < 0):
                nx, ny = -nx, -ny
            length = math.hypot(b[0] - a[0], b[1] - a[1]) - .06
            c = (mx + nx * .03, my + ny * .03, zc)
            blue_strip(f'Curb blue diode front {side}-{k}', c, (nx, ny, 0), (tx, ty, 0), max(length, .03), diode_h, top=diode_top)


def screen_vent():
    y0, y1 = SCREEN_VENT_Y
    f = SCREEN_VENT_FRAME
    zbox('Screen vent bed', -2.98, 2.98, y0 - f, y1 + f, SLAB_TOP, VENT_BED, 'shadow', 'deck', cover=True)
    for yy in ((y0 - f, y0), (y1, y1 + f)):
        zbox('Screen vent frame bar', -2.98, 2.98, yy[0], yy[1], VENT_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    for sgn in (-1, 1):
        xa, xb = sorted((sgn * 2.95, sgn * 2.98))
        zbox('Screen vent end bar', xa, xb, y0, y1, VENT_BED, BAR_TOP, 'deck metal', 'deck', .003, 1)
    for k in range(98):
        x = -2.91 + k * .06
        if 2.56 < abs(x) < 2.94:
            continue
        slat(f'Screen vent slat {k:02d}', x - .01, x + .01, y0, y1, VENT_GRILLE, VENT_BED, 'deck metal', 0)
    for sgn in (-1, 1):
        # z .462 keeps the tilted slot under the frame bar top (.484); the lens's lower
        # edge tucks into the vent bed.
        lens_slot(f'Screen vent lamp {sgn}', (sgn * 2.75, y1, .462), (0, -.96, .27), (1, 0, 0), .30, .030, slot_group='trim')


def threshold_grate():
    zbox('Hatch threshold grate bed', -1.2, 1.2, -6.35, -6.19, SLAB_TOP, VENT_BED, 'shadow', 'deck', cover=True)
    for k in range(30):
        x = -1.175 + .015 + k * .08
        slat(f'Threshold slat {k:02d}', x - .015, x + .015, -6.34, -6.20, VENT_GRILLE, VENT_BED, 'deck metal', 0)


def deck():
    centre_column()
    side_columns()
    grates_and_edges()
    guide_curbs()
    screen_vent()
    threshold_grate()


SEAM_FILL_TOP = VENT_GRILLE   # 10 mm under the plate tops, below the plates' .008 bevel
NARROW_SEAM = .029            # channels narrower than the 30 mm plate depth get filled


def deck_slab():
    """Slab top (.450) only where nothing covers it: seams, channels and toe gaps.

    Built last from COVERS so hidden slab area never takes atlas space.  Cells share
    vertices on one grid, so the plane has no T-junction cracks.

    Open channels narrower than NARROW_SEAM (20 mm seams, 10 mm slots) would be deeper
    than wide, which shimmers at headset resolution.  Their floor is raised to
    SEAM_FILL_TOP, with short skirts where a filled channel opens into a deeper one or
    meets a cover lower than the fill (vent beds), so no gap opens under the fill.
    """
    bx0, bx1, by0, by1 = -4.69, 4.69, REAR, 6.585
    rects = []
    for cov in COVERS:
        a, b, c, d = cov[:4]
        top = cov[4] if len(cov) > 4 else 9.0
        r = (max(bx0, a), min(bx1, b), max(by0, c), min(by1, d), top)
        if r[1] > r[0] + 1e-6 and r[3] > r[2] + 1e-6:
            rects.append(r)
    xs = sorted({round(v, 5) for r in rects for v in (r[0], r[1])} | {bx0, bx1})
    ys = sorted({round(v, 5) for r in rects for v in (r[2], r[3])} | {by0, by1})
    xs = [x for x in xs if bx0 <= x <= bx1]
    ys = [y for y in ys if by0 <= y <= by1]
    nx, ny = len(xs) - 1, len(ys) - 1
    real_x = [xs[i + 1] - xs[i] >= 1e-5 for i in range(nx)]
    real_y = [ys[j + 1] - ys[j] >= 1e-5 for j in range(ny)]
    cover_top = {}
    for j in range(ny):
        cy = (ys[j] + ys[j + 1]) / 2
        row = [r for r in rects if r[2] < cy < r[3]]
        for i in range(nx):
            cx = (xs[i] + xs[i + 1]) / 2
            tops = [r[4] for r in row if r[0] < cx < r[1]]
            cover_top[(i, j)] = max(tops) if tops else None

    def is_open(i, j):
        return real_x[i] and real_y[j] and cover_top[(i, j)] is None

    def run(i, j, axis):
        """Width of the open region through cell (i, j) along one axis."""
        n, real, edges = (nx, real_x, xs) if axis == 0 else (ny, real_y, ys)
        k0 = k1 = (i if axis == 0 else j)

        def passable(k):
            cell = (k, j) if axis == 0 else (i, k)
            return not real[k] or is_open(*cell)
        while k0 - 1 >= 0 and passable(k0 - 1):
            k0 -= 1
        while k1 + 1 < n and passable(k1 + 1):
            k1 += 1
        return edges[k1 + 1] - edges[k0]

    narrow = set()
    for j in range(ny):
        for i in range(nx):
            if is_open(i, j) and min(run(i, j, 0), run(i, j, 1)) < NARROW_SEAM:
                narrow.add((i, j))

    def neighbour(i, j, di, dj):
        i, j = i + di, j + dj
        while 0 <= i < nx and 0 <= j < ny and not (real_x[i] and real_y[j]):
            i, j = i + di, j + dj
        return (i, j) if 0 <= i < nx and 0 <= j < ny else None

    # Crossings of two narrow channels: a small open square whose open neighbours are all filled.
    crossings = set()
    for j in range(ny):
        for i in range(nx):
            if not is_open(i, j) or (i, j) in narrow:
                continue
            if xs[i + 1] - xs[i] > NARROW_SEAM or ys[j + 1] - ys[j] > NARROW_SEAM:
                continue
            opens = [c for c in (neighbour(i, j, *d) for d in ((-1, 0), (1, 0), (0, -1), (0, 1))) if c and is_open(*c)]
            if opens and all(c in narrow for c in opens):
                crossings.add((i, j))
    narrow |= crossings

    index, verts, faces = {}, [], []

    def vid(i, j, z):
        key = (i, j, round(z, 5))
        if key not in index:
            index[key] = len(verts)
            verts.append((xs[i], ys[j], z))
        return index[key]

    skirts = 0
    for j in range(ny):
        for i in range(nx):
            if not is_open(i, j):
                continue
            z = SEAM_FILL_TOP if (i, j) in narrow else SLAB_TOP
            faces.append((vid(i, j, z), vid(i + 1, j, z), vid(i + 1, j + 1, z), vid(i, j + 1, z)))
            if (i, j) not in narrow:
                continue
            # (direction, edge corners in skirt winding order: outward-facing quads)
            for d, (a, b) in (((-1, 0), ((i, j + 1), (i, j))), ((1, 0), ((i + 1, j), (i + 1, j + 1))),
                              ((0, -1), ((i, j), (i + 1, j))), ((0, 1), ((i + 1, j + 1), (i, j + 1)))):
                nb = neighbour(i, j, *d)
                if nb is None or nb in narrow:
                    continue
                top = cover_top[nb]
                if top is None:
                    lo = SLAB_TOP
                elif top < SEAM_FILL_TOP - 1e-6:
                    lo = max(SLAB_TOP, top)
                else:
                    continue
                faces.append((vid(*a, lo), vid(*b, lo), vid(*b, SEAM_FILL_TOP), vid(*a, SEAM_FILL_TOP)))
                skirts += 1
    obj = make_object('Deck slab seams', verts, faces, recalc=False)
    obj['narrow_cells'] = len(narrow)
    obj['skirts'] = skirts
    return finish(obj, 'Deck slab seams', 'shadow', 'deck')


UNDERLAY_TOP = SLAB_TOP - .006   # 6 mm under the slab, below the plates' lower bevels


def deck_underlay():
    """One opaque sheet under the whole deck, two triangles.

    Plate, bed and curb bottoms are culled and their lower bevels stop short of the slab
    cells, so a ray down a seam could leave the cabin and meet the sky: faint dots in the
    black seams and, over the Earth's cities, warm dashes on the floor. The sheet closes
    every such sliver. It sits in full shadow and is only ever seen through a hairline, so
    it takes a token patch of the atlas (`atlas_token`, see build_runtime.py).
    """
    z = UNDERLAY_TOP
    x, y0, y1 = HALF_WIDTH + .05, REAR - .05, FRONT + .05
    obj = make_object('Deck underlay', [(-x, y0, z), (x, y0, z), (x, y1, z), (-x, y1, z)], [(0, 1, 2, 3)], recalc=False)
    obj['atlas_token'] = True
    return finish(obj, 'Deck underlay', 'shadow', 'deck')


# ---------------------------------------------------------------- structure
SIDE_HALF = {'heavy': .29 + .012, 'slim': .06, 'fin': .45 + .012}
ROOF_HALF = {'heavy': .085, 'slim': .06, 'fin': .085}
PLATE_BANDS = ((1.92, 2.30), (2.46, 3.02), (3.06, 3.56))
TRANSOM = (.17, .15)        # across, depth
SHOULDER = (.15, .13)
ROOF_MULLION = (.10, .11)


def inward3(a, b):
    nx, nz = inward2(a, b)
    return Vector((nx, 0.0, nz))


def up3(a, b):
    tx, tz = unit2(a, b)
    return Vector((tx, 0.0, tz))


def inset_line(points, dists):
    """Shift each segment toward the room by dists[i]; mitred joints."""
    segs = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        nx, nz = inward2(a, b)
        segs.append(((a[0] + nx * dists[i], a[1] + nz * dists[i]), unit2(a, b)))
    out = [segs[0][0]]
    for i in range(1, len(segs)):
        hit = line_intersect(segs[i - 1][0], segs[i - 1][1], segs[i][0], segs[i][1])
        out.append(hit if hit is not None else segs[i][0])
    a, b = points[-2], points[-1]
    nx, nz = inward2(a, b)
    out.append((b[0] + nx * dists[-1], b[1] + nz * dists[-1]))
    return out


def at_z_on_line(p, q, z):
    t = (z - p[1]) / (q[1] - p[1])
    return (p[0] + t * (q[0] - p[0]), z)


def seg_plate(name, a, b, za, zb, off, y0, y1, thick, mat, group='shell', bevel=.012, drop=None):
    """Plate on the room side of profile segment a-b between profile heights za..zb."""
    pa, pb = along_profile(a, b, za, off), along_profile(a, b, zb, off)
    pts = [(pa[0], y0, pa[1]), (pb[0], y0, pb[1]), (pb[0], y1, pb[1]), (pa[0], y1, pa[1])]
    return extrude(name, pts, inward3(a, b) * thick, mat, group, bevel, drop=drop)


def cheek_plate(name, a, b, za, zb, off0, off1, y, dy, mat, group='shell', bevel=.004):
    pts = []
    for z, off in ((za, off0), (zb, off0), (zb, off1), (za, off1)):
        p = along_profile(a, b, z, off)
        pts.append((p[0], y, p[1]))
    return extrude(name, pts, (0, dy, 0), mat, group, bevel)


def mount(a, b, z, off, y):
    p = along_profile(a, b, z, off)
    return Vector((p[0], y, p[1]))


def armored_rib(station, kind):
    """Heavy armoured rib or forward fin, from the sill up (the bench passes beneath)."""
    width = STATION_WIDTH[kind]
    ivory = .80 if kind == 'fin' else .40
    for side in (-1, 1):
        q0, q1, q2 = side_pts([P0, P1, P2], side)
        outer = clip_start_z(inset_line([q0, q1, q2], [-.21, -.21]), LEDGE_TOP)
        inner = clip_start_z(inset_line([q0, q1, q2], [.21, .21]), LEDGE_TOP)
        prism(f'Armored rib core {station}-{side}', outer + list(reversed(inner)), width, station,
              'structural graphite', 'shell', .015, drop=[-inward3(q0, q1), -inward3(q1, q2), (0, 0, -1)])
        knee_top = at_z_on_line(inner[0], inner[1], 1.90)
        n_in = inward2(q0, q1)
        knee_top = (knee_top[0] - n_in[0] * .005, knee_top[1] - n_in[1] * .005)
        p_sh = (inner[0][0] - n_in[0] * .005, inner[0][1] - n_in[1] * .005)
        t1 = unit2(q0, q1)
        knee_foot = at_z_on_line(p_sh, (p_sh[0] + t1[0], p_sh[1] + t1[1]), LEDGE_TOP)
        prism(f'Armored rib knee wedge {station}-{side}', [(side * 4.262, LEDGE_TOP), knee_foot, knee_top],
              width - .03, station, 'structural graphite', 'shell', .008)
        n1 = inward3(q0, q1)
        u1 = up3(q0, q1)
        for k, (za, zb) in enumerate(PLATE_BANDS):
            seg_plate(f'Armored rib ivory plate {station}-{side}-{k}', q0, q1, za, zb, .21,
                      station - ivory / 2, station + ivory / 2, .06, 'warm ceramic armor', 'shell', .012)
            for sgn in (-1, 1):
                cheek_plate(f'Armored rib cheek plate {station}-{side}-{k}-{sgn}', q0, q1, za, zb, .11, .27,
                            station + sgn * width / 2, sgn * .012, 'warm ceramic armor', 'shell')
            for zz in (za + .04, zb - .04):
                for sgn in (-1, 1):
                    flush_bolt(f'Armored rib bolt {station}-{side}-{k}', mount(q0, q1, zz, .27, station + sgn * (ivory / 2 - .04)), n1)
        # Red band 2 mm proud of the plates, wrapping .08 onto the cheeks, with shadow pinstripes.
        seg_plate(f'Armored rib red band {station}-{side}', q0, q1, 2.36, 2.435, .21,
                  station - width / 2 - .012, station + width / 2 + .012, .062, 'muted red stripe', 'detail', .002)
        for sgn in (-1, 1):
            cheek_plate(f'Armored rib red wrap {station}-{side}-{sgn}', q0, q1, 2.362, 2.433, .13, .270,
                        station + sgn * width / 2, sgn * .014, 'muted red stripe', 'detail', .002)
        for za, zb in ((2.342, 2.354), (2.441, 2.453)):
            seg_plate(f'Armored rib pinstripe {station}-{side}', q0, q1, za, zb, .21,
                      station - width / 2, station + width / 2, .0605, 'shadow', 'detail', 0)
        # Lamp B sits in the middle of band 3 (3.06-3.56); at the plan's z 3.10 the
        # lens crossed the 3.02-3.06 seam and floated over the bare core.
        for z in (2.12, 3.31):
            lens_slot(f'Armored rib lamp {station}-{side}-{z}', mount(q0, q1, z, .27, station), n1, u1, .30, .024)
        # Ivory armour continues up the 49 degree segment (front and left views): two plates
        # with a 30 mm seam, starting clear of the band-3 plate at the knee.  They stop
        # at profile z 4.19 (about .29 m short of the core's top): higher, the -y cheek
        # of the aft rib meets the aft ceiling side fascia's end face (x 2.95-3.01) and
        # the two coplanar faces z-fight.
        n2 = inward3(q1, q2)
        upper = ((3.70, 3.94), (3.96, 4.19))
        # The forward fin's upper plates fill the top corners of the seated front view:
        # graphite-grey there (front view), ivory on the heavy ribs (left view).
        upper_mat = 'upper armor' if kind == 'fin' else 'warm ceramic armor'
        for k, (za, zb) in enumerate(upper):
            seg_plate(f'Armored rib upper ivory plate {station}-{side}-{k}', q1, q2, za, zb, .21,
                      station - ivory / 2, station + ivory / 2, .06, upper_mat, 'shell', .012)
            for sgn in (-1, 1):
                cheek_plate(f'Armored rib upper cheek plate {station}-{side}-{k}-{sgn}', q1, q2, za, zb, .11, .27,
                            station + sgn * width / 2, sgn * .012, upper_mat, 'shell')
        # .026 of profile height is the same .04 inset along this flatter segment.
        for zz in (upper[0][0] + .026, upper[1][1] - .026):
            for sgn in (-1, 1):
                flush_bolt(f'Armored rib upper bolt {station}-{side}', mount(q1, q2, zz, .27, station + sgn * (ivory / 2 - .04)), n2)
        lens_slot(f'Armored rib accent {station}-{side}', mount(q0, q1, 1.98, .19, station + width / 2 + .012),
                  (0, 1, 0), u1, .06, .06)


def slim_frame(station):
    """Slim frame from the sill over the roof to the other sill, one mesh (no coplanar joints)."""
    pts = [(-x, z) for x, z in (P0, P1, P2, P3)] + [P3, P2, P1, P0]
    pts = [(-4.66, 1.72), (-3.87, 3.62), (-2.99, 4.38), (-1.25, 4.58), (1.25, 4.58), (2.99, 4.38), (3.87, 3.62), (4.66, 1.72)]
    widths = [.16, .14, .13, .13, .13, .14, .16]
    left = clip_start_z(offset_polyline(pts, [w / 2 for w in widths]), LEDGE_TOP)
    right = clip_start_z(offset_polyline(pts, [-w / 2 for w in widths]), LEDGE_TOP)
    left = list(reversed(clip_start_z(list(reversed(left)), LEDGE_TOP)))
    right = list(reversed(clip_start_z(list(reversed(right)), LEDGE_TOP)))
    outward = [-inward3(a, b) for a, b in zip(pts, pts[1:])]
    prism(f'Slim canopy frame {station}', left + list(reversed(right)), .12, station, 'structural graphite', 'shell', .012,
          drop=outward)


def roof_member(station, kind):
    pts = [(-2.99, 4.38), (-1.25, 4.58), (1.25, 4.58), (2.99, 4.38)]
    prism(f'Roof member {station}', band_polygon(pts, [.15, .15, .15]), .17, station, 'structural graphite', 'shell', .012,
          drop=[-inward3(a, b) for a, b in zip(pts, pts[1:])])


def member_bottom(station, kind):
    width = .15 if kind in ('heavy', 'fin') else .13
    return 4.58 - width / 2


def longitudinal(name, point, normals, size, y0, y1, slope_to=None, strip=False):
    """Mullion along Y at a profile bend; cross-section faces the bisector of the two panes."""
    nb = (normals[0] + normals[1]).normalized()
    across, depth = size
    c = Vector((point[0], (y0 + y1) / 2, point[1]))
    oriented_box(name, c, (y1 - y0, across, depth), (0, 1, 0), nb, 'structural graphite', 'shell', .010, drop='back')
    if strip:
        oriented_box(name + ' hatch strip', c + nb * (depth / 2 - .0125 + .002), (y1 - y0 - .012, across - .006, .025),
                     (0, 1, 0), nb, 'hatch graphite', 'shell', .004, drop='back')
    if slope_to is not None:
        a = Vector((point[0], y1 - .05, point[1]))
        b = Vector(slope_to)
        d = (b - a)
        mid = (a + b) / 2
        f = (nb - d.normalized() * d.normalized().dot(nb)).normalized()
        oriented_box(name + ' forward slope', mid, (d.length, across - .004, depth), d, f, 'structural graphite', 'shell', .010,
                     drop='back')
        if strip:
            # Ends 9.5 cm short of the brow (hidden there) so no bevel face meets the slope's.
            oriented_box(name + ' forward slope hatch strip', mid - d.normalized() * .045 + f * (depth / 2 - .0125 + .002),
                         (d.length - .10, across - .010, .025), d, f, 'hatch graphite', 'shell', .004, drop='back')


def roof_eave(side):
    """Ivory eave in the roof facet plane (x 2.25-2.99), continuous from -2.91 to 4.75."""
    q2, q3 = side_pts([P2, P3], side)
    n = inward2(q2, q3)
    tx, tz = unit2(q2, q3)

    def at_x(x, off):
        t = (side * x - q2[0]) / (q3[0] - q2[0])
        return (q2[0] + t * (q3[0] - q2[0]) + n[0] * off, q2[1] + t * (q3[1] - q2[1]) + n[1] * off)
    poly = [at_x(2.98, -.035), at_x(2.25, -.035), at_x(2.25, .035), at_x(2.98, .035)]
    prism(f'Ivory roof eave {side}', poly, 4.74 + 2.91, (4.74 - 2.91) / 2, 'warm ceramic armor', 'shell', .010,
          drop=[-inward3(q2, q3)])
    stripe = [at_x(2.285, .033), at_x(2.255, .033), at_x(2.255, .037), at_x(2.285, .037)]
    prism(f'Eave red stripe {side}', stripe, 4.74 + 2.91 - .02, (4.74 - 2.91) / 2, 'muted red stripe', 'detail', 0)
    for st in CABIN_STATIONS:
        y = st - .40 if STATION_KIND[st] == 'fin' else st + .40
        p = at_x(2.42, .035)    # 2 cm outboard of the plan's 2.40 so the slot clears the red stripe
        lens_slot(f'Eave lamp {side}-{st}', (p[0], y, p[1]), (n[0], 0, n[1]), (tx, 0, tz), .22, .035)


def front_brow():
    right = BROW
    pts = right + [(-x, z) for x, z in reversed(right)]
    widths = [.20] * (len(pts) - 1)
    away = [(0, 1, 0)]
    for a, b in zip(pts, pts[1:]):
        nx, nz = inward2(a, b)
        # the brow's outer edge faces point away from the window opening
        away.append((-nx, 0, -nz))
    prism('Front brow', band_polygon(pts, widths), .18, FRONT, 'structural graphite', 'shell', .015, drop=away)
    prism('Front brow hatch strip', band_polygon(pts, [.12] * (len(pts) - 1)), .012, FRONT - .09 + .004,
          'hatch graphite', 'shell', .003, drop=[(0, 1, 0)])
    # Crossbar with a lower lip and .55 m fillets into the slanted brow segments.
    zbox('Brow crossbar', -3.30, 3.30, FRONT - .07, FRONT + .07, 4.54, 4.70, 'structural graphite', 'shell', .012, 2)
    zbox('Brow crossbar lip', -3.30, 3.30, FRONT - .088, FRONT + .088, 4.51, 4.54, 'structural graphite', 'shell', .006, 2)
    for side in (-1, 1):
        a, b = side_pts([(3.95, 3.75), (3.05, 4.95)], side)
        inner = inset_line([a, b], [.10])
        t = unit2(a, b)
        x0 = line_intersect(inner[0], t, (0, 4.51), (1, 0))
        n = inward2(a, b)
        shifted = (inner[0][0] + n[0] * .55, inner[0][1] + n[1] * .55)
        centre = line_intersect(shifted, t, (0, 4.51 - .55), (1, 0))
        t1 = (centre[0], 4.51)
        t2 = (centre[0] - n[0] * .55, centre[1] - n[1] * .55)
        a1 = math.atan2(t1[1] - centre[1], t1[0] - centre[0])
        a2 = math.atan2(t2[1] - centre[1], t2[0] - centre[0])
        arc = [(centre[0] + .55 * math.cos(a1 + (a2 - a1) * k / 6), centre[1] + .55 * math.sin(a1 + (a2 - a1) * k / 6)) for k in range(7)]
        prism(f'Brow crossbar fillet {side}', [x0] + arc, .16, FRONT, 'structural graphite', 'shell', .006)
        FILLETS[side] = arc
        box(f'Brow post {side}', (side * 2.30, FRONT, 4.91), (.10, .12, .42), 'structural graphite', 'shell', .010)


FILLETS = {}


def sill_and_walls():
    for side in (-1, 1):
        x0, x1 = sorted((side * 4.26, side * 4.70))
        zbox(f'Sill ledge {side}', x0, x1, -4.60, 6.00, 1.66, LEDGE_TOP, 'structural graphite', 'shell', .010, 2,
             drop=[(side, 0, 0)])
        xn = side * 4.27
        cuts = [-4.598 + k * (5.998 + 4.598) / 6 for k in range(7)]
        for k in range(6):
            zbox(f'Sill trim nosing {side}-{k}', xn - .0125, xn + .0125, cuts[k], cuts[k + 1], LEDGE_TOP + .002 - .025,
                 LEDGE_TOP + .002, 'trim', 'trim', .004, 1)
        prism(f'Sill chamfered fascia {side}', [(side * 4.262, 1.660), (side * 4.33, 1.660), (side * 4.33, 1.615)],
              10.596, .70, 'structural graphite', 'shell', .004, drop=[(0, 0, 1)])
        wx = sorted((side * 4.61, side * 4.71))
        zbox(f'Low side bulkhead {side}', wx[0], wx[1], REAR, 6.45, SLAB_TOP, 1.66, 'structural graphite', 'shell', .010, 2,
             drop=[(side, 0, 0), (0, 0, 1), (0, 0, -1)])
        zbox(f'Aft wall cap {side}', wx[0], wx[1], REAR, -4.60, 1.66, 1.72, 'structural graphite', 'shell', .004, 1,
             drop=[(side, 0, 0), (0, 0, -1)])


def front_hull():
    box('Front lower hull', (0, 6.56, .91), (8.94, .32, .91), 'warm ceramic armor', 'shell', .025)
    box('Front window sill', (0, 6.32, 1.39), (8.97, .58, .13), 'structural graphite', 'shell', .025, drop=[(0, 1, 0)])
    for x in (-3.6, -1.8, 0, 1.8, 3.6):
        box('Forward lower access panel', (x, 6.385, .91), (1.74, .025, .76), 'warm ceramic armor', 'shell', .012)
        box('Forward toe gap', (x, 6.355, .57), (1.62, .018, .03), 'shadow', 'detail', .004)
        box('Forward panel red seam', (x, 6.354, 1.19), (1.62, .018, .027), 'muted red stripe', 'detail', .002)
    COVERS.append((-4.47, 4.47, 6.40, 6.72))


def structure():
    for st in CABIN_STATIONS:
        kind = STATION_KIND[st]
        if kind == 'slim':
            slim_frame(st)
        else:
            armored_rib(st, kind)
            roof_member(st, kind)
        z = member_bottom(st, kind) - .005
        box(f'Canopy center connector {st}', (0, st, 4.58), (.32, .22, .14), 'structural graphite', 'shell', .02)
        lens_slot(f'Canopy node lamp {st}', (0, st, 4.505 if kind != 'slim' else 4.51), (0, 0, -1), (1, 0, 0), .17, .040)
        if kind == 'heavy':
            for side in (-1, 1):
                q2, q3 = side_pts([P2, P3], side)
                nb = (inward3(q2, q3) + Vector((0, 0, -1))).normalized()
                c = Vector((side * 1.25, 0, 4.58)) + nb * ROOF_MULLION[1] / 2
                for dy in (-.33, .33):
                    lens_slot(f'Roof junction lamp {st}-{side}-{dy}', (c.x, st + dy, c.z), nb, (0, 1, 0), .14, .035)
    lens_slot('Brow node lamp', (0, FRONT - .04, 5.20 - .10), (0, 0, -1), (1, 0, 0), .17, .040)
    for side in (-1, 1):
        q0, q1, q2, q3 = side_pts([P0, P1, P2, P3], side)
        n1, n2, n3 = inward3(q0, q1), inward3(q1, q2), inward3(q2, q3)
        longitudinal(f'Side transom {side}', q1, (n1, n2), TRANSOM, REAR + .45, 4.30)
        longitudinal(f'Shoulder mullion {side}', q2, (n2, n3), SHOULDER, REAR + .45, FIN,
                     slope_to=(side * 3.05, FRONT, 4.95), strip=True)
        longitudinal(f'Roof facet mullion {side}', q3, (n3, Vector((0, 0, -1))), ROOF_MULLION, -2.91, FIN,
                     slope_to=(side * 1.25, FRONT, 5.20))
        # Forward side transom from the fin to the brow (separates the forward main/upper panes).
        a = Vector((q1[0], FIN_SPAN[1], q1[1]))
        b = Vector((side * 3.95, FRONT - .09, 3.75))
        nb = (n1 + n2).normalized()
        d = b - a
        f = (nb - d.normalized() * d.normalized().dot(nb)).normalized()
        oriented_box(f'Forward side transom {side}', (a + b) / 2, (d.length, TRANSOM[0], TRANSOM[1]), d, f,
                     'structural graphite', 'shell', .010, drop='back')
        roof_eave(side)
    front_brow()
    sill_and_walls()
    front_hull()


# ---------------------------------------------------------------- glazing lips
def pane_corners_on(a, b, s0, s1, y0, y1):
    """Rectangle on segment a-b between along-segment distances s0..s1 from a, y0..y1."""
    tx, tz = unit2(a, b)
    p0 = (a[0] + tx * s0, a[1] + tz * s0)
    p1 = (a[0] + tx * s1, a[1] + tz * s1)
    return [(p0[0], y0, p0[1]), (p1[0], y0, p1[1]), (p1[0], y1, p1[1]), (p0[0], y1, p0[1])]


def seg_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def glazing():
    stations = list(CABIN_STATIONS)
    count = 0
    for side in (-1, 1):
        q0, q1, q2, q3 = side_pts([P0, P1, P2, P3], side)
        n1, n2, n3 = inward3(q0, q1), inward3(q1, q2), inward3(q2, q3)
        L1, L2, L3 = seg_len(q0, q1), seg_len(q1, q2), seg_len(q2, q3)
        s_sill = (LEDGE_TOP + .01 - q0[1]) / (q1[1] - q0[1]) * L1
        for i in range(len(stations) - 1):
            ya, yb = stations[i], stations[i + 1]
            ka, kb = STATION_KIND[ya], STATION_KIND[yb]
            y0, y1 = ya + SIDE_HALF[ka], yb - SIDE_HALF[kb]
            lip_ring(f'Pane seal ring main {side}-{i}', pane_corners_on(q0, q1, s_sill, L1 - TRANSOM[0] / 2, y0, y1), n1)
            lip_ring(f'Pane seal ring upper {side}-{i}', pane_corners_on(q1, q2, TRANSOM[0] / 2, L2 - SHOULDER[0] / 2, y0, y1), n2)
            r0, r1 = ya + ROOF_HALF[ka], yb - ROOF_HALF[kb]
            s_eave = (2.25 - 2.99) / (1.25 - 2.99) * L3
            lip_ring(f'Pane seal ring roof facet {side}-{i}', pane_corners_on(q2, q3, s_eave, L3 - ROOF_MULLION[0] / 2, r0, r1), n3)
            count += 3
        for k, (y0, y1) in enumerate(((-4.25 + .07, -2.91), (-5.60 + .07, -4.25 - .07))):
            lip_ring(f'Pane seal ring aft upper {side}-{k}', pane_corners_on(q1, q2, TRANSOM[0] / 2, L2 - SHOULDER[0] / 2, y0, y1), n2)
            count += 1
        # Forward bay (fin to brow): ruled panes between the cabin profile and the brow profile.
        ya, yb = FIN_SPAN[1] + .012, FRONT - .09
        bA, bB, bC, bD = side_pts([(4.66, 1.70), (3.95, 3.75), (3.05, 4.95), (1.25, 5.20)], side)

        def on(a, b, s, y):
            tx, tz = unit2(a, b)
            return (a[0] + tx * s, y, a[1] + tz * s)
        lb = seg_len(bA, bB)
        main = [on(q0, q1, s_sill, ya), on(q0, q1, L1 - TRANSOM[0] / 2, ya),
                on(bA, bB, lb - TRANSOM[0] / 2, yb), on(bA, bB, (LEDGE_TOP + .01 - bA[1]) / (bB[1] - bA[1]) * lb, yb)]
        lip_ring(f'Pane seal ring forward main {side}', main, n1)
        t = (ya - FIN) / (FRONT - FIN)
        sh = Vector((q2[0] + (side * 3.05 - q2[0]) * t, ya, q2[1] + (4.95 - q2[1]) * t))
        q1v = Vector((q1[0], ya, q1[1]))
        upper = [tuple(q1v + (sh - q1v).normalized() * (TRANSOM[0] / 2)), tuple(sh + (q1v - sh).normalized() * (SHOULDER[0] / 2)),
                 on(bB, bC, seg_len(bB, bC) - SHOULDER[0] / 2, yb), on(bB, bC, TRANSOM[0] / 2, yb)]
        lip_ring(f'Pane seal ring forward upper {side}', upper, n2)
        ya2 = FIN + ROOF_HALF['fin']
        t2 = (ya2 - FIN) / (FRONT - FIN)
        sh2 = Vector((q2[0] + (side * 3.05 - q2[0]) * t2, ya2, q2[1] + (4.95 - q2[1]) * t2))
        rm2 = Vector((side * 1.25, ya2, 4.58 + (5.20 - 4.58) * t2))
        rmf = Vector((side * 1.25, yb, 4.58 + (5.20 - 4.58) * (yb - FIN) / (FRONT - FIN)))
        shf = Vector((q2[0] + (side * 3.05 - q2[0]) * (yb - FIN) / (FRONT - FIN), yb,
                      q2[1] + (4.95 - q2[1]) * (yb - FIN) / (FRONT - FIN)))
        facet = [tuple(sh2 + (rm2 - sh2).normalized() * SHOULDER[0] / 2), tuple(rm2 + (sh2 - rm2).normalized() * ROOF_MULLION[0] / 2),
                 tuple(rmf + (shf - rmf).normalized() * ROOF_MULLION[0] / 2), tuple(shf + (rmf - shf).normalized() * SHOULDER[0] / 2)]
        lip_ring(f'Pane seal ring forward roof facet {side}', facet, n3)
        count += 3
        # Rear corner triangle above the truncated pressure bulkhead.
        tri = [Vector((side * 3.87, REAR + .04, 3.62)), Vector((side * 2.99, REAR + .04, 4.38)), Vector((side * 2.95, REAR + .04, 3.95))]
        cen = sum(tri, Vector()) / 3
        tri = [tuple(p + (cen - p).normalized() * .06) for p in tri]
        lip_ring(f'Pane seal ring rear corner {side}', tri, (0, 1, 0), radius=.03)
        count += 1
    for i in range(len(stations) - 1):
        ya, yb = stations[i], stations[i + 1]
        r0, r1 = ya + ROOF_HALF[STATION_KIND[ya]], yb - ROOF_HALF[STATION_KIND[yb]]
        x = 1.25 - ROOF_MULLION[0] / 2
        lip_ring(f'Pane seal ring roof centre {i}', [(-x, r0, 4.58), (x, r0, 4.58), (x, r1, 4.58), (-x, r1, 4.58)], (0, 0, -1))
        count += 1
    ya2, yb = FIN + ROOF_HALF['fin'], FRONT - .09
    z0 = 4.58 + (5.20 - 4.58) * (ya2 - FIN) / (FRONT - FIN)
    z1 = 4.58 + (5.20 - 4.58) * (yb - FIN) / (FRONT - FIN)
    x = 1.25 - ROOF_MULLION[0] / 2
    normal = Vector((0, z1 - z0, -(yb - ya2))).normalized()
    lip_ring('Pane seal ring forward roof centre', [(-x, ya2, z0), (x, ya2, z0), (x, yb, z1), (-x, yb, z1)], normal)
    count += 1
    # Front glazing in the brow plane: three brow panes and the centre pane under the crossbar.
    y = FRONT - .09 + .0
    count += front_lips(y)
    return count


def front_lips(y):
    def inner_pt(seg_a, seg_b, other_a, other_b):
        la = inset_line([seg_a, seg_b], [.10])
        lb = inset_line([other_a, other_b], [.10])
        return line_intersect(la[0], unit2(seg_a, seg_b), lb[0], unit2(other_a, other_b))

    def on_inner(a, b, *, z=None, x=None):
        l = inset_line([a, b], [.10])
        if z is not None:
            return line_intersect(l[0], unit2(a, b), (0, z), (1, 0))
        return line_intersect(l[0], unit2(a, b), (x, 0), (0, 1))
    A, B, C, D = (4.66, 1.70), (3.95, 3.75), (3.05, 4.95), (1.25, 5.20)
    flat = ((1.25, 5.20), (-1.25, 5.20))
    n = (0, -1, 0)
    # Order: bottom-right, up the right brow, fillet into the crossbar, across, mirrored down.
    rpath = [(4.56, 1.46), inner_pt((4.66, .45), A, A, B), inner_pt(A, B, B, C)] + list(reversed(FILLETS[1]))
    lpath = [(-x, z) for x, z in reversed(rpath)]
    poly = rpath + lpath
    lip_ring('Pane seal ring front centre', [(x, y, z) for x, z in poly], n)
    top = 4.70
    rb = [(2.35, top), on_inner(B, C, z=top), inner_pt(B, C, C, D), on_inner(C, D, x=2.35)]
    for side in (-1, 1):
        pts = [(side * x, z) for x, z in rb]
        lip_ring(f'Pane seal ring brow side {side}', [(x, y, z) for x, z in pts], n)
    cpts = [(-2.25, top), (2.25, top), on_inner(C, D, x=2.25), inner_pt(C, D, *flat),
            (-inner_pt(C, D, *flat)[0], inner_pt(C, D, *flat)[1]), (-on_inner(C, D, x=2.25)[0], on_inner(C, D, x=2.25)[1])]
    lip_ring('Pane seal ring brow centre', [(x, y, z) for x, z in cpts], n)
    return 4


# ---------------------------------------------------------------- aft bay
AFT_BAYS = ((-4.25, -2.91), (-5.60, -4.25), (REAR + .445, -5.60))
HATCH_Y = REAR + .27
FILL_FRONT = REAR + .30
BRACE_Y = REAR + .20


def closed_offset(points, d):
    """Offset a closed 2D polygon; positive d moves along each edge's left normal."""
    n = len(points)
    lines = []
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        tx, tz = unit2(a, b)
        lines.append(((a[0] - tz * d, a[1] + tx * d), (tx, tz)))
    return [line_intersect(lines[i - 1][0], lines[i - 1][1], lines[i][0], lines[i][1]) for i in range(n)]


def x_at(line_pts, z):
    for a, b in zip(line_pts, line_pts[1:]):
        if min(a[1], b[1]) - 1e-9 <= z <= max(a[1], b[1]) + 1e-9 and abs(b[1] - a[1]) > 1e-9:
            return a[0] + (z - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
    a, b = line_pts[-2], line_pts[-1]
    return a[0] + (z - a[1]) / (b[1] - a[1]) * (b[0] - a[0])


def band_between(left, right, za, zb):
    """Polygon between two polylines (x as a function of z) from za to zb, keeping bends."""
    zs = sorted({za, zb} | {p[1] for p in left + right if za < p[1] < zb})
    return [(x_at(right, z), z) for z in zs] + [(x_at(left, z), z) for z in reversed(zs)]


def aft_side_walls():
    for side in (-1, 1):
        q0, q1, q2 = side_pts([P0, P1, P2], side)
        n1, u1 = inward3(q0, q1), up3(q0, q1)
        wx = sorted((side * 4.61, side * 4.71))
        seg_plate(f'Aft slope wall backing {side}', q0, q1, 1.72, 3.62, -.04, REAR, -2.90, .08, 'structural graphite', 'shell', .010,
                  drop=[-n1])
        for b, (ya, yb) in enumerate(AFT_BAYS):
            a0 = ya + (.07 if b < 2 else 0.0) + .0
            b0 = yb - (0.0 if b == 0 else .07)
            px = sorted((side * 4.57, side * 4.61))
            zbox(f'Aft lower wall ivory plate {side}-{b}', px[0], px[1], a0 + .02, b0 - .02, .60, 1.62,
                 'warm ceramic armor', 'shell', .010, 2)
            mid = (a0 + b0) / 2
            for c, (ca, cb) in enumerate(((a0, mid - .0075), (mid + .0075, b0))):
                for k, (za, zb) in enumerate(PLATE_BANDS):
                    seg_plate(f'Aft slope ivory plate {side}-{b}-{c}-{k}', q0, q1, za, zb, .04, ca, cb, .04,
                              'warm ceramic armor', 'shell', .010, drop=[-n1])
        seg_plate(f'Aft red band {side}', q0, q1, 2.36, 2.435, .04, REAR + .445, -2.912, .042, 'muted red stripe', 'detail', .002,
                  drop=[-n1])
        for y in AFT_PILASTERS:
            seg_plate(f'Aft pilaster {side}-{y}', q0, q1, 1.72, 3.62, .04, y - .07, y + .07, .10, 'structural graphite', 'shell', .010,
                      drop=[-n1])
            px = sorted((side * 4.51, side * 4.61))
            zbox(f'Aft pilaster foot {side}-{y}', px[0], px[1], y - .068, y + .068, SLAB_TOP, 1.72, 'structural graphite', 'shell', .010, 2)
            seg_plate(f'Aft upper frame {side}-{y}', q1, q2, 3.62, 4.38, -.07, y - .068, y + .068, .14, 'structural graphite', 'shell', .010,
                      drop=[-inward3(q1, q2)])
        seg_plate(f'Aft upper band solid {side}', q1, q2, 3.625, 4.375, -.03, REAR, -5.60, .06, 'hatch graphite', 'shell', .006,
                  drop=[-inward3(q1, q2)])
        for y in (-3.58, -4.92):
            lens_slot(f'Aft wall lamp {side}-{y}', mount(q0, q1, 2.12, .08, y), n1, u1, .30, .024)


def aft_ceiling():
    cell_solid('Aft ceiling', (-2.95, 2.95, REAR + .04, -2.91), [(-2.2, 2.2, -5.75, -3.35)], 3.95, 4.10,
               'structural graphite', 'shell', .010, 2, cover=False, drop=[(0, 0, 1)])
    zbox('Aft ceiling front fascia', -2.96, 2.96, -2.96, -2.90, 3.94, 4.45, 'structural graphite', 'shell', .008, 2)
    for side in (-1, 1):
        xa, xb = sorted((side * 2.95, side * 3.01))
        zbox(f'Aft ceiling side fascia {side}', xa, xb, REAR + .04, -2.91, 3.95, 4.33, 'structural graphite', 'shell', .008, 2)
    zbox('Aft ceiling coffer panel', -2.21, 2.21, -5.76, -3.34, 4.07, 4.10, 'shadow', 'shell', drop=[(0, 0, 1)])
    for side in (-1, 1):
        xa, xb = sorted((side * 2.10, side * 2.22))
        zbox(f'Coffer lip beam long {side}', xa, xb, -5.77, -3.33, 3.92, 4.07, 'structural graphite', 'shell', .008, 2)
    for ya, yb in ((-5.77, -5.65), (-3.45, -3.33)):
        zbox('Coffer lip beam short', -2.10, 2.10, ya, yb, 3.92, 4.07, 'structural graphite', 'shell', .008, 2)
    for side in (-1, 1):
        lens_slot(f'Aft ceiling slit {side}', (side * 1.24, -5.90, 3.95), (0, 0, -1), (1, 0, 0), .35, .030)
    # The roof over the enclosed bay is solid; it closes the gap above the ceiling fascia.
    roof = [(-2.97, 4.383), (-1.25, 4.58), (1.25, 4.58), (2.97, 4.383)]
    outer = offset_polyline(roof, [.06] * 3)
    outer2 = offset_polyline(roof, [.11] * 3)
    prism('Aft roof closure', outer + list(reversed(outer2)), .68, -2.96, 'structural graphite', 'shell', .006,
          drop=[(0, 0, 1), (.1142, 0, .9934), (-.1142, 0, .9934)])


def rear_wall():
    prism('Rear pressure bulkhead', [(-4.7, .45), (4.7, .45), (4.7, 1.7), (3.87, 3.62), (2.95, 3.95),
                                     (-2.95, 3.95), (-3.87, 3.62), (-4.7, 1.7)], .16, REAR - .04,
          'structural graphite', 'shell', .010)
    for side in (-1, 1):
        wall = side_pts([(4.66, .45), (4.66, 1.72), (3.87, 3.62), (2.95, 3.95)], side)
        a = inset_line(wall, [0, 0, 0])
        b = inset_line(wall, [.30, .30, .30])
        prism(f'Rear rib 0 {side}', a + list(reversed(b)), .45, REAR + .22, 'structural graphite', 'shell', .015,
              drop=[(side, 0, 0)] + [-inward3(p, q) for p, q in zip(wall, wall[1:])])
    box('Rear transverse beam', (0, REAR + .25, 3.72), (7.5, .45, .38), 'structural graphite', 'shell', .015,
        drop=[(0, 0, 1), (0, -1, 0)])
    box('Rear transverse beam step', (0, REAR + .25, 3.47), (7.0, .30, .12), 'structural graphite', 'shell', .010)
    for side in (-1, 1):
        inner = side_pts([(1.68, .45), (1.68, 1.50), (2.15, 3.47)], side)
        outer = side_pts([(3.05, .45), (3.05, 1.50), (3.45, 3.40)], side)
        for name, pts in (('inner', inner), ('outer', outer)):
            prism(f'Rear brace {name} {side}', band_polygon(pts, [.26, .26]), .24, BRACE_Y, 'structural graphite', 'shell', .012)
        # Ivory fills between the braces and outside the outer brace.
        sgn = side
        in_edge = offset_polyline(inner, [-sgn * .1375] * 2)
        out_l = offset_polyline(outer, [sgn * .1375] * 2)
        out_r = offset_polyline(outer, [-sgn * .1375] * 2)
        wall28 = inset_line(side_pts([(4.66, .45), (4.66, 1.72), (3.87, 3.62)], side), [.28, .28])
        for region, (left, right) in (('mid', (in_edge, out_l)), ('outer', (out_r, wall28))):
            for k, (za, zb) in enumerate(((.51, 1.47), (1.53, 2.35), (2.41, 3.40))):
                poly = band_between(left, right, za, zb)
                if abs(polygon_signed_area(poly)) < .01:
                    continue
                prism(f'Rear ivory fill {region} {side}-{k}', poly, .12, FILL_FRONT - .06, 'warm ceramic armor', 'shell', .010)
            xa, xb = sorted((x_at(left, 2.38), x_at(right, 2.38)))
            zbox(f'Rear red trim {region} {side}', xa + .01, xb - .01, FILL_FRONT - .011, FILL_FRONT + .002,
                 2.3525, 2.4075, 'muted red stripe', 'detail', .002, 1)
        # Kick lights low on the fills; a sconce on each inner brace.
        for x in (2.36, 3.90):
            lens_slot(f'Rear kick lamp {side}-{x}', (side * x, FILL_FRONT, .66), (0, 1, 0), (0, 0, 1), .10, .06)
        box(f'Rear sconce bezel {side}', (side * 1.68, BRACE_Y + .12 + .025, 1.30), (.10, .07, .10), 'shadow', 'detail', .008)
        lens_slot(f'Rear sconce {side}', (side * 1.68, BRACE_Y + .12 + .06, 1.30), (0, 1, 0), (1, 0, 0), .05, .05)


def hatch():
    O = [(-1.42, .45), (-1.42, 2.95), (-1.10, 3.27), (1.10, 3.27), (1.42, 2.95), (1.42, .45)]
    I = offset_polyline(O, [-.26] * 5)
    for i in range(5):
        poly = [O[i], O[i + 1], I[i + 1], I[i]]
        if i == 0:
            poly = [(-1.56, .45), (-1.42, .75), O[1], I[1], I[0]]
        if i == 4:
            poly = [O[4], (1.42, .75), (1.56, .45), I[5], I[4]]
        prism(f'Hatch ivory frame {i}', poly, .30, HATCH_Y, 'warm ceramic armor', 'shell', .012)
    surround_out = offset_polyline(O, [.12] * 5)
    prism('Hatch graphite surround', surround_out + list(reversed(O)), .19, HATCH_Y + .15 - .05 - .095,
          'structural graphite', 'shell', .008)
    leaf_front = REAR + .15
    for sgn in (-1, 1):
        xa, xb = sorted((sgn * .006, sgn * 1.20))
        zbox(f'Hatch door leaf {sgn}', xa, xb, leaf_front - .04, leaf_front, .47, 3.03, 'door graphite', 'detail', .006, 2)
        outline = [(sgn * .18, .62), (sgn * 1.06, .62), (sgn * 1.06, 2.78), (sgn * .91, 2.93), (sgn * .18, 2.93)]
        if sgn < 0:
            outline = list(reversed(outline))
        if polygon_signed_area(outline) < 0:
            outline = list(reversed(outline))
        o = closed_offset(outline, -.05)
        i_ = closed_offset(outline, .05)
        for k in range(len(outline)):
            j = (k + 1) % len(outline)
            pts = [(o[k][0], leaf_front, o[k][1]), (o[j][0], leaf_front, o[j][1]),
                   (i_[j][0], leaf_front, i_[j][1]), (i_[k][0], leaf_front, i_[k][1])]
            extrude(f'Hatch leaf raised border {sgn}-{k}', pts, (0, .012, 0), 'door graphite', 'detail', .004, 1)
        box(f'Hatch handle {sgn}', (sgn * .09, leaf_front + .012, 1.85), (.022, .03, 1.0), 'fastener', 'detail', .006)
    # On the -x jamb: that is the right-hand jamb looking aft, as designed.
    lens_slot('Hatch status lamp', (-1.29, HATCH_Y + .15, 1.95), (0, 1, 0), (0, 0, 1), .30, .030)


def aft_bay():
    aft_side_walls()
    aft_ceiling()
    rear_wall()
    hatch()


# ---------------------------------------------------------------- seating and furniture
BENCH_X = 4.08
FOUNDATION = (.55, .95)
WARM = (1.0, .46, .15)


def bench_unit(name, side, y0, y1, seats, foot_ys, foot_watts, pillows):
    """Shadow plinth, ivory foundation, tray, crease cushions, foot-lights and a blue toe strip."""
    x = side * BENCH_X
    length = y1 - y0
    cy = (y0 + y1) / 2
    box(f'{name} shadow plinth', (x, cy, .615), (1.10, length - .04, .32), 'shadow', 'seating', .02)
    box(f'{name} ivory foundation', (x, cy, sum(FOUNDATION) / 2), (1.17, length, FOUNDATION[1] - FOUNDATION[0]),
        'bench ivory', 'seating', .02, 2)
    box(f'{name} dark seat tray', (x, cy, 1.005), (1.19, length + .02, .11), 'structural graphite', 'seating', .02, 2)
    # The slab is cut only under the plinth; the foundation overhang (toe kick) keeps slab under it.
    COVERS.append((x - .55, x + .55, y0 + .02, y1 - .02))
    for i, (yc, sl) in enumerate(seats):
        cushion(f'{name} seat cushion {i}', (side * 3.98, yc, 1.15), (.98, sl, .18), 'navy upholstery')
        cushion(f'{name} back cushion {i}', (side * 4.43, yc, 1.37), (.22, sl, .58), 'navy upholstery',
                rotation=(0, side * math.radians(8), 0))
    face = side * (BENCH_X - .585)
    for y in foot_ys:
        box(f'{name} foot-light bezel {y}', (face + side * .03, y, .77), (.08, .40, .07), 'shadow', 'detail', .028, 3)
        c = (face - side * .01, y, .77)
        lens_slot(f'{name} foot-light {y}', c, (-side, 0, 0), (0, 1, 0), .30, .024)
        POOLS.append({'type': 'foot', 'name': f'{name} foot-light pool {y}', 'c': Vector(c), 'side': side, 'watts': foot_watts})
    blue_strip(f'{name} blue toe strip', (face, cy, .587), (-side, 0, 0), (0, 1, 0), length - .10, .020)
    BLUES[-1]['kind'] = 'toe'
    for k, (mat, y, row) in enumerate(pillows):
        big = mat == 'grey pillow'
        size = (.50, .50, .16) if big else (.46, .46, .15)
        if row == 'back':
            c, lean = (side * 4.13, y, 1.47), 20
        else:
            c, lean = (side * 3.98, y, 1.45), 14
        pillow(f'{name} pillow {k}', c, size, (6 if k % 2 else -6), lean, mat, side=side)


def benches():
    main_seats = [(-2.52 + .76 * i, .72) for i in range(6)]
    pillows = {
        -1: [('grey pillow', -2.50, 'back'), ('navy pillow', -2.66, 'front'), ('oxblood cushion', -2.28, 'front'),
             ('navy pillow', -.62, 'back'), ('grey pillow', 1.25, 'back'), ('navy pillow', 1.05, 'front'),
             ('oxblood cushion', 1.42, 'front')],
        1: [('grey pillow', 1.25, 'back'), ('navy pillow', 1.05, 'front'), ('navy pillow', .40, 'back'),
            ('oxblood cushion', -.62, 'back'), ('navy pillow', -1.65, 'back'), ('grey pillow', -2.50, 'back'),
            ('navy pillow', -2.30, 'front')],
    }
    for side in (-1, 1):
        bench_unit(f'Main bench {side}', side, -2.90, 1.65, main_seats, (-1.86, .61), 24.0, pillows[side])
        bench_unit(f'Rear sofa {side}', side, -4.40, -3.30, [(-4.125, .53), (-3.575, .53)], (-3.85,), 12.0,
                   [('grey pillow', -3.85, 'back')])
        bench_unit(f'Forward sofa {side}', side, 3.35, 4.40, [(3.6075, .505), (4.1425, .505)], (3.875,), 12.0,
                   [('grey pillow', 3.90, 'back'), ('navy pillow', 3.70, 'front'), ('oxblood cushion', 4.10, 'front')])


def drum_table(name, x, y, height, lens=True, radius=.17, grooves=6, slit=False, cup='fastener matte'):
    """Drum with 1.5 mm 'shadow' grooves, a room-facing lens and a tumbler on top.

    slit=True gives the low side-table look: a wider, shorter drum with two trim
    grooves, a horizontal amber slit on a flat bezel near the top and a steel cup.
    """
    z0, z1 = PLATE_TOP, PLATE_TOP + height
    r, ri = radius, radius - .0015
    profile, index = [(r, z0)], []
    for k in range(grooves):
        zc = z0 + height * (k + 1) / (grooves + 1)
        for p in ((r, zc - .006), (ri, zc - .006), (ri, zc + .006), (r, zc + .006)):
            profile.append(p)
    profile.append((r, z1))
    for i in range(len(profile) - 1):
        a, b = profile[i], profile[i + 1]
        groove = (a[0] < r - 1e-4 or b[0] < r - 1e-4)
        index.append(1 if groove else 0)
    index.append(0)
    lathe(f'{name} drum', profile, (x, y), ['structural graphite', 'shadow'], index, 'detail', 24)
    if lens:
        f = Vector((-x, -y, 0)).normalized()
        if slit:
            # A flat bezel 4 mm proud of the drum carries the slot, so the straight lens never
            # floats off the curved wall (the .17 m bezel's sagitta is 16-20 mm; it reaches 26 mm deep).
            zl = z0 + height * .74
            surface = Vector((x, y, zl)) + f * r
            along = Vector((0, 0, 1)).cross(f).normalized()
            oriented_box(f'{name} lamp bezel', surface + f * -.011, (.17, .05, .030), along, f, 'shadow', 'detail', .002)
            lens_slot(f'{name} lamp', surface + f * .004, f, along, .11, .022)
        else:
            c = Vector((x, y, z0 + height * .5)) + f * r
            lens_slot(f'{name} lamp', c, f, (0, 0, 1), .16, .030)
    lathe(f'{name} tumbler', [(.035, z1), (.035, z1 + .11)], (x + .05, y, ), [cup], [0, 0], 'detail', 12)


def side_console(side):
    x0, x1 = sorted((side * 3.98, side * 4.66))
    y0, y1 = 1.85, 3.20
    px = sorted((side * 4.04, side * 4.66))
    zbox(f'Side console plinth {side}', px[0], px[1], y0, y1, SLAB_TOP, .53, 'shadow', 'detail', cover=True)
    for y in (2.20, 2.85):
        lens_slot(f'Side console toe lamp {side}-{y}', (side * 4.04, y, .49), (-side, 0, 0), (0, 1, 0), .04, .04)
    zbox(f'Side console carcass {side}', x0, x1, y0, y1, .53, 1.42, 'structural graphite', 'detail', .010, 2)
    face = side * 3.98
    for k, (a, b, mat) in enumerate(((1.87, 2.519, 'hatch graphite'), (2.531, 3.18, 'warm ceramic armor'))):
        dx = sorted((face, face - side * .01))
        zbox(f'Side console door {side}-{k}', dx[0], dx[1], a, b, .56, 1.39, mat, 'detail', .004, 1)
        lens_slot(f'Side console door lamp {side}-{k}', (face - side * .01, (a + b) / 2, 1.05), (-side, 0, 0), (0, 0, 1), .16, .024)
    top_in = side * (3.98 + .24 * math.tan(math.radians(30)))
    prism(f'Side console fascia {side}', [(face, 1.42), (side * 4.66, 1.42), (side * 4.66, 1.66), (top_in, 1.66)],
          y1 - y0, (y0 + y1) / 2, 'structural graphite', 'detail', .008, drop=[(0, 0, 1)])
    n = Vector((-side * math.cos(math.radians(30)), 0, math.sin(math.radians(30))))
    mid = Vector(((face + top_in) / 2, 2.52, 1.54))
    oriented_box(f'Side console fascia bezel {side}', mid + n * .004, (.36, .06, .008), (0, 1, 0), n, 'shadow', 'detail', 0)
    lens_slot(f'Side console fascia lamp {side}', mid + n * .008, n, (0, 1, 0), .26, .030)
    for k in range(4):
        oriented_box(f'Side console inactive key {side}-{k}', mid + Vector((0, .40 + k * .07, 0)) + n * .005,
                     (.05, .022, .010), (0, 1, 0), n, 'fastener', 'detail', .002)


def corner_console(side):
    x0, x1 = sorted((side * 2.65, side * 4.30))
    zbox(f'Corner console plinth {side}', x0, x1, 5.66, 6.02, SLAB_TOP, .53, 'shadow', 'detail', cover=True)
    zbox(f'Corner console carcass {side}', x0, x1, 5.60, 6.02, .53, 1.42, 'structural graphite', 'detail', .010, 2)
    y_top = 5.60 + .24 * math.tan(math.radians(30))
    pts = [(x0, 5.60, 1.42), (x0, 6.02, 1.42), (x0, 6.02, 1.66), (x0, y_top, 1.66)]
    extrude(f'Corner console fascia {side}', pts, (x1 - x0, 0, 0), 'structural graphite', 'detail', .008)
    # Final look pass: door panels like side_console's (bench ivory, alternating with a graphite
    # door) proud of the graphite carcass, and a recessed dark bezel strip above them, so the
    # cabinets flanking the screen read as lit ivory cabinets instead of black boxes.
    for k, (a, b) in enumerate(((2.68, 3.200), (3.212, 3.738), (3.750, 4.270))):
        xa, xb = sorted((side * a, side * b))
        zbox(f'Corner console door {side}-{k}', xa, xb, 5.59, 5.60, .56, 1.33,
             'hatch graphite' if k == 1 else 'bench ivory', 'detail', .004, 1)
    zbox(f'Corner console bezel strip {side}', x0 + .03, x1 - .03, 5.598, 5.60, 1.345, 1.395, 'shadow', 'detail')
    POOLS.append({'type': 'console_toe', 'name': f'Corner console toe wash {side}', 'side': side})
    n = Vector((0, -math.cos(math.radians(30)), math.sin(math.radians(30))))
    for x in (3.05, 3.85):
        c = Vector((side * x, (5.60 + y_top) / 2, 1.54))
        oriented_box(f'Corner console bezel {side}-{x}', c + n * .004, (.36, .06, .008), (1, 0, 0), n, 'shadow', 'detail', 0)
        lens_slot(f'Corner console lamp {side}-{x}', c + n * .008, n, (1, 0, 0), .26, .030)
    POOLS.append({'type': 'sill', 'name': f'Screen-side sill spill {side}', 'side': side})


def aft_cabinet(side):
    x, y = side * 3.75, -4.80
    box(f'Aft cabinet {side}', (x, y, PLATE_TOP + .275), (.40, .40, .55), 'structural graphite', 'detail', .010)
    box(f'Aft cabinet ivory band {side}', (x, y, PLATE_TOP + .515), (.41, .41, .08), 'warm ceramic armor', 'detail', .006)
    lens_slot(f'Aft cabinet lamp {side}', (x - side * .20, y, .80), (-side, 0, 0), (0, 1, 0), .12, .030)
    COVERS.append((x - .20, x + .20, y - .20, y + .20))


def viewer_sofa():
    box('Viewer sofa base', (0, -.22, .62), (1.86, .80, .34), 'hatch graphite', 'viewer', .02)
    COVERS.append((-.93, .93, -.62, .18))
    for x in (-.60, 0, .60):
        cushion(f'Viewer seat cushion {x}', (x, -.14, .86), (.58, .64, .14), 'navy upholstery', 'viewer')
        cushion(f'Viewer back cushion {x}', (x, -.52, 1.17), (.58, .20, .50), 'navy upholstery', 'viewer',
                rotation=(math.radians(12), 0, 0))
        line(f'Viewer seat piping {x}', rounded_rectangle(x, -.14, .925, .54, .60, .06), .004, 'fabric piping', 'viewer', True, 1)
    box('Viewer sofa back shell', (0, -.66, 1.04), (1.90, .10, .62), 'hatch graphite', 'viewer', .02)
    for side in (-1, 1):
        box(f'Viewer armrest {side}', (side * 1.01, -.22, 1.03), (.16, .80, .22), 'navy upholstery', 'viewer', .05, 3)
        box(f'Viewer armrest cap {side}', (side * 1.01, -.22, 1.15), (.16, .80, .02), 'structural graphite', 'viewer', .006, 1)


def seating():
    benches()
    for side in (-1, 1):
        drum_table(f'Tumbler table {side}', side * 3.30, 4.62, .46, radius=.22, grooves=2, slit=True, cup='polished steel')
        drum_table(f'Side table {side}', side * 3.72, -3.10, .48, radius=.18, grooves=2, slit=True, cup='polished steel')
        side_console(side)
        corner_console(side)
        aft_cabinet(side)
    viewer_sofa()


# ---------------------------------------------------------------- build entry points
LIGHTS = []
BLEND_PATH = None


def build_interior():
    """Create authored meshes; return them without modifying caller's scene state."""
    for store in (OBJECTS, LAMPS, BLUES, POOLS, COVERS, WIDENED):
        store.clear()
    MATS.clear()
    FILLETS.clear()
    build_materials()
    deck()
    structure()
    glazing()
    aft_bay()
    seating()
    deck_slab()
    deck_underlay()
    bpy.context.view_layer.update()
    return list(OBJECTS)


def build_lights():
    """Bake-only lights: per-lamp amber rects, practical pools, blue guide rects, a faint fill.

    The Earth itself lights the cabin through build_runtime.py's proxy world.
    """
    LIGHTS.clear()
    fill = area_rect('Faint canopy fill', (0, 0, 6.8), (0, 0, -1), (1, 0, 0), 8.0, 9.0, 12.0, (.46, .58, 1), 180, 'fill')
    fill.visible_glossy = False
    LIGHTS.append(fill)
    # Earthshine: two broad, cool, glossy-invisible panels on the cabin axis facing each wall.
    # The Earth sits below the windows, so the proxy world barely reaches the armour (it faces
    # inward and slightly down); these stand in for earthlight bounced off the far glazing.
    for side in (-1, 1):
        shine = area_rect(f'Earthshine panel {side}', (-side * .05, 1.75, 2.9), (side, 0, 0), (0, 1, 0), 8.5, 1.8,
                          10.0, (.55, .68, 1.0), 180, 'earth')
        shine.visible_glossy = False
        LIGHTS.append(shine)
    amber = (1.0, .42, .12)
    for lamp in LAMPS:
        # Aft-bay lenses light their own walls (behind the rear shield): they follow lamp_gain
        # as practicals; cabin lenses are small accents whose spill follows lens_gain.
        aft = lamp['name'].startswith(('Aft ', 'Rear ', 'Hatch '))
        LIGHTS.append(area_rect(lamp['name'] + ' light', lamp['c'] + lamp['f'] * .03, lamp['f'], lamp['a'],
                                lamp['L'], .03, max(.4, 6.0 * lamp['L']), amber, 150, 'practical' if aft else 'amber'))
    for pool in POOLS:
        if pool['type'] == 'foot':
            side = pool['side']
            f = Vector((-side, 0, -1)).normalized()
            c = pool['c'] + Vector((-side * .05, 0, 0))
            LIGHTS.append(area_rect(pool['name'], c, f, (0, 1, 0), .30, .05, pool['watts'], WARM, 120, 'practical'))
        elif pool['type'] == 'console_toe':
            # A low warm wash from the deck in front of each corner console up its door face
            # (glossy-invisible, so it never shows in the deck mirror).
            side = pool['side']
            rect = area_rect(pool['name'], Vector((side * 3.47, 5.28, .52)), Vector((0, .80, .60)).normalized(), (1, 0, 0),
                             1.40, .05, 2.0, (1.0, .72, .45), 120, 'practical')
            rect.visible_glossy = False
            LIGHTS.append(rect)
        elif pool['type'] == 'sill':
            side = pool['side']
            # 22 cm in front of the corner console and aimed out over the deck with a
            # 120 degree spread, so the console face stays outside the cone (at y 5.55
            # it burned a wedge between the console lamps).
            c = Vector((side * 3.45, 5.38, 1.72))
            f = Vector((-side * .20, -.80, -.57)).normalized()
            LIGHTS.append(area_rect(pool['name'], c, f, (1, 0, 0), .20, .20, 9.0, (1, .5, .18), 120, 'practical'))
    for side in (-1, 1):
        for x in (2.36, 3.90):
            c = Vector((side * x, REAR + .32, .64))
            f = (Vector((side * x, REAR + 1.4, .45)) - c).normalized()
            LIGHTS.append(area_rect(f'Rear kick pool {side}-{x}', c, f, (1, 0, 0), .10, .06, 6.0, (1, .5, .18), 140, 'practical'))
            # The 1.2 W 'Rear kick glow' points 12 cm above each lens burned a hot spot into the
            # ivory fill (final look pass: removed; the kick pools light the deck).
        # A dim cool-neutral fill from each aft coffer onto the side walls: with the rear shield the
        # aft bay was lit by warm practicals only and read as a beige corridor.
        aft = area_rect(f'Aft coffer fill {side}', (side * 1.55, -4.55, 3.90), (side * .85, 0, -.53), (0, 1, 0), 2.0, .30, 3.0,
                        (.80, .88, 1.0), 120, 'aft_fill')
        aft.visible_glossy = False
        LIGHTS.append(aft)
        LIGHTS.append(spot_light(f'Aft ceiling slit spot {side}', (side * 1.24, -5.90, 3.92), (0, 0, -1), 8.0, (1, .5, .18), 70, .8))
        LIGHTS.append(point_light(f'Rear sconce glow {side}', (side * 1.68, BRACE_Y + .12 + .06 + .08, 1.30), 1.0, (1, .5, .18)))
    # A dim cool wash from the coffer onto the aft deck centre and the hatch threshold (the design's
    # floor reads about 38 luma there; the warm practicals left it near 13).
    wash = area_rect('Aft deck wash', (0, -4.55, 3.90), (0, 0, -1), (1, 0, 0), 2.4, 1.6, 3.0, (.80, .88, 1.0), 120, 'aft_fill')
    wash.visible_glossy = False
    LIGHTS.append(wash)
    LIGHTS.append(point_light('Hatch status glow', (-1.29, HATCH_Y + .15 + .05, 1.95), .6, (1, .5, .18)))
    # A soft, neutral-cool wash from the hatch header down the door leaves (the design reads the
    # graphite door at about 14 luma; the warm practicals alone left it near black).
    wash = area_rect('Hatch door wash', (0, REAR + .15 + .32, 2.98), (0, -.30, -1), (1, 0, 0), 2.0, .12, 1.5,
                     (.80, .88, 1.0), 120, 'practical')
    wash.visible_glossy = False
    LIGHTS.append(wash)
    blue = (.04, .28, 1.0)
    for strip in BLUES:
        f = strip['f']
        if strip.get('kind') == 'toe':
            aim = (f + Vector((0, 0, -.6))).normalized()
            LIGHTS.append(area_rect(strip['name'] + ' light', strip['c'] + f * .01, aim, strip['a'], strip['L'], .03,
                                    1.1 * strip['L'], blue, 150, 'blue'))
        else:
            aim = (f + Vector((0, 0, 1))).normalized()
            LIGHTS.append(area_rect(strip['name'] + ' light', strip['c'] + f * .01 + Vector((0, 0, .02)), aim, strip['a'],
                                    strip['L'], .03, 1.2 * strip['L'], blue, 150, 'blue'))
    return list(LIGHTS)


def summary():
    deps = bpy.context.evaluated_depsgraph_get()
    groups, glows = {}, {'amber': 0, 'blue': 0}
    min_area, min_name = float('inf'), None
    for obj in OBJECTS:
        if obj.name not in bpy.data.objects:
            continue
        mesh = obj.evaluated_get(deps).data
        mesh.calc_loop_triangles()
        groups[obj['bake_group']] = groups.get(obj['bake_group'], 0) + len(mesh.loop_triangles)
        for tri in mesh.loop_triangles:
            if tri.area < min_area:
                min_area, min_name = tri.area, obj.name
        if obj.get('glow'):
            glows[str(obj['glow'])] = glows.get(str(obj['glow']), 0) + 1
    return {'groups': groups, 'triangles': sum(groups.values()), 'glows': glows, 'min_face_area_m2': min_area,
            'min_face_object': min_name, 'lights': len(LIGHTS), 'meshes': len(OBJECTS), 'widened_lenses': len(WIDENED),
            'blend': BLEND_PATH}


if __name__ == '__main__':
    import argparse
    import json
    import sys
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Direct CLI builds start empty; imported build_interior() never resets a scene.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    meshes = build_interior()
    lights = build_lights()
    BLEND_PATH = str(out)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    info = summary()
    if WIDENED:
        print('SHIP_WIDENED ' + json.dumps(WIDENED))
    print(json.dumps(info))
    if info['min_face_area_m2'] < 1e-9:
        print('SHIP_MIN_FACE_AREA_FAIL', info['min_face_object'], info['min_face_area_m2'])
        sys.exit(1)
