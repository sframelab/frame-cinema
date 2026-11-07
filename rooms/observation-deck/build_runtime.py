"""Build and bake the Observation Deck with Blender, then export indexed geometry.

Run with Blender --background --python this-file -- --output <workspace-folder>.
The source .blend remains editable; runtime geometry uses Cinema's ROCK format.

v4 pipeline (2026-11-02; the v5 look pass keeps it):
- an art-directed numpy Earth-proxy world that matches the runtime sky geometry,
  with self-tests before baking (SHIP_WORLD_OK);
- an optional camera-invisible rear-bay light shield (--no-rear-shield);
- world-space join, hidden-face cull, quad-follow strips and packed atlases;
- per-group lighting/albedo resolutions, ACTIVE_CAMERA gloss except the deck;
- glows.json (lamp halo manifest), a prefiltered deck mirror map and a wear map;
- --relight-from <dir>: re-bake lighting and the mirror only.
Knobs come from bake-params.json when present; CLI flags override them.
"""
from pathlib import Path
import argparse, hashlib, importlib.util, json, math, re, shutil, struct, sys, time
import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REVISION = '2026-11-02-v7'
FLOOR = 0.45
EYE_B = (0.0, 0.0, 1.65)

# Shared vision constants (Godot room space G; Blender B = (gx, -gz, gy)).
PLANET_DIRECTION = [-0.3954, -0.8290, -0.3954]
PLANET_G = np.array(PLANET_DIRECTION)
PLANET_G = PLANET_G / np.linalg.norm(PLANET_G)
PLANET_DISTANCE = 1.031
EARTH_RADIUS_DEG = 75.9
SUN_DIRECTION = [-0.6725, 0.3090, -0.6725]
SUN_G = np.array(SUN_DIRECTION)
SUN_G = SUN_G / np.linalg.norm(SUN_G)
# Shared with space.gdshader: the twilight band fades out between 5 and 9 deg inside the limb.
TWILIGHT_FADE_DEG = (5.0, 9.0)
EARTH_DIR_B = np.array([PLANET_G[0], -PLANET_G[2], PLANET_G[1]])

LIGHT_RES = {'deck': 4096, 'shell': 4096, 'detail': 2048, 'seating': 2048, 'viewer': 2048, 'trim': 1024, 'emission': 1024}
ALBEDO_RES = {'deck': 2048, 'shell': 2048, 'detail': 2048, 'seating': 1024, 'viewer': 1024, 'trim': 512, 'emission': 1024}
ALBEDO_SAMPLES = 16

MIRROR_EYE_B = (0.0, 0.0, -0.69)
MIRROR_W, MIRROR_H, MIRROR_PAD = 2048, 546, 32
MIRROR_LAT_MIN, MIRROR_LAT_MAX = -6.0, 90.0
MIRROR_SAMPLES = 256
WEAR_SIZE, WEAR_SEED = 512, 20261102

# blue_emit_gain < 0 means "follow blue_gain" (the v5 behaviour: one knob for the blue lights and
# the diode emission). group_gains: per-part light multipliers applied only while that part's
# lighting map bakes, [{"group": "deck", "kind": "amber", "name": "foot-light pool", "gain": .5}, ...]
# (kind and name are optional filters; name is a substring of the light's name). They act like
# Cycles light linking, which the bake does not need: the deck can take less of the warm lamp
# spill than the walls, the cushions less amber than the armour.
DEFAULT_PARAMS = {'k_night': .30, 'k_tw': 3.0, 'k_limb': 1.5, 'cam_gain': .25,
                  'lamp_gain': 1.0, 'lens_gain': 1.0, 'lens_emit_gain': 1.0, 'blue_gain': 1.0, 'fill_gain': 1.0, 'shine_gain': 1.0,
                  'aft_fill_gain': 1.0, 'blue_emit_gain': -1.0, 'group_gains': [], 'rear_shield': True}
GAIN_KEYS = ('k_night', 'k_tw', 'k_limb', 'cam_gain', 'lamp_gain', 'lens_gain', 'lens_emit_gain', 'blue_gain', 'fill_gain', 'shine_gain',
             'aft_fill_gain', 'blue_emit_gain')
# Deck mirror prefilter (bake-params.json "mirror" block overrides). The raw render is split
# into an environment layer and an emitter-only layer (lenses and diodes, rendered with every
# other mesh as a holdout). The environment is blurred like a satin plate; amber emitters get a
# glossy lobe in direction space (elevation sigma along, el*k_az*tan(lat) of azimuth across:
# thin vertical streaks at grazing, round blobs overhead); blue strips stay thin lines.
MIRROR_DEFAULTS = {'env_gain': [1.0, 1.0, 1.0], 'env_el': 5.0, 'env_az': 1.2, 'halo_gain': .15, 'halo_sigma': 12.0,
                   'floor_lat': -90.0, 'split_emitters': False, 'emit_clip': 3.0,
                   'amber_gain': 1.0, 'amber_el': 5.0, 'amber_az_min': 1.2, 'amber_core_gain': 0.0,
                   'amber_core_el': 1.5, 'amber_core_az_min': .35, 'k_az': 1.0, 'k_pow': 1.0, 'az_max': 12.0,
                   'blue_gain': 1.0, 'blue_el': 5.0, 'blue_az': 1.2,
                   # height_lobes: each emitter pixel is matched to its glows.json lamp and blurred
                   # by lobe_el/lobe_az (true glossy-lobe sigmas, deg) times k = h / (h + 1.17), h
                   # the lamp height over the deck. The proxy-box lookup measures angles from the
                   # mirror eye, which overstates a low source's streak by (h + 1.17) / h: a strip on
                   # the deck reflects as a thin line beside itself, a foot light as a short streak,
                   # an overhead lamp as a broad blob.
                   'height_lobes': False, 'lobe_el': 14.0, 'lobe_az': 14.0, 'el_min': .5, 'el_max': 90.0, 'k_floor': .05, 'el_floor': .4, 'high_gain': 1.0, 'core_gain': 0.0,
                   'core_scale': .35,
                   # Final look pass (None/1.0 reproduce v5): overhead lamps (k above .4-.6) get their own
                   # lobe caps and core gain, so they reflect as satin streaks toward the viewer instead
                   # of flat-topped round blobs; low amber sources (k under low_k) get low_gain and may
                   # streak longer (low_el_max), so foot and kick lamps read as vertical streaks.
                   'high_el_max': None, 'high_az_max': None, 'high_core_gain': None,
                   'low_gain': 1.0, 'low_k': .3, 'low_el_max': None,
                   # Per-lamp reflection gains by glows.json name: [{"name": "Corner console lamp", "gain": .35}]
                   # (name is a substring); every emitter pixel takes the gain of the lamp it is matched to.
                   'lamp_gains': []}
EYE_OVER_DECK = 1.65 - .48
STRIP_PATTERN = re.compile(r'\b(gasket|lip|lips|slat|slats)\b|runner rib|grate rail', re.I)
# Lens emission has its own gain so lamp_gain (the practical pools) can rise above 1 without
# pushing the authored 1.5 lens core past the 1.6 linear emitter cap.
LAMP_MATERIALS = {'warm lens': 'lens_emit_gain', 'warm diode': 'lens_emit_gain', 'blue diode': 'blue_emit_gain'}
# 'amber' are the small per-lens spill rects (lens_gain); 'practical' the foot/kick/sill pools.
LIGHT_KIND_GAIN = {'amber': 'lens_gain', 'practical': 'lamp_gain', 'blue': 'blue_gain', 'fill': 'fill_gain', 'earth': 'shine_gain',
                   'aft_fill': 'aft_fill_gain'}


def log(tag, payload):
    print(tag + ' ' + json.dumps(payload), flush=True)


def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------- export
def export_mesh(obj, path):
    # Blender's tangent builder rejects n-gon hatch/armor caps. Triangulate
    # only those caps after UV packing, preserving the authored corner normals.
    select(obj)
    triangulate = obj.modifiers.new('Runtime n-gon caps', 'TRIANGULATE')
    triangulate.min_vertices = 5
    if hasattr(triangulate, 'keep_custom_normals'):
        triangulate.keep_custom_normals = True
    bpy.ops.object.modifier_apply(modifier=triangulate.name)
    mesh = obj.data
    mesh.calc_loop_triangles()
    mesh.calc_tangents(uvmap=mesh.uv_layers.active.name)
    loops = np.array([list(t.loops) for t in mesh.loop_triangles]).reshape(-1)
    faces = np.array([list(t.vertices) for t in mesh.loop_triangles]).reshape(-1)
    convert = np.array([[1,0,0],[0,0,1],[0,-1,0]], dtype=float)
    world = np.array(obj.matrix_world)
    linear = world[:3,:3]
    positions = (np.array([list(v.co) for v in mesh.vertices])[faces] @ linear.T + world[:3,3]) @ convert.T
    normals = np.array([list(v.vector) for v in mesh.corner_normals])[loops] @ np.linalg.inv(linear) @ convert.T
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:,None], 1e-9)
    tangents = np.array([list(v.tangent) for v in mesh.loops])[loops] @ linear.T @ convert.T
    tangents -= normals * np.sum(tangents*normals, axis=1)[:,None]
    lengths = np.linalg.norm(tangents, axis=1)
    bad = lengths < .001
    if bad.any():
        axis=np.zeros_like(normals[bad]); axis[:,0]=1
        axis[np.abs(normals[bad,0])>.9]=(0,1,0)
        tangents[bad] = np.cross(axis,normals[bad])
        lengths=np.linalg.norm(tangents,axis=1)
    tangents /= lengths[:,None]
    signs = -np.array([v.bitangent_sign for v in mesh.loops])[loops]
    signs[bad]=1
    tangents=np.column_stack([tangents,signs])
    uv=np.array([list(v.uv) for v in mesh.uv_layers.active.data])[loops]
    uv[:,1]=1-uv[:,1]
    records=np.concatenate([positions,normals,tangents,uv],axis=1).astype('<f4')
    assert np.isfinite(records).all()
    # Clamped bevel edges can retain coincident corners. Filter after float32
    # quantization, exactly as the runtime sees them; their UVs cover no area.
    triangles=records.reshape(-1,3,12)
    points=triangles[:,:,:3].astype(np.float64)
    cross=np.cross(points[:,1]-points[:,0],points[:,2]-points[:,0])
    nonzero=np.any(cross!=0.0,axis=1)
    removed=int((~nonzero).sum())
    records=triangles[nonzero].reshape(-1,12)
    compact, inverse=np.unique(records,axis=0,return_inverse=True)
    indices=inverse.reshape(-1,3)[:,[0,2,1]].reshape(-1).astype('<u4')
    with path.open('wb') as f:
        f.write(struct.pack('<III',0x524f434b,len(compact),len(indices)))
        for a in [compact[:,:3],compact[:,3:6],compact[:,6:10],compact[:,10:12],indices]:
            f.write(a.tobytes())
    return {'vertices':len(compact),'triangles':len(indices)//3,'removed_zero_area_triangles':removed,
            'bounds':[compact[:,:3].min(axis=0).tolist(),compact[:,:3].max(axis=0).tolist()]}


def select(obj):
    if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active=obj


# ---------------------------------------------------------------- images (ROW-ORDER RULE)
def bpy_pixels(image):
    """Return a top-row-first float array (H, W, C) of a bpy image."""
    w, h = image.size
    buf = np.empty(w * h * image.channels, dtype=np.float32)
    image.pixels.foreach_get(buf)
    return np.flipud(buf.reshape(h, w, image.channels))


def write_float_image(name, array, path=None, keep=False):
    """Write a top-row-first float RGB(A) array through a bpy float image."""
    array = np.asarray(array, dtype=np.float32)
    h, w = array.shape[:2]
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[..., :array.shape[2]] = array[..., :4] if array.shape[2] <= 4 else array[..., :4]
    if array.shape[2] == 1:
        rgba[..., 1] = rgba[..., 2] = rgba[..., 0]
    image = bpy.data.images.get(name)
    if image is not None and (image.size[0] != w or image.size[1] != h):
        bpy.data.images.remove(image)
        image = None
    if image is None:
        image = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(np.flipud(rgba).ravel())
    image.update()
    if path is not None:
        image.filepath_raw = str(path)
        image.file_format = 'OPEN_EXR'
        image.save()
    if not keep and path is not None:
        bpy.data.images.remove(image)
        return None
    return image


def load_exr(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    image.colorspace_settings.name = 'Non-Color'
    array = bpy_pixels(image)
    bpy.data.images.remove(image)
    return array


# ---------------------------------------------------------------- parameters
def load_params(args):
    params = dict(DEFAULT_PARAMS)
    runtime = {}
    source = HERE / 'bake-params.json'
    file_values = {}
    if source.is_file():
        data = json.loads(source.read_text())
        runtime = dict(data.get('runtime', {}) or {})
        flat = dict(data.get('bake', {}) or {})
        flat.update({k: v for k, v in data.items() if k not in ('runtime', 'bake') and not isinstance(v, (dict, list))})
        for key, value in flat.items():
            norm = key.replace('-', '_').lower()
            if norm in params:
                file_values[norm] = value
        params.update(file_values)
    for key in GAIN_KEYS:
        value = getattr(args, key)
        if value is not None:
            params[key] = float(value)
    if args.no_rear_shield:
        params['rear_shield'] = False
    params['rear_shield'] = bool(params['rear_shield'])
    for key in GAIN_KEYS:
        params[key] = float(params[key])
    mirror = dict(MIRROR_DEFAULTS)
    if source.is_file():
        mirror.update({k: v for k, v in (json.loads(source.read_text()).get('mirror', {}) or {}).items() if k in MIRROR_DEFAULTS})
    params['mirror'] = mirror
    return params, runtime, (rel_root(source) if source.is_file() else None)


def rel_root(path):
    """File name for manifests (no local paths or workspace folders in the package)."""
    return Path(path).name


# ---------------------------------------------------------------- Earth-proxy world
def blender_equirect_dirs(width, height):
    """World directions (B) for a Blender Environment Texture, top-row-first.

    Blender maps u = 0.5 - atan2(y, x)/(2 pi) and v = 0.5 + lat/pi (v up),
    so numpy row 0 (after the row-order flip) is the zenith.
    """
    r = (np.arange(height) + .5) / height
    c = (np.arange(width) + .5) / width
    lat = (0.5 - r)[:, None] * np.pi
    lon = (0.5 - c)[None, :] * 2 * np.pi
    cl = np.cos(lat)
    return np.stack([np.cos(lon) * cl, np.sin(lon) * cl, np.broadcast_to(np.sin(lat), (height, width))], axis=-1), lat


def earth_proxy(params, width=2048, height=1024, twilight=True, ring=True):
    d_b, lat = blender_equirect_dirs(width, height)
    g = np.stack([d_b[..., 0], d_b[..., 2], -d_b[..., 1]], axis=-1)
    inside = EARTH_RADIUS_DEG - np.degrees(np.arccos(np.clip(g @ PLANET_G, -1, 1)))
    disk = smoothstep(-0.5, 0.5, inside)[..., None]
    center = PLANET_G * PLANET_DISTANCE
    b = g @ center
    disc = b * b - (center @ center - 1.0)
    hit = (disc >= 0) & (b > 0)
    t = np.where(hit, b - np.sqrt(np.maximum(disc, 0)), b)
    normal = t[..., None] * g - center
    normal /= np.maximum(np.linalg.norm(normal, axis=-1, keepdims=True), 1e-9)
    sun_side = (0.55 + 0.9 * smoothstep(-0.35, 0.25, normal @ SUN_G))[..., None]
    fade = 1 - smoothstep(TWILIGHT_FADE_DEG[0], TWILIGHT_FADE_DEG[1], inside)
    tw = ((np.exp(-np.maximum(inside, 0) / 3.5) * fade)[..., None]) * np.maximum(0.85, sun_side)
    radiance = disk * np.array([0.20, 0.32, 0.62]) * params['k_night']
    if twilight:
        radiance = radiance + disk * tw * np.array([0.30, 0.40, 0.62]) * params['k_tw']
    if ring:
        radiance = radiance + (1 - disk) * np.exp(-np.maximum(-inside, 0) / 0.6)[..., None] * np.array([0.45, 0.70, 1.0]) * params['k_limb'] * sun_side
    radiance = radiance + np.array([0.006, 0.010, 0.020])
    return radiance.astype(np.float32), d_b, lat


def setup_world(scene, params):
    """Environment Texture with the proxy; camera rays use cam_gain."""
    world = scene.world or bpy.data.worlds.new('Space')
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    radiance, _, _ = earth_proxy(params)
    image = write_float_image('Earth proxy', radiance, keep=True)
    try:
        image.pack()
    except RuntimeError as exc:
        print('SHIP_WORLD_PACK_SKIPPED', str(exc).strip(), flush=True)
    env = nt.nodes.new('ShaderNodeTexEnvironment'); env.name = 'Earth proxy'
    env.image = image; env.interpolation = 'Linear'; env.projection = 'EQUIRECTANGULAR'
    light_bg = nt.nodes.new('ShaderNodeBackground'); light_bg.name = 'Light background'
    light_bg.inputs['Strength'].default_value = 1.0
    cam_bg = nt.nodes.new('ShaderNodeBackground'); cam_bg.name = 'Camera background'
    cam_bg.inputs['Strength'].default_value = params['cam_gain']
    path = nt.nodes.new('ShaderNodeLightPath')
    mix = nt.nodes.new('ShaderNodeMixShader'); mix.name = 'Camera ray mix'
    out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(env.outputs['Color'], light_bg.inputs['Color'])
    nt.links.new(env.outputs['Color'], cam_bg.inputs['Color'])
    nt.links.new(path.outputs['Is Camera Ray'], mix.inputs['Fac'])
    nt.links.new(light_bg.outputs[0], mix.inputs[1])
    nt.links.new(cam_bg.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    world.cycles.sampling_method = 'MANUAL'
    world.cycles.sample_map_resolution = 1024
    return world


def solid_centroid(dirs, weight, mask):
    w = (weight * mask)[..., None]
    total = (dirs * w).reshape(-1, 3).sum(axis=0)
    return total / max(np.linalg.norm(total), 1e-12)


def angle_deg(a, b):
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))))


class HiddenScene:
    """Hide every object from render except the listed ones; restore on exit."""
    def __init__(self, scene, keep=()):
        self.scene, self.keep, self.saved = scene, set(keep), []
    def __enter__(self):
        for obj in self.scene.objects:
            if obj.name in self.keep:
                continue
            self.saved.append((obj, obj.hide_render))
            obj.hide_render = True
        return self
    def __exit__(self, *exc):
        for obj, value in self.saved:
            obj.hide_render = value


class RenderSettings:
    def __init__(self, scene, **values):
        self.scene, self.values, self.saved = scene, values, {}
    def __enter__(self):
        for key, value in self.values.items():
            owner, attr = key.split('.', 1) if '.' in key else ('render', key)
            target = getattr(self.scene, owner)
            self.saved[key] = getattr(target, attr)
            setattr(target, attr, value)
        return self
    def __exit__(self, *exc):
        for key, value in self.saved.items():
            owner, attr = key.split('.', 1) if '.' in key else ('render', key)
            setattr(getattr(self.scene, owner), attr, value)


def pano_camera(name, location, width, height, lat_min, lat_max):
    data = bpy.data.cameras.new(name)
    data.type = 'PANO'
    data.panorama_type = 'EQUIRECTANGULAR'
    data.longitude_min, data.longitude_max = -math.pi, math.pi
    data.latitude_min, data.latitude_max = math.radians(lat_min), math.radians(lat_max)
    data.clip_start = 0.01
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (math.radians(90), 0, 0)
    return obj


def render_camera(scene, camera, path, width, height, samples, denoise):
    previous = scene.camera
    scene.camera = camera
    with RenderSettings(scene, resolution_x=width, resolution_y=height, resolution_percentage=100,
                        filepath=str(path), film_transparent=False, use_border=False,
                        **{'cycles.samples': samples, 'cycles.use_denoising': denoise}):
        settings = scene.render.image_settings
        old = (settings.file_format, settings.color_depth, settings.color_mode)
        settings.file_format = 'OPEN_EXR'; settings.color_depth = '32'; settings.color_mode = 'RGB'
        try:
            bpy.ops.render.render(write_still=True)
        finally:
            settings.file_format, settings.color_depth, settings.color_mode = old
    scene.camera = previous
    return load_exr(path)


def camera_dirs(width, height, lat_min, lat_max):
    """Directions (B) of an equirect camera at rotation (90,0,0), top-row-first.

    Verified in Blender 4.5: the image centre looks along +Y and +X is to the right.
    """
    c = (np.arange(width) + .5) / width
    r = (np.arange(height) + .5) / height
    az = (c - 0.5)[None, :] * 2 * np.pi
    lat = np.radians(lat_max - r * (lat_max - lat_min))[:, None]
    cl = np.cos(lat)
    return np.stack([np.sin(az) * cl, np.cos(az) * cl, np.broadcast_to(np.sin(lat), (height, width))], axis=-1), lat


def world_self_tests(scene, params, out):
    world = scene.world
    nt = world.node_tree
    cam_bg = nt.nodes['Camera background']
    env = nt.nodes['Earth proxy']
    camera = pano_camera('World test eye', EYE_B, 128, 64, -90, 90)
    results = {}
    try:
        with HiddenScene(scene, keep={camera.name}):
            cam_bg.inputs['Strength'].default_value = 1.0
            # (a) full proxy: render centroid against the numpy centroid.
            radiance, d_b, lat = earth_proxy(params)
            lum = radiance @ np.array([.2126, .7152, .0722])
            background = float(np.array([0.006, 0.010, 0.020]) @ np.array([.2126, .7152, .0722]))
            threshold = 3.0 * background
            expected = solid_centroid(d_b, np.cos(lat), lum > threshold)
            shot = render_camera(scene, camera, out / '_selftest-world-a.exr', 128, 64, 16, False)
            cdirs, clat = camera_dirs(128, 64, -90, 90)
            slum = shot[..., :3] @ np.array([.2126, .7152, .0722])
            got = solid_centroid(cdirs, np.cos(clat), slum > threshold)
            results['a_deg'] = angle_deg(expected, got)
            # (b) disk only: centroid must be the authored Earth direction.
            plain, _, _ = earth_proxy(params, twilight=False, ring=False)
            write_float_image('Earth proxy test', plain, keep=True)
            env.image = bpy.data.images['Earth proxy test']
            shot = render_camera(scene, camera, out / '_selftest-world-b.exr', 128, 64, 16, False)
            slum = shot[..., :3] @ np.array([.2126, .7152, .0722])
            disk_lum = background + 0.5 * float(np.array([0.20, 0.32, 0.62]) @ np.array([.2126, .7152, .0722])) * params['k_night']
            got_b = solid_centroid(cdirs, np.cos(clat), slum > disk_lum)
            results['b_deg'] = angle_deg(EARTH_DIR_B, got_b)
    finally:
        env.image = bpy.data.images['Earth proxy']
        if bpy.data.images.get('Earth proxy test'):
            bpy.data.images.remove(bpy.data.images['Earth proxy test'])
        cam_bg.inputs['Strength'].default_value = params['cam_gain']
        bpy.data.objects.remove(camera, do_unlink=True)
        for name in ('_selftest-world-a.exr', '_selftest-world-b.exr'):
            (out / name).unlink(missing_ok=True)
    log('SHIP_WORLD_TEST', results)
    if results['a_deg'] > 3.0:
        raise RuntimeError('Earth-proxy world self-test (a) failed: render/numpy centroid differ by %.2f deg' % results['a_deg'])
    if results['b_deg'] > 2.0:
        raise RuntimeError('Earth-proxy world self-test (b) failed: disk centroid %.2f deg from EARTH_DIR' % results['b_deg'])
    print('SHIP_WORLD_OK', flush=True)
    return results


# ---------------------------------------------------------------- lights and lamps
def apply_gains(scene, params):
    """Scale baked lights by kind and lamp materials by gain; bases kept on the IDs."""
    counts = {}
    for obj in scene.objects:
        if obj.type != 'LIGHT':
            continue
        if 'base_energy' not in obj:
            obj['base_energy'] = float(obj.data.energy)
        kind = str(obj.get('light_kind', ''))
        gain = params[LIGHT_KIND_GAIN[kind]] if kind in LIGHT_KIND_GAIN else 1.0
        obj.data.energy = float(obj['base_energy']) * gain
        counts[kind or 'untagged'] = counts.get(kind or 'untagged', 0) + 1
    scaled = []
    for mat in bpy.data.materials:
        base_name = mat.name[3:] if mat.name.startswith('OD ') else mat.name
        base_name = base_name.split('.')[0]
        if base_name not in LAMP_MATERIALS or not mat.use_nodes:
            continue
        key = LAMP_MATERIALS[base_name]
        gain = params[key]
        if key == 'blue_emit_gain' and gain < 0:
            gain = params['blue_gain']
        bases = dict(mat.get('ws1_base_emission', {}))
        for node in mat.node_tree.nodes:
            socket = None
            if node.type == 'BSDF_PRINCIPLED':
                socket = node.inputs.get('Emission Strength')
            elif node.type == 'EMISSION':
                socket = node.inputs.get('Strength')
            if socket is None or socket.is_linked:
                continue
            if node.name not in bases:
                bases[node.name] = float(socket.default_value)
            socket.default_value = bases[node.name] * gain
        mat['ws1_base_emission'] = bases
        scaled.append(mat.name)
    log('SHIP_GAINS', {'lights': counts, 'materials': sorted(set(m.split('.')[0] for m in scaled)),
                       'lamp_gain': params['lamp_gain'], 'lens_gain': params['lens_gain'], 'blue_gain': params['blue_gain'],
                       'fill_gain': params['fill_gain'], 'shine_gain': params['shine_gain']})


def group_gain_lights(scene, group, rules):
    """Scale lights for one part's lighting bake (bake-params group_gains); returns the restore list."""
    restore, applied = [], {}
    for obj in scene.objects:
        if obj.type != 'LIGHT':
            continue
        kind = str(obj.get('light_kind', ''))
        gain = 1.0
        for rule in rules or []:
            if rule.get('group') != group:
                continue
            if rule.get('kind') is not None and rule['kind'] != kind:
                continue
            if rule.get('name') is not None and rule['name'] not in obj.name:
                continue
            gain *= float(rule['gain'])
        if gain != 1.0:
            restore.append((obj, obj.data.energy))
            obj.data.energy = obj.data.energy * gain
            applied[kind] = applied.get(kind, 0) + 1
    if restore:
        log('SHIP_GROUP_GAINS', {'part': group, 'lights_scaled': applied})
    return restore


def add_rear_shield(scene):
    """Opaque, camera-invisible plane at B y=-2.80 that stops direct earthlight aft."""
    mesh = bpy.data.meshes.new('Rear bay light shield')
    mesh.from_pydata([(-4.8, -2.80, 1.75), (4.8, -2.80, 1.75), (4.8, -2.80, 4.75), (-4.8, -2.80, 4.75)], [], [(0, 1, 2, 3)])
    mesh.update()
    mat = bpy.data.materials.new('WS1 shield black')
    mat.use_nodes = True
    nt = mat.node_tree; nt.nodes.clear()
    diffuse = nt.nodes.new('ShaderNodeBsdfDiffuse'); diffuse.inputs['Color'].default_value = (0, 0, 0, 1)
    out = nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(diffuse.outputs[0], out.inputs['Surface'])
    mesh.materials.append(mat)
    obj = bpy.data.objects.new('Rear bay light shield', mesh)
    scene.collection.objects.link(obj)
    obj.visible_camera = False
    obj.visible_diffuse = True
    obj.visible_glossy = True
    obj.visible_transmission = True
    obj.visible_shadow = True
    obj['bake_helper'] = True
    return obj


def is_helper(obj):
    return bool(obj.get('bake_helper', False))


# ---------------------------------------------------------------- glows
def to_g(v):
    return [float(v[0]), float(v[2]), float(-v[1])]


def collect_glows(objects):
    glows = []
    counts = {'amber': 0, 'blue': 0}
    for obj in objects:
        kind = obj.get('glow')
        if not kind:
            continue
        kind = str(kind)
        missing = [k for k in ('glow_c', 'facing', 'along', 'glow_size') if k not in obj]
        if missing:
            raise RuntimeError('Glow %s lacks %s' % (obj.name, missing))
        c = Vector(tuple(obj['glow_c'])); n = Vector(tuple(obj['facing'])).normalized(); u = Vector(tuple(obj['along'])).normalized()
        size = [float(x) for x in obj['glow_size']]
        glows.append({'name': obj.name, 'c': to_g(c), 'n': to_g(n), 'u': to_g(u), 'size': size, 'kind': kind})
        counts[kind] = counts.get(kind, 0) + 1
    return glows, counts


# ---------------------------------------------------------------- join, cull and UV
def select_faces(bm, wanted):
    """Face-mode selection of exactly the faces for which wanted(face) is true."""
    bm.select_mode = {'FACE'}
    for face in bm.faces:
        face.select_set(False)
    count = 0
    for face in bm.faces:
        if wanted(face):
            face.select_set(True)
            count += 1
    bm.select_flush_mode()
    return count


def unwrap_strip(obj):
    """Follow-active-quads on a strip's quads; returns the per-face flag list."""
    mesh = obj.data
    flags = [0] * len(mesh.polygons)
    quads = [p.index for p in mesh.polygons if len(p.vertices) == 4]
    if not quads:
        return flags
    select(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    best = max(quads, key=lambda i: bm.faces[i].calc_area())
    select_faces(bm, lambda face: len(face.verts) == 4)
    bm.faces.active = bm.faces[best]
    bmesh.update_edit_mesh(mesh)
    try:
        bpy.ops.uv.follow_active_quads(mode='LENGTH_AVERAGE')
        for i in quads:
            flags[i] = 1
    except RuntimeError as exc:
        print('SHIP_UV_STRIP_FALLBACK', obj.name, str(exc).strip(), flush=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    return flags


def cull_hidden_faces(obj, rear):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    bm.normal_update()
    doomed = []
    area = 0.0
    rules = {k: 0.0 for k in 'abcdef'}
    for face in bm.faces:
        n = face.normal
        c = face.calc_center_median()
        rule = None
        if n.z < -0.9 and FLOOR - .005 <= c.z <= FLOOR + .07:
            rule = 'a'
        elif n.z < -0.9 and c.z < FLOOR - .05:
            rule = 'b'
        elif abs(c.x) > 4.72 and n.x * math.copysign(1.0, c.x) > .9:
            rule = 'c'
        elif c.y < rear - 0.10 and n.y < -.9:
            rule = 'd'
        elif c.y > 6.70 and n.y > .9:
            rule = 'e'
        elif c.z > 5.25 and n.z > .9:
            rule = 'f'
        if rule:
            a = face.calc_area()
            area += a
            rules[rule] += a
            doomed.append(face)
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='FACES')
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {'culled_m2': round(area, 4), 'culled_faces': len(doomed), 'culled_by_rule_m2': {k: round(v, 4) for k, v in rules.items()}}


# A hidden sheet (the deck underlay, `atlas_token`) keeps its island but at this scale: about 3 x 3 cm
# of atlas per metre of surface, so it costs almost nothing and still bakes its own dark value.
ATLAS_TOKEN_SCALE = 1 / 32


def shrink_token_islands(bm, token):
    uv = bm.loops.layers.uv.active
    for face in bm.faces:
        if token[face.index]:
            loops = [loop[uv] for loop in face.loops]
            cx = sum(l.uv.x for l in loops) / len(loops)
            cy = sum(l.uv.y for l in loops) / len(loops)
            for l in loops:
                l.uv.x, l.uv.y = cx + (l.uv.x - cx) * ATLAS_TOKEN_SCALE, cy + (l.uv.y - cy) * ATLAS_TOKEN_SCALE


def pack_margin(resolution):
    """Island gap as a fraction of the atlas: 8 texels (4 at 1K and below).

    The plan's fixed FRACTION .006 left the deck atlas 4.4% covered (thousands of
    small bevel islands each paid a 0.012-wide gap); measured on the v3 interior.
    """
    return max(4.0, min(8.0, resolution / 256.0)) / resolution


def pack_atlas(obj, shape_method, margin):
    started = time.monotonic()
    used = shape_method
    try:
        bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=margin, shape_method=shape_method)
    except TypeError:
        used = None
        bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=margin)
    return used, time.monotonic() - started


def uv_metrics(obj, resolution, token=None):
    mesh = obj.data
    mesh.calc_loop_triangles()
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    mesh.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    tl = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get('loops', tl)
    tv = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get('vertices', tv)
    tl = tl.reshape(-1, 3); tv = tv.reshape(-1, 3)
    if token is not None and token.any():
        # Texel density of what can be seen: the hidden sheet's token patch stays out of it.
        polys = np.empty(len(mesh.loop_triangles), dtype=np.int64)
        mesh.loop_triangles.foreach_get('polygon_index', polys)
        tl, tv = tl[token[polys] == 0], tv[token[polys] == 0]
    a, b, c = uv[tl[:, 0]], uv[tl[:, 1]], uv[tl[:, 2]]
    uv_area = float(np.abs(np.cross(b - a, c - a)).sum() * .5)
    p, q, r = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
    area = float(np.linalg.norm(np.cross(q - p, r - p), axis=1).sum() * .5)
    return {'uv_coverage': round(uv_area, 4), 'surface_m2': round(area, 3),
            'texels_per_m': round(math.sqrt(uv_area * resolution * resolution / max(area, 1e-9)), 1)}


def join_group(name, members, rear, lighting_res, shape_state):
    scene = bpy.context.scene
    for obj in members:
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        if obj.modifiers:
            select(obj)
            for modifier in list(obj.modifiers):
                bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in members:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = members[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # UV operators read the mesh face selection only with UV sync selection on.
    scene.tool_settings.use_uv_select_sync = True
    scene.tool_settings.mesh_select_mode = (False, False, True)
    strips = 0
    for obj in members:
        mesh = obj.data
        while mesh.uv_layers:
            mesh.uv_layers.remove(mesh.uv_layers[0])
        mesh.uv_layers.new(name='Runtime atlas')
        flags = [0] * len(mesh.polygons)
        if bool(obj.get('uv_strip')) or STRIP_PATTERN.search(obj.name):
            flags = unwrap_strip(obj)
            strips += 1
        attr = mesh.attributes.get('ws1_fq') or mesh.attributes.new('ws1_fq', 'INT', 'FACE')
        attr.data.foreach_set('value', flags)
        attr = mesh.attributes.get('ws1_token') or mesh.attributes.new('ws1_token', 'INT', 'FACE')
        attr.data.foreach_set('value', [1 if obj.get('atlas_token') else 0] * len(mesh.polygons))
    bpy.ops.object.select_all(action='DESELECT')
    for obj in members:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = members[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    world = np.array(obj.matrix_world)
    assert np.allclose(world, np.eye(4), atol=1e-9), 'Joined %s is not at identity' % name
    cull = cull_hidden_faces(obj, rear)
    # Unique material copies prevent one atlas becoming another group's target.
    for slot in obj.material_slots:
        slot.material = slot.material.copy()
    while len(obj.data.uv_layers) > 1:
        obj.data.uv_layers.remove(obj.data.uv_layers[1])
    obj.data.uv_layers.active = obj.data.uv_layers[0]
    scene.tool_settings.use_uv_select_sync = True
    flags = np.zeros(len(obj.data.polygons), dtype=np.int32)
    if obj.data.attributes.get('ws1_fq'):
        obj.data.attributes['ws1_fq'].data.foreach_get('value', flags)
    token = np.zeros(len(obj.data.polygons), dtype=np.int32)
    if obj.data.attributes.get('ws1_token'):
        obj.data.attributes['ws1_token'].data.foreach_get('value', token)
    select(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    smart = select_faces(bm, lambda face: flags[face.index] == 0)
    bmesh.update_edit_mesh(obj.data)
    started = time.monotonic()
    if smart:
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.004, area_weight=.5,
                                 correct_aspect=True, scale_to_bounds=False)
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    if token.any():
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        shrink_token_islands(bm, token)
        bmesh.update_edit_mesh(obj.data)
    unwrap_seconds = time.monotonic() - started
    margin = pack_margin(lighting_res)
    used, seconds = pack_atlas(obj, shape_state['method'], margin)
    retried = False
    if seconds > 120 and used == 'CONCAVE':
        print('SHIP_UV_SLOW', name, round(seconds, 1), 'retrying with CONVEX', flush=True)
        used, seconds2 = pack_atlas(obj, 'CONVEX', margin)
        seconds += seconds2
        retried = True
    bpy.ops.object.mode_set(mode='OBJECT')
    if obj.data.attributes.get('ws1_fq'):
        obj.data.attributes.remove(obj.data.attributes['ws1_fq'])
    if obj.data.attributes.get('ws1_token'):
        obj.data.attributes.remove(obj.data.attributes['ws1_token'])
    info = dict(cull)
    info.update(uv_metrics(obj, lighting_res, token))
    info.update({'uv_pack_margin': round(margin, 5), 'uv_shape_method': used, 'uv_pack_seconds': round(seconds, 1), 'uv_unwrap_seconds': round(unwrap_seconds, 1),
                 'uv_pack_retried': retried, 'strip_objects': strips, 'members': len(members), 'matrix_world_identity': True})
    log('SHIP_GROUP_READY', dict(info, part=name))
    return obj, info


# ---------------------------------------------------------------- baking
def bake(scene,obj,kind,path,size,samples):
    select(obj)
    image=bpy.data.images.new(obj.name+' '+kind,width=size,height=size,alpha=False,float_buffer=True)
    image.colorspace_settings.name='Non-Color'
    restores=[]
    targets=[]
    for mat in obj.data.materials:
        nodes=mat.node_tree.nodes; links=mat.node_tree.links
        target=nodes.new('ShaderNodeTexImage'); target.image=image; nodes.active=target; targets.append((mat,target))
        if kind=='albedo':
            outputs=[n for n in nodes if n.type=='OUTPUT_MATERIAL']
            output=next((n for n in outputs if n.is_active_output),outputs[0])
            original=output.inputs['Surface'].links[0].from_socket
            principled=next((n for n in nodes if n.type=='BSDF_PRINCIPLED'),None)
            emission=nodes.new('ShaderNodeEmission')
            if principled:
                color=principled.inputs['Base Color']
                if color.is_linked: links.new(color.links[0].from_socket,emission.inputs['Color'])
                else: emission.inputs['Color'].default_value=color.default_value
            else: emission.inputs['Color'].default_value=(.08,.08,.08,1)
            links.new(emission.outputs[0],output.inputs['Surface'])
            restores.append((mat,output,original,emission))
    settings=scene.render.bake
    deck=obj.name=='deck'
    saved=(settings.view_from,settings.use_pass_glossy,scene.camera)
    scene.cycles.samples=samples if kind=='lighting' else ALBEDO_SAMPLES
    settings.use_selected_to_active=False
    settings.use_clear=True
    settings.margin=16 if size>=2048 else 8
    settings.use_pass_direct=True
    settings.use_pass_indirect=True
    settings.use_pass_color=True
    settings.use_pass_diffuse=True
    settings.use_pass_transmission=True
    settings.use_pass_emit=True
    # The runtime adds the deck's specular (mirror map); bake it diffuse only.
    settings.use_pass_glossy=not deck
    camera=bpy.data.objects.get('Seated reference')
    if camera is not None:
        scene.camera=camera
    settings.view_from='ABOVE_SURFACE' if deck or camera is None else 'ACTIVE_CAMERA'
    started=time.monotonic()
    try:
        bpy.ops.object.bake(type='COMBINED' if kind=='lighting' else 'EMIT',uv_layer=obj.data.uv_layers.active.name)
    finally:
        settings.view_from,settings.use_pass_glossy,scene.camera=saved
    image.filepath_raw=str(path); image.file_format='OPEN_EXR'; image.save()
    for mat,output,original,emission in restores:
        mat.node_tree.links.new(original,output.inputs['Surface']); mat.node_tree.nodes.remove(emission)
    for mat,target in targets: mat.node_tree.nodes.remove(target)
    bpy.data.images.remove(image)
    log('SHIP_BAKED',{'part':obj.name,'kind':kind,'size':size,'samples':scene.cycles.samples,
                      'view_from':'ABOVE_SURFACE' if deck else 'ACTIVE_CAMERA','glossy':not deck,
                      'seconds':round(time.monotonic()-started,1)})


# ---------------------------------------------------------------- mirror map
def gaussian_kernel(sigma):
    radius = max(1, int(math.ceil(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum(), radius


def blur_vertical(array, sigma):
    """Clamped-reflect Gaussian along rows via a dense (H x H) operator."""
    h = array.shape[0]
    kernel, radius = gaussian_kernel(sigma)
    rows = np.arange(h)
    matrix = np.zeros((h, h))
    period = 2 * h
    for k, w in zip(range(-radius, radius + 1), kernel):
        j = (rows + k) % period
        j = np.where(j >= h, period - 1 - j, j)
        np.add.at(matrix, (rows, j), w)
    flat = array.reshape(h, -1).astype(np.float64)
    return (matrix @ flat).reshape(array.shape)


def blur_horizontal_wrap(array, sigma):
    w = array.shape[1]
    kernel, radius = gaussian_kernel(sigma)
    circ = np.zeros(w)
    for k, v in zip(range(-radius, radius + 1), kernel):
        circ[k % w] += v
    spectrum = np.fft.rfft(circ)
    data = np.fft.rfft(array.astype(np.float64), axis=1)
    return np.fft.irfft(data * spectrum[None, :, None], n=w, axis=1)


def blur_horizontal_rows(array, sigma_px):
    """Per-row Gaussian along the wrapping azimuth (sigma in px for each row), Fourier form."""
    w = array.shape[1]
    f = np.fft.rfftfreq(w)
    spectrum = np.exp(-2.0 * (np.pi * f[None, :] * np.asarray(sigma_px, dtype=np.float64)[:, None]) ** 2)
    data = np.fft.rfft(array.astype(np.float64), axis=1)
    return np.fft.irfft(data * spectrum[:, :, None], n=w, axis=1)


def mirror_row_lat():
    return MIRROR_LAT_MAX - (np.arange(MIRROR_H) + .5) * (MIRROR_LAT_MAX - MIRROR_LAT_MIN) / MIRROR_H


def glossy_lobe(array, el_deg, k_az, az_min, az_max, k_pow=1.0):
    """Across the lobe: el*k_az*sin(lat)^k_pow of true angle (thin at grazing, round overhead),
    i.e. divided by cos(lat) in azimuth degrees."""
    px_deg_v = MIRROR_H / (MIRROR_LAT_MAX - MIRROR_LAT_MIN)
    px_deg_h = MIRROR_W / 360.0
    lat = np.radians(np.clip(mirror_row_lat(), .5, 89.5))
    az = np.clip(el_deg * k_az * np.sin(lat) ** k_pow / np.cos(lat), az_min, az_max)
    return blur_horizontal_rows(blur_vertical(array, el_deg * px_deg_v), az * px_deg_h)


def emitter_height_k(emit, glows, u_sign, return_index=False):
    """Per-pixel k = h / (h + 1.17) for the emitter layer: nearest glows.json lamp (segment
    distance in mirror pixels, azimuth wrapping); pixels with no lamp within 14 px get k .3.
    return_index also returns the matched glows.json index per pixel (-1: none)."""
    lum = emit.sum(axis=2)
    ys, xs = np.nonzero(lum > 1e-5)
    k = np.zeros(lum.shape)
    index = np.full(lum.shape, -1, dtype=np.int64)
    if not len(ys) or not glows:
        return (k, index) if return_index else k
    segs = []
    for g in glows:
        c = np.array(g['c'], dtype=np.float64)
        u = np.array(g['u'], dtype=np.float64)
        half = .5 * float(g['size'][0])
        ends = []
        for p in (c - u * half, c + u * half):
            px, py = mirror_lookup_pixel((p[0], -p[2], p[1]), MIRROR_W, MIRROR_H, u_sign)
            ends.append((px - .5, py - .5))
        (ax, ay), (bx, by) = ends
        if bx - ax > MIRROR_W / 2: bx -= MIRROR_W
        if ax - bx > MIRROR_W / 2: bx += MIRROR_W
        h = max(float(c[1]) - .48, .01)
        segs.append((ax, ay, bx, by, h / (h + EYE_OVER_DECK)))
    segs = np.array(segs)
    best = np.full(len(ys), np.inf)
    kk = np.full(len(ys), .3)
    ii = np.full(len(ys), -1, dtype=np.int64)
    for gi, (ax, ay, bx, by, kg) in enumerate(segs):
        for shift in (-MIRROR_W, 0, MIRROR_W):
            px, py = xs - (ax + shift), ys - ay
            dx, dy = bx - ax, by - ay
            t = np.clip((px * dx + py * dy) / max(dx * dx + dy * dy, 1e-9), 0, 1)
            d = np.hypot(px - t * dx, py - t * dy)
            better = d < best
            best = np.where(better, d, best)
            kk = np.where(better, kg, kk)
            ii = np.where(better, gi, ii)
    kk = np.where(best <= 14, kk, .3)
    k[ys, xs] = kk
    index[ys, xs] = np.where(best <= 14, ii, -1)
    return (k, index) if return_index else k


def high_weight(k):
    """0 for low sources, 1 for overhead lamps (k .4 -> .6, smoothstep)."""
    t = np.clip((np.asarray(k, dtype=np.float64) - .4) / .2, 0, 1)
    return t * t * (3 - 2 * t)


def lobe_caps(km, m):
    """Elevation and azimuth caps (deg) for one height band; the defaults give v5's single el_max/az_max."""
    el_cap, az_cap = m['el_max'], m['az_max']
    t = float(high_weight(km))
    if m.get('high_el_max') is not None:
        el_cap += (m['high_el_max'] - m['el_max']) * t
    if m.get('high_az_max') is not None:
        az_cap += (m['high_az_max'] - m['az_max']) * t
    if m.get('low_el_max') is not None and km < m['low_k']:
        el_cap = m['low_el_max']
    return el_cap, az_cap


def height_lobes(layer, k, m, sigma_scale=1.0):
    """Blur an emitter layer in bands of k with sigmas lobe_* x k (deg), azimuth thinned by
    sin(lat)^k_pow at grazing and widened by 1/cos(lat) into azimuth degrees."""
    px_deg_v = MIRROR_H / (MIRROR_LAT_MAX - MIRROR_LAT_MIN)
    px_deg_h = MIRROR_W / 360.0
    lat = np.radians(np.clip(mirror_row_lat(), .5, 89.5))
    edges = [0.0, .03, .06, .1, .16, .25, .4, .6, 1.01]
    out = np.zeros(layer.shape)
    for lo, hi in zip(edges, edges[1:]):
        band = (k > lo) & (k <= hi)
        if not band.any():
            continue
        km = float(np.median(k[band]))
        part = np.where(band[..., None], layer, 0)
        # Deck-level sources (k under k_floor: strips, vent lamps) reflect as tight lines beside
        # themselves; everything higher keeps at least el_min of streak (the satin plate's grain).
        lo_el = m['el_floor'] if km < m['k_floor'] else m['el_min']
        el_cap, az_cap = lobe_caps(km, m)
        el = min(max(m['lobe_el'] * km, lo_el) * sigma_scale, el_cap * sigma_scale)
        az = np.clip(m['lobe_az'] * km * sigma_scale * np.sin(lat) ** m['k_pow'] / np.cos(lat), m['amber_az_min'], az_cap)
        out += blur_horizontal_rows(blur_vertical(part, el * px_deg_v), az * px_deg_h)
    return out


def prefilter_mirror(raw, emit=None, m=None, glows=None, u_sign=1):
    m = dict(MIRROR_DEFAULTS, **(m or {}))
    px_deg_v = MIRROR_H / (MIRROR_LAT_MAX - MIRROR_LAT_MIN)
    px_deg_h = MIRROR_W / 360.0
    split = bool(m['split_emitters']) and emit is not None
    if split:
        emit = np.clip(emit, 0, m['emit_clip'])
        env = np.clip(raw - emit, 0, None)
    else:
        env = raw.copy()
    # Rows below the lowest latitude the runtime lookup reaches (about 9.3 deg at the proxy-box
    # corners) hold the Earth band under the room edges; extend the floor row instead of letting
    # the blur carry it up into the bench band.
    if m['floor_lat'] > MIRROR_LAT_MIN:
        floor_row = int(round((MIRROR_LAT_MAX - m['floor_lat']) * px_deg_v))
        env[floor_row:] = env[floor_row:floor_row + 1]
    env = env * np.asarray(m['env_gain'], dtype=np.float64)
    core = blur_horizontal_wrap(blur_vertical(env, m['env_el'] * px_deg_v), m['env_az'] * px_deg_h)
    halo = blur_horizontal_wrap(blur_vertical(env, m['halo_sigma'] * px_deg_v), m['halo_sigma'] * px_deg_h)
    result = core + m['halo_gain'] * halo
    if split and m['height_lobes']:
        k, index = emitter_height_k(emit, glows or [], u_sign, return_index=True)
        if m.get('lamp_gains'):
            per_glow = np.ones(len(glows or []) + 1)
            for gi, glow in enumerate(glows or []):
                for rule in m['lamp_gains']:
                    if rule['name'] in str(glow.get('name', '')):
                        per_glow[gi] *= float(rule['gain'])
            emit = emit * per_glow[index][..., None]
        blue = (emit[..., 2] > emit[..., 0])[..., None]
        # Low amber sources (foot, kick and table lamps) may get low_gain: brighter, narrow streaks.
        low = 1 - smoothstep(m['low_k'] - .1, m['low_k'], k)
        gain = np.where(blue, m['blue_gain'], m['amber_gain'] * (1 + (m['low_gain'] - 1) * low)[..., None])
        # Overhead fixtures (k above .4: canopy nodes, eaves, ceiling slits) are larger lamps;
        # high_gain lifts their floor highlights (the lamp sheen seen looking down) without the low streaks.
        t = np.clip((k - .4) / .3, 0, 1)
        gain = gain * (1 + (m['high_gain'] - 1) * (t * t * (3 - 2 * t)))[..., None]
        result = result + height_lobes(gain * emit, k, m)
        if m['core_gain'] > 0:
            core = m['core_gain'] if m.get('high_core_gain') is None else \
                m['core_gain'] + (m['high_core_gain'] - m['core_gain']) * high_weight(k)
            result = result + height_lobes(np.asarray(core)[..., None] * gain * emit if np.ndim(core) else core * gain * emit, k, m, m['core_scale'])
    elif split:
        blue = (emit[..., 2] > emit[..., 0])[..., None]
        amber = np.where(blue, 0, emit)
        strips = np.where(blue, emit, 0)
        result = result + m['amber_gain'] * glossy_lobe(amber, m['amber_el'], m['k_az'], m['amber_az_min'], m['az_max'], m['k_pow'])
        if m['amber_core_gain'] > 0:
            result = result + m['amber_core_gain'] * glossy_lobe(amber, m['amber_core_el'], m['k_az'], m['amber_core_az_min'],
                                                                 m['az_max'], m['k_pow'])
        result = result + m['blue_gain'] * blur_horizontal_wrap(blur_vertical(strips, m['blue_el'] * px_deg_v), m['blue_az'] * px_deg_h)
    return np.concatenate([result[:, -MIRROR_PAD:], result, result[:, :MIRROR_PAD]], axis=1)


def mirror_lookup_pixel(point_b, width, height, u_sign):
    q = np.array([point_b[0], point_b[2], -point_b[1]]) - np.array([MIRROR_EYE_B[0], MIRROR_EYE_B[2], -MIRROR_EYE_B[1]])
    q /= np.linalg.norm(q)
    u = .5 + u_sign * math.atan2(q[0], -q[2]) / (2 * math.pi)
    v = (math.radians(90) - math.asin(q[1])) / math.radians(MIRROR_LAT_MAX - MIRROR_LAT_MIN)
    return u * width, v * height


def mirror_self_test(scene, camera, out):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=.05, location=(3, 3, 1.2), segments=16, ring_count=8)
    marker = bpy.context.object
    marker.name = 'Mirror orientation marker'
    mat = bpy.data.materials.new('WS1 red marker'); mat.use_nodes = True
    nt = mat.node_tree; nt.nodes.clear()
    emit = nt.nodes.new('ShaderNodeEmission'); emit.inputs['Color'].default_value = (1, 0, 0, 1); emit.inputs['Strength'].default_value = 200
    outn = nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(emit.outputs[0], outn.inputs['Surface'])
    marker.data.materials.append(mat)
    try:
        with HiddenScene(scene, keep={camera.name, marker.name}):
            shot = render_camera(scene, camera, out / '_selftest-mirror.exr', 256, 73, 16, False)
    finally:
        bpy.data.objects.remove(marker, do_unlink=True)
        bpy.data.materials.remove(mat)
        (out / '_selftest-mirror.exr').unlink(missing_ok=True)
    redness = shot[..., 0] - 0.5 * (shot[..., 1] + shot[..., 2])
    row, col = np.unravel_index(np.argmax(redness), redness.shape)
    weights = np.clip(redness, 0, None)
    window = weights[max(0, row-3):row+4, max(0, col-3):col+4]
    ys, xs = np.mgrid[max(0, row-3):row+4, max(0, col-3):col+4]
    found = (float((xs * window).sum() / window.sum()) + .5, float((ys * window).sum() / window.sum()) + .5)
    result = {'found_px': [round(found[0], 2), round(found[1], 2)]}
    best = None
    for sign in (1, -1):
        ex, ey = mirror_lookup_pixel((3, 3, 1.2), 256, 73, sign)
        du = abs((found[0] - ex + 128) % 256 - 128)
        dv = abs(found[1] - ey)
        result['expected_px_sign%+d' % sign] = [round(ex, 2), round(ey, 2)]
        if best is None or du < best[1]:
            best = (sign, du, dv)
    u_sign, du, dv = best
    result.update(u_sign=u_sign, du_px=round(du, 2), dv_px=round(dv, 2))
    log('SHIP_MIRROR_TEST', result)
    if du > 4:
        raise RuntimeError('Mirror orientation self-test: u error %.2f px for either sign' % du)
    if dv > 4:
        raise RuntimeError('Mirror orientation self-test failed: v error %.2f px' % dv)
    return u_sign, result


def render_emitter_layer(scene, camera, out, deck):
    """Emitter-only mirror layer: every mesh but the emission group is a holdout, film transparent."""
    saved = []
    for obj in scene.objects:
        if obj.type == 'MESH' and obj is not deck and obj.name != 'emission':
            saved.append((obj, 'is_holdout', obj.is_holdout))
            obj.is_holdout = True
    previous = scene.camera
    scene.camera = camera
    try:
        with RenderSettings(scene, resolution_x=MIRROR_W, resolution_y=MIRROR_H, resolution_percentage=100,
                            filepath=str(out / 'deck-mirror-emit-raw.exr'), film_transparent=True, use_border=False,
                            **{'cycles.samples': 64, 'cycles.use_denoising': False}):
            settings = scene.render.image_settings
            old = (settings.file_format, settings.color_depth, settings.color_mode)
            settings.file_format = 'OPEN_EXR'; settings.color_depth = '32'; settings.color_mode = 'RGB'
            try:
                bpy.ops.render.render(write_still=True)
            finally:
                settings.file_format, settings.color_depth, settings.color_mode = old
    finally:
        scene.camera = previous
        for obj, attr, value in saved:
            setattr(obj, attr, value)
    return load_exr(out / 'deck-mirror-emit-raw.exr')[..., :3]


def bake_mirror(scene, out, deck, mparams=None, glows=None):
    started = time.monotonic()
    mparams = dict(MIRROR_DEFAULTS, **(mparams or {}))
    camera = pano_camera('Deck mirror eye', MIRROR_EYE_B, MIRROR_W, MIRROR_H, MIRROR_LAT_MIN, MIRROR_LAT_MAX)
    saved = []
    try:
        u_sign, test = mirror_self_test(scene, camera, out)
        if deck is not None:
            saved.append((deck, 'visible_camera', deck.visible_camera))
            deck.visible_camera = False
        for obj in scene.objects:
            if obj.type == 'LIGHT':
                saved.append((obj, 'visible_camera', obj.visible_camera))
                saved.append((obj, 'visible_glossy', obj.visible_glossy))
                obj.visible_camera = False
                obj.visible_glossy = False
        try:
            scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        except Exception:
            pass
        raw = render_camera(scene, camera, out / 'deck-mirror-raw.exr', MIRROR_W, MIRROR_H, MIRROR_SAMPLES, True)[..., :3]
        emit = render_emitter_layer(scene, camera, out, deck) if mparams['split_emitters'] else None
    finally:
        for obj, attr, value in saved:
            setattr(obj, attr, value)
        bpy.data.objects.remove(camera, do_unlink=True)
    filtered = prefilter_mirror(raw, emit, mparams, glows, u_sign).astype(np.float32)
    write_float_image('deck-mirror', filtered, out / 'deck-mirror.exr')
    peak = np.unravel_index(np.argmax(filtered[..., :3].sum(axis=2)), filtered.shape[:2])
    info = {'u_sign': u_sign, 'self_test': test, 'raw_mean': [round(float(x), 5) for x in raw.reshape(-1, 3).mean(axis=0)],
            'filtered_peak_px': [int(peak[1]), int(peak[0])], 'size': [int(filtered.shape[1]), int(filtered.shape[0])],
            'emitter_layer_mean': None if emit is None else [round(float(x), 5) for x in emit.reshape(-1, 3).mean(axis=0)],
            'seconds': round(time.monotonic() - started, 1)}
    log('SHIP_MIRROR', info)
    return info


# ---------------------------------------------------------------- wear map
WEAR_SCUFF_M = .04       # final look pass: nothing broader than about 4 cm (v5 had 20-30 cm blotches)
WEAR_SCRATCHES = 1800


def wear_map(path, size=WEAR_SIZE, seed=WEAR_SEED):
    """Satin wear: small scuffs (1/f noise high-passed at WEAR_SCUFF_M) and short scratches.

    The v5 map's broad blotches read as cloudy smoke across the plates in the down view; the deck
    should read as satin steel with fine use marks, so the low frequencies are removed."""
    rng = np.random.default_rng(seed)
    f = np.fft.fftfreq(size)
    k = np.sqrt(f[:, None] ** 2 + f[None, :] ** 2)
    k[0, 0] = 1.0
    px_per_m = size / (1 / .6)          # the runtime samples wear at room XZ * 0.6
    k0 = 1.0 / (WEAR_SCUFF_M * px_per_m)
    spectrum = np.fft.fft2(rng.standard_normal((size, size))) * k ** (-2.2 / 2) * (1 - np.exp(-(k / k0) ** 2))
    spectrum[0, 0] = 0
    blotch = np.real(np.fft.ifft2(spectrum))
    blotch /= blotch.std()
    value = .5 + .08 * np.clip(blotch, -2.5, 2.5)
    scratch = np.zeros((size, size))
    for _ in range(WEAR_SCRATCHES):
        length = rng.uniform(.01, .06) * px_per_m
        angle = math.radians(rng.uniform(-20, 20) if rng.random() < .7 else rng.uniform(0, 180))
        cx, cy = rng.uniform(0, size, 2)
        strength = rng.uniform(.10, .22) * (1 if rng.random() < .8 else -1)
        steps = max(2, int(length * 2))
        t = np.linspace(-.5, .5, steps) * length
        xs = cx + t * math.cos(angle)
        ys = cy + t * math.sin(angle)
        taper = np.sin(np.linspace(0, math.pi, steps)) ** .5
        x0 = np.floor(xs).astype(int); y0 = np.floor(ys).astype(int)
        fx = xs - x0; fy = ys - y0
        for dx, dy, w in ((0, 0, (1-fx)*(1-fy)), (1, 0, fx*(1-fy)), (0, 1, (1-fx)*fy), (1, 1, fx*fy)):
            np.add.at(scratch, ((y0 + dy) % size, (x0 + dx) % size), w * taper * strength * .5)
    value = np.clip(value + np.clip(scratch, -.25, .25), .15, .85)
    write_float_image('deck-wear', np.repeat(value[..., None], 3, axis=2).astype(np.float32), path)
    info = {'size': size, 'seed': seed, 'beta': 2.2, 'highpass_m': WEAR_SCUFF_M, 'scratches': WEAR_SCRATCHES, 'min': round(float(value.min()), 3),
            'max': round(float(value.max()), 3), 'mean': round(float(value.mean()), 3)}
    log('SHIP_WEAR', info)
    return info


# ---------------------------------------------------------------- scene setup
def configure_cycles(scene, samples):
    scene.render.engine='CYCLES';scene.cycles.samples=samples
    scene.cycles.use_denoising=True;scene.cycles.max_bounces=6
    prefs=bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type='OPTIX';prefs.get_devices()
        for d in prefs.devices: d.use=d.type=='OPTIX'
        scene.cycles.device='GPU' if any(d.use for d in prefs.devices) else 'CPU'
    except Exception: scene.cycles.device='CPU'
    scene.render.resolution_x=1600;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'


def bake_groups(objects):
    groups = {}
    for obj in objects:
        if obj.type != 'MESH' or is_helper(obj):
            continue
        groups.setdefault(str(obj.get('bake_group', 'detail')), []).append(obj)
    return groups


def resolutions(name, quick):
    if quick:
        return 1024, 512
    return LIGHT_RES.get(name, 2048), ALBEDO_RES.get(name, 1024)


def sync_shield(scene, wanted):
    shields = [o for o in scene.objects if is_helper(o)]
    if wanted and not shields:
        shields = [add_rear_shield(scene)]
    if not wanted:
        for obj in shields:
            bpy.data.objects.remove(obj, do_unlink=True)
        shields = []
    return [o.name for o in shields]


def interior_label(path):
    # The bare file name (no local paths or workspace folders in the package).
    return rel_root(path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--samples',type=int,default=192)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--only-build',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Resume the saved merged bake scene in the same output directory')
    parser.add_argument('--relight-from',type=Path,help='Re-bake only the lighting maps and the mirror map of an existing bake')
    parser.add_argument('--interior',type=Path,default=HERE/'build_interior.py',help='Authoring module (default: build_interior.py beside this file)')
    for key,help_text in (('k-night','night-disk gain (default .30)'),('k-tw','twilight-band gain (3.0)'),('k-limb','limb-ring gain (1.5)'),
                          ('cam-gain','camera-ray world strength (.25)'),('lamp-gain','amber/practical light and warm lens gain (1.0)'),
                          ('lens-gain','per-lens amber spill light gain (1.0)'),('lens-emit-gain','warm lens/diode emission gain (1.0)'),('shine-gain','earthshine side panels gain (1.0)'),
                          ('blue-gain','blue light and diode gain (1.0)'),('fill-gain','fill light gain (1.0)'),
                          ('aft-fill-gain','aft coffer fill gain (1.0)'),('blue-emit-gain','blue diode emission gain (-1 = follow blue-gain)')):
        parser.add_argument('--'+key,type=float,default=None,help=help_text)
    parser.add_argument('--no-rear-shield',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    started_all=time.monotonic()
    out=args.output.resolve(); out.relative_to(ROOT.resolve()); out.mkdir(parents=True,exist_ok=True)
    params,runtime,params_file=load_params(args)
    log('SHIP_PARAMS',{'params':params,'runtime':runtime,'file':params_file})
    interior_path=args.interior.resolve()
    relight=args.relight_from.resolve() if args.relight_from else None
    if relight is not None:
        assert relight != out, '--relight-from must write into a new --output directory'
        for name in ['observation-deck-bake.blend','glows.json','starship.json']+[p.name for p in relight.glob('*.bin')]+[p.name for p in relight.glob('*-albedo.exr')]+(['prep.json'] if (relight/'prep.json').exists() else []):
            shutil.copyfile(relight/name,out/name)
    rear=-6.5
    source=None
    if args.resume or relight is not None:
        bpy.ops.wm.open_mainfile(filepath=str(out/'observation-deck-bake.blend'))
        objects=[obj for obj in bpy.context.scene.objects if obj.type=='MESH']
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        spec=importlib.util.spec_from_file_location('ship_interior',interior_path)
        source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
        rear=float(getattr(source,'REAR',rear))
        objects=source.build_interior()
        source.build_lights()
    scene=bpy.context.scene
    configure_cycles(scene,args.samples)
    apply_gains(scene,params)
    shield=sync_shield(scene,params['rear_shield'])
    if args.resume or relight is not None:
        objects=[obj for obj in scene.objects if obj.type=='MESH']
    setup_world(scene,params)
    world_test=world_self_tests(scene,params,out)
    if not args.resume and relight is None:
        bpy.ops.object.camera_add(location=EYE_B)
        camera=bpy.context.object;camera.name='Seated reference';camera.data.lens=23
        camera.rotation_euler=(Vector((0,6,2.1))-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.camera=camera
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'observation-deck-source.blend'))
    if args.only_build:
        print('SHIP_SOURCE_READY',flush=True);return
    if args.resume or relight is not None:
        glow_data=json.loads((out/'glows.json').read_text())
    else:
        glows,counts=collect_glows(objects)
        expected=None
        if source is not None and hasattr(source,'summary'):
            try: expected=source.summary().get('glows')
            except Exception as exc: print('SHIP_GLOW_SUMMARY_UNAVAILABLE',exc,flush=True)
        glow_data={'schema':1,'space':'Godot room (x right, y up, -z forward)','counts':counts,'cli_counts':expected,'glows':glows}
        (out/'glows.json').write_text(json.dumps(glow_data,indent=1))
    glows=glow_data['glows']
    counts=glow_data.get('counts',{})
    assert len(glows)<=120, 'More than 120 glows: %d'%len(glows)
    assert len(glows)==int(counts.get('amber',0))+int(counts.get('blue',0)), 'Glow manifest count differs from amber + blue counts'
    if glow_data.get('cli_counts'):
        cli=glow_data['cli_counts']
        assert len(glows)==int(cli.get('amber',0))+int(cli.get('blue',0)), 'Glow manifest count differs from the authoring CLI counts'
    groups=bake_groups(objects)
    merged=[]
    prep={}
    if args.resume or relight is not None:
        for name,members in groups.items():
            assert len(members)==1, 'Resume expects one joined mesh per bake group'
            merged.append(members[0])
        if (out/'prep.json').exists():
            prep=json.loads((out/'prep.json').read_text())
    else:
        shape_state={'method':'CONCAVE'}
        for name,members in groups.items():
            light_res,_=resolutions(name,args.quick)
            obj,info=join_group(name,members,rear,light_res,shape_state)
            prep[name]=info
            merged.append(obj)
        prep['_rear']=rear
        (out/'prep.json').write_text(json.dumps(prep,indent=2))
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'observation-deck-bake.blend'))
    previous={}
    if relight is not None:
        previous=json.loads((out/'starship.json').read_text())
    manifest={'schema':1,'name':'Observation Deck','revision':REVISION,'source_eye_height_m':1.65,'floor_height_m':FLOOR,
              'source_sha256':previous.get('source_sha256') if relight is not None else hashlib.sha256(interior_path.read_bytes()).hexdigest(),
              'samples':args.samples,'albedo_samples':ALBEDO_SAMPLES,'quick':bool(args.quick) if relight is None else previous.get('quick',False),
              'parts':[]}
    old_parts={p['name']:p for p in previous.get('parts',[])}
    timings={}
    for obj in merged:
        name=obj.name
        if relight is not None:
            metadata=dict(old_parts[name])
            light_res=int(metadata['resolution'])
        else:
            light_res,albedo_res=resolutions(name,args.quick)
            metadata=export_mesh(obj,out/(name+'.bin'))
            metadata.update(name=name,resolution=light_res,albedo_resolution=albedo_res)
            for key in ('culled_m2','culled_faces','culled_by_rule_m2','texels_per_m','uv_coverage','uv_pack_margin','uv_shape_method','uv_pack_seconds'):
                if key in prep.get(name,{}): metadata[key]=prep[name][key]
            if 'texels_per_m' in prep.get(name,{}):
                metadata['albedo_texels_per_m']=round(prep[name]['texels_per_m']*albedo_res/light_res,1)
        kinds=['lighting'] if relight is not None else ['lighting','albedo']
        for kind in kinds:
            target=out/(name+'-'+kind+'.exr')
            size=light_res if kind=='lighting' else metadata['albedo_resolution']
            if not args.resume or not target.exists():
                t0=time.monotonic()
                restore=group_gain_lights(scene,name,params['group_gains']) if kind=='lighting' else []
                try:
                    bake(scene,obj,kind,target,size,args.samples)
                finally:
                    for light,energy in restore: light.data.energy=energy
                timings[name+'-'+kind]=round(time.monotonic()-t0,1)
        manifest['parts'].append(metadata)
    deck=next((o for o in merged if o.name=='deck'),None)
    mirror_info=bake_mirror(scene,out,deck,params['mirror'],glows)
    wear_info=wear_map(out/'deck-wear.exr')
    manifest['triangles']=sum(p['triangles'] for p in manifest['parts'])
    manifest['vertices']=sum(p['vertices'] for p in manifest['parts'])
    manifest['glows']=[{k:g[k] for k in ('name','c','n','u','size','kind') if k in g} for g in glows]
    manifest['glow_counts']=counts
    manifest['deck_top']=.480
    manifest['mirror']={'eye':[0.0,-0.69,0.0],'lat_min_deg':MIRROR_LAT_MIN,'lat_max_deg':MIRROR_LAT_MAX,'pad_px':MIRROR_PAD,
                        'width_px':MIRROR_W,'height_px':MIRROR_H,'u_sign':mirror_info['u_sign'],
                        'prefilter':params['mirror'],
                        'samples':MIRROR_SAMPLES,'denoise':'OIDN'}
    manifest['sky']={'planet_direction':PLANET_DIRECTION,'planet_distance':PLANET_DISTANCE,'sun':SUN_DIRECTION,'twilight_fade_deg':list(TWILIGHT_FADE_DEG)}
    manifest['extras']=[{'name':'deck-mirror','format':'RGBH'},{'name':'deck-wear','format':'RGB8'}]
    manifest['runtime']=runtime
    manifest['bake_params']=dict(params,samples=args.samples,albedo_samples=ALBEDO_SAMPLES,rear_shield=bool(shield),
                                 params_file=params_file,relit_from=rel_root(relight) if relight is not None else None,
                                 world={'size':[2048,1024],'sampling':'MANUAL','sample_map_resolution':1024,'self_test':world_test},
                                 wear=wear_info,interior=interior_label(interior_path) if relight is None else previous.get('bake_params',{}).get('interior'))
    manifest['timings']=dict(timings,mirror=mirror_info['seconds'],total=round(time.monotonic()-started_all,1))
    (out/'starship.json').write_text(json.dumps(manifest,indent=2))
    log('SHIP_TIMING',manifest['timings'])
    print('SHIP_RUNTIME_READY '+json.dumps({k:v for k,v in manifest.items() if k not in ('glows',)}),flush=True)

if __name__=='__main__': main()
