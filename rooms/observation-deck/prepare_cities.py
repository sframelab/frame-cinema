"""Build the Observation Deck's city lights (cities.dat): real night light, traced into chains of points.

Run with the workspace venv (NumPy and Pillow). The NASA files are untrusted data: run this with python -I from another
folder, it only decodes images and reads numbers.
    python -I prepare_cities.py [--tiles <dir>] [--source <dir>] [--shader <space.gdshader>] [--output <dir>] [--cache <dir>] [--receipt <file>]

A stretched map smears every light along the limb. This draws each one as a small additive quad, as the stars are, placed on
the ground. Where they go comes from the data:
- Ridge lines of the 500 m Black Marble gray tiles at two widths (roads and coasts in the faint light, arterial spokes inside
  a metro in the squared light), so a road reads as a chain in any direction. Plain local maxima make polka dots.
- Beads go down those lines best first (a long clear line for a road, a clear artery in a metro), and nothing lands within a
  set distance of an earlier bead, so spacing along a line is as irregular as the towns on it. Nothing random is added.
- The gray tile saturates, so a light's rank is the light integrated around it, not its own value: one hot core per metro,
  bright beads on the chains that lead out of it, and a long way down to the faint specks.
- A longitude with no tile uses the 3 km map, its levels matched to the tiles by quantile. Add a tile to TILES by name and it
  takes over from the 3 km map there.

Output cities.dat, read by starship_room.gd city_mesh_file(): u32 magic 'CITY', u32 vertex count, u32 index count, vec3 float32
position x vertices, RGBA8 x vertices, int32 x indices. Each light is one quad of four vertices that all hold (belt u, belt v, 0),
the same u and v the map uses; cities.gdshader turns that into a direction with the ground's spin and spreads the corners
by VERTEX_ID. RGB is the light's tint, A its amplitude, ln(amp / AMP_MIN) / ln(AMP_MAX / AMP_MIN).
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != HERE]

import numpy as np
from PIL import Image

WORKSPACE = HERE.parents[1]
SHADER = WORKSPACE / 'app/starship/space.gdshader'
MAGIC = 0x59544943  # 'CITY'

# Gray 500 m tiles, 21600 x 21600 of 90 x 90 deg. West longitude, north latitude, bytes, sha256. A new tile goes here by name;
# one that is not on disk is skipped, and the 3 km map stands in for it.
TILE_PIXELS, TILE_DEGREES = 21600, 90.0
TILES = {
    'BlackMarble_2016_A1_gray.jpg': (-180.0, 90.0, 5906921, '4e5a1135eb97ffa17067128f278d329ccf8d8819f469c9c4a40ffda7b77c809b'),
    'BlackMarble_2016_B1_gray.jpg': (-90.0, 90.0, 8388924, '19a3e114e0a3970577813ff54e81e60fe5f32b6c38148468625a8a02f594a33c'),
}
COARSE_MAP = ('BlackMarble_2016_3km.jpg', '230aac448ae68c358be433dd518888cccb3a85ccf66f7b44326441c324ad6725')
# Basemap level of the 3 km colour map, removed from max(R, G) (prepare_earth.py FALLBACK_BASEMAP).
COARSE_BASEMAP = 0.02

# What the glass can show at this orbit: with the room's frames, 588 head poses and both eyes, no pixel north of 41. The margin is for leaning.
LATITUDES = (-2.0, 47.0)
# Source pixels per working cell (about 926 m), and the coarse world grid the integrated light is read from (1/30 deg, 3.7 km).
CELL = 2
GRID_PER_DEGREE = 30
# Ridge passes: name, field, sigma in cells, least strength, least level of the cell (0-255). "spokes" are a metro's arteries,
# found in the squared light; "web" the finer lines in the same light; "roads" the faint lines in a log of the light.
PASSES = (('spokes', 'square', 3.0, 0.02, 120.0),
          ('web', 'square', 1.5, 0.02, 60.0),
          ('roads', 'log', 1.5, 0.03, 14.0))
# Long lines: length each way in 1.85 km cells (about 22 km), and directions tried (even, so each has a perpendicular).
CORRIDOR_CELLS, CORRIDOR_ANGLES = 12, 12
# The same on the squared light, shorter (about 11 km): an artery inside a metro, against the sprawl beside it.
ARTERY_CELLS = 6
# A ridge cell must be longer than it is wide, or a lone blob grows a star of false lines: least (|low| - |high|) / |low|.
RIDGE_ANISOTROPY = 0.3
# Specks: local maxima of the log field above this level (0-255), for towns on no line.
SPECK_LEVEL = 18.0
# How many quads, by when a longitude first reaches the glass: (west, east, quads). The first two hours of a film are over the
# Americas, so they get most of them. Room total is 118,744 triangles against a 150,000 limit: 31,256 free, so at most 15,628 quads.
BUDGET = ((-140.0, -55.0, 9800), (-55.0, 0.0, 1300), (None, None, 4400))
MAX_QUADS = 15600
# Share of a band's quads each pass may lay, in the order they are laid; what a pass leaves goes to the next. Hubs come first and count against the band.
PASS_SHARE = {'spokes': 0.18, 'web': 0.04, 'roads': 0.70, 'specks': 0.08}
# Hubs: maxima of the light within GRID sigma 3 (11 km), at least this far apart and this bright. Each gets one hot core.
HUB_APART_KM, HUB_FLOOR = 45.0, 0.30
# Least distance between beads in km, by pass, for the brightest light and the faintest.
SPACING_KM = {'spokes': (5.5, 7.0), 'web': (8.0, 11.0), 'roads': (4.5, 6.0), 'specks': (18.0, 24.0)}
# Amplitude: linear radiance of a light's kernel peak before tone map at earth_gain 1, by the light around it (geometric mean of 3.7 and 11 km,
# level^2). A map's full-scale texel in red is 1.6 (space.gdshader CITY_PEAK). AMP_MIN and AMP_MAX code the RGBA8 alpha, shared with cities.gdshader.
AMP_MIN, AMP_MAX = 0.004, 2.0
AMP_TABLE = ((0.003, 0.025), (0.02, 0.055), (0.10, 0.13), (0.30, 0.24), (0.60, 0.40), (0.90, 0.80))
# A town on a road stands out of the road: amplitude also goes as this power of the light in 3.7 km against 11 km.
AMP_LOCAL = 0.6
# And a bead on a clear line outshines one off it: a factor of the corridor or artery score over these, within these limits.
ROAD_REF, ARTERY_REF = 0.25, 0.10
ON_LINE = (0.3, 2.0)
# A bead off the strong lines stays in the faint tier, leveling off toward this, so the eye follows the chains. A speck always does.
STRONG_LINE, FAINT_TOP = 1.1, 0.155
# Strong beads closer than this are one chain, hubs included. A chain shorter than the next figure across drops to the faint tier: the eye should find lines, not dots.
CHAIN_REACH_KM, CHAIN_LEAST_KM = 13.0, 40.0
# A hub's core by the light of its whole metro (sigma 8 cells, 30 km).
HUB_AMP = ((0.02, 0.6), (0.06, 1.1), (0.15, 1.7), (0.40, 2.0))
# A small hub with no chain near it is a town: it keeps this share, up to all of it with this many strong beads within this many km, or with this much light in its metro.
HUB_LONE, HUB_BEADS, HUB_BEADS_KM, HUB_METRO = 0.35, 8, 30.0, 0.25
# Tint: amber, paling into the hot colour with amplitude. The spread follows the place: compact towns stay on sodium amber,
# wide metros lean paler, as LED conversions have in big cities. Nothing per light is random.
# The tone map pales them on the way: on screen the brightest beads' G/R is .80 in Focus and .82-.83 at gain 1, near the .78-.81 aimed for. Keep it in .78-.83.
AMBER = np.array([1.0, 0.486, 0.228])
HOT = np.array([1.0, 0.616, 0.36])
PALE_FROM, PALE_TO = 0.03, 0.6
SPREAD = 0.5


def shader_float(source, name):
    match = re.search(r'const\s+float\s+' + name + r'\s*=\s*([-0-9.eE+]+)', source)
    assert match, 'space.gdshader has no ' + name
    return float(match.group(1))


def blur(field, sigma):
    """Separable Gaussian, edge padded, sigma in cells (prepare_earth.py)."""
    radius = max(1, int(math.ceil(3 * sigma)))
    taps = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2).astype(np.float32)
    taps /= taps.sum()
    pad = np.pad(field, radius, mode='edge')
    rows = sum(w * pad[:, i:i + field.shape[1]] for i, w in enumerate(taps))
    return sum(w * rows[i:i + field.shape[0], :] for i, w in enumerate(taps))


def ridges(field, sigma):
    """Cells on a ridge line of the field at this width: strength (sigma^2 x the curvature across the line) where it is the
    largest across the line, and how much longer than wide the ridge is. Both 0 elsewhere."""
    g = blur(field, sigma)
    gxx = g[1:-1, 2:] - 2 * g[1:-1, 1:-1] + g[1:-1, :-2]
    gyy = g[2:, 1:-1] - 2 * g[1:-1, 1:-1] + g[:-2, 1:-1]
    gxy = (g[2:, 2:] - g[2:, :-2] - g[:-2, 2:] + g[:-2, :-2]) / 4
    del g
    half = (gxx + gyy) / 2
    root = np.sqrt(((gxx - gyy) / 2) ** 2 + gxy ** 2)
    low = half - root
    high = half + root
    strength = np.maximum(-low, 0) * sigma * sigma
    across = np.rint(np.mod(np.arctan2(gxy, low - gyy), np.pi) / (np.pi / 4)).astype(np.int8) % 4
    del gxx, gyy, gxy, half, root
    pad = np.pad(strength, 1)
    h, w = strength.shape
    top = np.zeros_like(strength, bool)
    for k, (dy, dx) in enumerate(((0, 1), (1, 1), (1, 0), (1, -1))):
        top |= (across == k) & (strength >= pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]) & (strength >= pad[1 - dy:1 - dy + h, 1 - dx:1 - dx + w])
    long_ways = (np.abs(low) - np.abs(high)) / np.maximum(np.abs(low), 1e-6)
    return np.pad(strength * top, 1), np.pad(long_ways, 1)


def corridor(field, length, angles=CORRIDOR_ANGLES):
    """How much a cell sits on a long line of light. Along each direction, the mean of the field over `length` cells on each side: the
    weaker side counts, less the stronger side of the perpendicular. A town alone scores low (dark along), a metro's inside low (bright
    across), a road or a chain of towns high, gaps and all (prepare_earth.py line_evidence is the same idea without the second term)."""
    h, w = field.shape
    pad = np.pad(field, length + 1)
    lit, wide = [], []
    for k in range(angles):
        angle = math.pi * k / angles
        dx, dy = math.cos(angle), math.sin(angle)
        ahead, behind = np.zeros_like(field), np.zeros_like(field)
        for step in range(1, length + 1):
            ox, oy = int(round(dx * step)), int(round(dy * step))
            ahead += pad[length + 1 + oy:length + 1 + oy + h, length + 1 + ox:length + 1 + ox + w]
            behind += pad[length + 1 - oy:length + 1 - oy + h, length + 1 - ox:length + 1 - ox + w]
        lit.append(np.minimum(ahead, behind) / length)
        wide.append(np.maximum(ahead, behind) / length)
    best = np.zeros_like(field)
    for k in range(angles):
        best = np.maximum(best, lit[k] - wide[(k + angles // 2) % angles])
    return best


def read_tiles(folder):
    """Each tile on disk that matches its pin, as cell-mean levels (float32, 0-255) in the belt's latitudes. Returns {name: (west, levels)}."""
    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = TILE_PIXELS * TILE_PIXELS + 1
    tiles = {}
    per = TILE_PIXELS / TILE_DEGREES
    for name, (west, north, size, digest) in TILES.items():
        path = folder / name
        if not path.exists():
            print('CITIES_TILE_MISSING', name, flush=True)
            continue
        data = path.read_bytes()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest, 'Tile differs from its pin: %s' % path
        with Image.open(path) as opened:
            full = np.asarray(opened.convert('L'))
        rows = (max(0, int((north - LATITUDES[1]) * per)), min(TILE_PIXELS, int((north - max(LATITUDES[0], north - TILE_DEGREES)) * per)))
        rows = (rows[0] - rows[0] % CELL, rows[1] - rows[1] % CELL)
        part = full[rows[0]:rows[1]]
        levels = part.reshape(part.shape[0] // CELL, CELL, part.shape[1] // CELL, CELL).astype(np.float32).mean(axis=(1, 3))
        tiles[name] = (west, north - rows[0] / per, levels)
        del full, part
    Image.MAX_IMAGE_PIXELS = limit
    return tiles


def tile_candidates(name, tiles, cache):
    """Ridge cells and specks of one tile, cached: lat, lon, pass index, level, ridge strength, corridor and artery scores."""
    path = cache / (name + '.candidates3.npz')
    if path.exists():
        data = np.load(path)
        return {k: data[k] for k in data.files}
    west, north, levels = tiles[name]
    # A strip of the neighbour on each side, so a line that crosses the tile's edge is seen whole.
    pad = 64
    left = right = None
    for other, (w2, n2, lv) in tiles.items():
        if n2 == north and lv.shape == levels.shape:
            if w2 == west - TILE_DEGREES:
                left = lv[:, -pad:]
            if w2 == west + TILE_DEGREES:
                right = lv[:, :pad]
    block = np.concatenate([left if left is not None else np.zeros((levels.shape[0], pad), np.float32), levels,
                            right if right is not None else np.zeros((levels.shape[0], pad), np.float32)], axis=1)
    fields = {'square': (block / 255) ** 2, 'log': np.log1p(block / 8) / math.log1p(255 / 8)}
    per = TILE_PIXELS / TILE_DEGREES / CELL
    out = {k: [] for k in ('lat', 'lon', 'kind', 'level', 'strength', 'corridor', 'artery')}
    h2, w2 = block.shape[0] // 2, block.shape[1] // 2
    halved = (block[:h2 * 2, :w2 * 2] / 255).reshape(h2, 2, w2, 2).mean(axis=(1, 3))
    lines = corridor(halved, CORRIDOR_CELLS)
    arteries = corridor(halved ** 2, ARTERY_CELLS)
    print('CITIES_CORRIDOR', name, flush=True)

    def keep(ys, xs, kind, strength):
        inside = (xs >= pad) & (xs < pad + levels.shape[1])
        ys, xs, strength = ys[inside], xs[inside], strength[inside]
        out['lat'].append(north - (ys + .5) / per)
        out['lon'].append(west + (xs - pad + .5) / per)
        out['kind'].append(np.full(len(ys), kind, np.int8))
        out['level'].append(block[ys, xs])
        out['strength'].append(strength.astype(np.float32))
        out['corridor'].append(lines[np.minimum(ys // 2, h2 - 1), np.minimum(xs // 2, w2 - 1)])
        out['artery'].append(arteries[np.minimum(ys // 2, h2 - 1), np.minimum(xs // 2, w2 - 1)])

    for kind, (label, which, sigma, floor, least) in enumerate(PASSES):
        strength, long_ways = ridges(fields[which], sigma)
        ys, xs = np.nonzero((strength > floor) & (block > least) & (long_ways > RIDGE_ANISOTROPY))
        keep(ys, xs, kind, strength[ys, xs])
        del strength, long_ways
        print('CITIES_PASS', name, label, len(ys), flush=True)
    soft = blur(fields['log'], 1.0)
    window = np.lib.stride_tricks.sliding_window_view(np.pad(soft, 1, mode='edge'), (3, 3)).max(axis=(2, 3))
    ys, xs = np.nonzero((soft >= window) & (block > SPECK_LEVEL))
    keep(ys, xs, len(PASSES), soft[ys, xs])
    print('CITIES_SPECKS', name, len(ys), flush=True)
    result = {k: np.concatenate(v) for k, v in out.items()}
    np.savez(path, **result)
    return result


def coarse_light(source):
    """The 3 km map as light (0-1): basemap off, as prepare_earth.py belt_fallback, on its own grid with its pixel size."""
    name, digest = COARSE_MAP
    path = source / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Source differs from its pin: %s' % path
    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 100_000_000
    with Image.open(path) as opened:
        rgb = np.asarray(opened.convert('RGB'), dtype=np.float32) / 255
    Image.MAX_IMAGE_PIXELS = limit
    return np.clip((np.maximum(rgb[..., 0], rgb[..., 1]) - COARSE_BASEMAP) / (1 - COARSE_BASEMAP), 0, 1)


def world_grid(tiles, coarse):
    """Light per grid cell on the belt's latitudes, (level / 255)^2 from the tiles, and from the 3 km map, matched by quantile, where no tile is."""
    per = GRID_PER_DEGREE
    rows = int((LATITUDES[1] - LATITUDES[0]) * per)
    width = 360 * per
    grid = np.zeros((rows, width), np.float32)
    known = np.zeros((rows, width), bool)
    for name, (west, north, levels) in tiles.items():
        step = int(TILE_PIXELS / TILE_DEGREES / CELL / per)
        top = int(round((LATITUDES[1] - north) * per))
        left = int(round((west + 180.0) * per))
        h, w = levels.shape[0] // step, levels.shape[1] // step
        part = ((levels[:h * step, :w * step] / 255) ** 2).reshape(h, step, w, step).mean(axis=(1, 3))
        grid[top:top + h, left:left + w] = part
        known[top:top + h, left:left + w] = True
    # The 3 km map on the same grid, nearest cell; it is finer than the grid by only 1.25x.
    h3, w3 = coarse.shape
    lat = LATITUDES[1] - (np.arange(rows) + .5) / per
    lon = -180.0 + (np.arange(width) + .5) / per
    y3 = np.clip(((90.0 - lat) / 180.0 * h3).astype(int), 0, h3 - 1)
    x3 = np.clip(((lon + 180.0) / 360.0 * w3).astype(int), 0, w3 - 1)
    stand_in = coarse[y3][:, x3] ** 2
    lit = stand_in[known] > 1e-4
    ranks = np.linspace(0.0, 1.0, 513)
    src = np.maximum.accumulate(np.quantile(stand_in[known][lit], ranks) + np.arange(513) * 1e-9)
    grid[~known] = np.interp(stand_in[~known], src, np.quantile(grid[known][lit], ranks))
    return grid, known


def coarse_candidates(coarse, known):
    """Ridge cells of the 3 km map where no tile is, as the roads pass. Same record as tile_candidates."""
    h3, w3 = coarse.shape
    top, bottom = int((90.0 - LATITUDES[1]) / 180.0 * h3), int((90.0 - LATITUDES[0]) / 180.0 * h3)
    light = coarse[top:bottom]
    field = np.log1p(light * 32) / math.log1p(32)
    strength, long_ways = ridges(field, 1.0)
    lines = corridor(light, CORRIDOR_CELLS * 5 // 8)
    ys, xs = np.nonzero((strength > 0.015) & (light > 0.06) & (long_ways > RIDGE_ANISOTROPY))
    per3 = h3 / 180.0
    lat = 90.0 - (ys + top + .5) / per3
    lon = -180.0 + (xs + .5) / per3
    gy = np.clip(((LATITUDES[1] - lat) * GRID_PER_DEGREE).astype(int), 0, known.shape[0] - 1)
    gx = np.clip(((lon + 180.0) * GRID_PER_DEGREE).astype(int), 0, known.shape[1] - 1)
    away = ~known[gy, gx]
    roads = {'lat': lat[away], 'lon': lon[away], 'kind': np.full(int(away.sum()), 2, np.int8), 'level': light[ys, xs][away] * 255,
             'strength': strength[ys, xs][away], 'corridor': lines[ys, xs][away], 'artery': np.zeros(int(away.sum()), np.float32)}
    window = np.lib.stride_tricks.sliding_window_view(np.pad(field, 1, mode='edge'), (3, 3)).max(axis=(2, 3))
    ys, xs = np.nonzero((field >= window) & (light > 0.12))
    lat, lon = 90.0 - (ys + top + .5) / per3, -180.0 + (xs + .5) / per3
    gy = np.clip(((LATITUDES[1] - lat) * GRID_PER_DEGREE).astype(int), 0, known.shape[0] - 1)
    gx = np.clip(((lon + 180.0) * GRID_PER_DEGREE).astype(int), 0, known.shape[1] - 1)
    away = ~known[gy, gx]
    specks = {'lat': lat[away], 'lon': lon[away], 'kind': np.full(int(away.sum()), len(PASSES), np.int8), 'level': light[ys, xs][away] * 255,
              'strength': field[ys, xs][away], 'corridor': lines[ys, xs][away], 'artery': np.zeros(int(away.sum()), np.float32)}
    return {k: np.concatenate([roads[k], specks[k]]) for k in roads}


def sample(grid, lat, lon):
    """Bilinear on the world grid; longitude wraps."""
    y = np.clip((LATITUDES[1] - lat) * GRID_PER_DEGREE - .5, 0, grid.shape[0] - 1.001)
    x = (lon + 180.0) * GRID_PER_DEGREE - .5
    y0, x0 = y.astype(int), np.floor(x).astype(int)
    fy, fx = y - y0, x - x0
    x0, x1 = x0 % grid.shape[1], (x0 + 1) % grid.shape[1]
    return (grid[y0, x0] * (1 - fx) * (1 - fy) + grid[y0, x1] * fx * (1 - fy)
            + grid[y0 + 1, x0] * (1 - fx) * fy + grid[y0 + 1, x1] * fx * fy)


def hubs_of(wide):
    """One core per metro: maxima of the light in 11 km that nothing brighter holds within HUB_APART_KM."""
    r = 2
    window = np.lib.stride_tricks.sliding_window_view(np.pad(wide, r, mode='edge'), (2 * r + 1, 2 * r + 1)).max(axis=(2, 3))
    ys, xs = np.nonzero((wide >= window) & (wide > HUB_FLOOR))
    order = np.argsort(-wide[ys, xs])
    lat = LATITUDES[1] - (ys[order] + .5) / GRID_PER_DEGREE
    lon = -180.0 + (xs[order] + .5) / GRID_PER_DEGREE
    keep = []
    for i in range(len(order)):
        dy = (lat[keep] - lat[i]) * 111.19
        dx = ((lon[keep] - lon[i] + 180.0) % 360.0 - 180.0) * 111.19 * math.cos(math.radians(lat[i]))
        if not keep or (dx * dx + dy * dy).min() > HUB_APART_KM ** 2:
            keep.append(i)
    return lat[keep], lon[keep]


def lay_beads(records, wants, taken_lat, taken_lon, shares):
    """Beads pass by pass, brightest first in each, none within the set distance of one already laid. wants: [(west, east, quads)], the last
    the rest of the world. Cutting the budget only drops the faintest of a pass, so the brighter ones do not move."""
    cell_deg = 0.2
    grid = {}
    for la, lo in zip(taken_lat, taken_lon):
        grid.setdefault((int(la // cell_deg), int(lo // cell_deg)), []).append((la, lo))
    chosen = []
    spare = [0] * len(wants)
    bands = np.full(len(records['lat']), len(wants) - 1)
    for k, (west, east, _) in enumerate(wants[:-1]):
        bands[(records['lon'] >= west) & (records['lon'] < east)] = k
    for kind, share in enumerate(shares):
        for band, want in enumerate(wants):
            left = int(want[2] * share) + spare[band]
            here = np.nonzero((records['kind'] == kind) & (bands == band))[0]
            order = here[np.argsort(-records['priority'][here])]
            lat, lon, spacing = records['lat'][order], records['lon'][order], records['spacing'][order]
            cos_lat = np.cos(np.radians(lat))
            for i in range(len(order)):
                if left <= 0:
                    break
                la, lo = lat[i], lon[i]
                cy, cx = int(la // cell_deg), int(lo // cell_deg)
                r2 = spacing[i] * spacing[i]
                reach_y = int(spacing[i] / (111.19 * cell_deg)) + 1
                reach_x = int(spacing[i] / (111.19 * cell_deg * max(cos_lat[i], .3))) + 1
                clear = True
                for gy in range(cy - reach_y, cy + reach_y + 1):
                    for gx in range(cx - reach_x, cx + reach_x + 1):
                        for la2, lo2 in grid.get((gy, gx), ()):
                            dy = (la2 - la) * 111.19
                            dx = (lo2 - lo) * 111.19 * cos_lat[i]
                            if dx * dx + dy * dy < r2:
                                clear = False
                                break
                        if not clear:
                            break
                    if not clear:
                        break
                if clear:
                    grid.setdefault((cy, cx), []).append((la, lo))
                    chosen.append(order[i])
                    left -= 1
            spare[band] = left
    return np.array(chosen)


def chain_extent(lat, lon, reach_km):
    """Points closer than reach_km are one chain: the km across each point's chain, corner to corner."""
    cell_deg = reach_km / 60.0
    grid = {}
    for i, (la, lo) in enumerate(zip(lat, lon)):
        grid.setdefault((int(la // cell_deg), int(lo // cell_deg)), []).append(i)
    parent = list(range(len(lat)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    r2 = reach_km * reach_km
    for i, (la, lo) in enumerate(zip(lat, lon)):
        cos_lat = math.cos(math.radians(la))
        cy, cx = int(la // cell_deg), int(lo // cell_deg)
        for gy in range(cy - 2, cy + 3):
            for gx in range(cx - 2, cx + 3):
                for j in grid.get((gy, gx), ()):
                    if j > i and ((lat[j] - la) * 111.19) ** 2 + ((lon[j] - lo) * 111.19 * cos_lat) ** 2 < r2:
                        parent[root(j)] = root(i)
    labels = np.array([root(i) for i in range(len(lat))]) if len(lat) else np.zeros(0, int)
    extent = np.zeros(len(lat))
    for label in np.unique(labels):
        at = np.nonzero(labels == label)[0]
        dy = np.ptp(lat[at]) * 111.19
        dx = np.ptp(lon[at]) * 111.19 * math.cos(math.radians(lat[at[0]]))
        extent[at] = math.hypot(dx, dy)
    return extent


def write_mesh(path, u, v, amp, tint):
    count = len(u)
    assert count <= MAX_QUADS, 'Too many lights: %d' % count
    code = np.round(np.log(np.clip(amp, AMP_MIN, AMP_MAX) / AMP_MIN) / math.log(AMP_MAX / AMP_MIN) * 255.0)
    colour = np.empty((count, 4), np.uint8)
    colour[:, :3] = np.round(np.clip(tint, 0.0, 1.0) * 255.0)
    colour[:, 3] = code
    position = np.stack([u, v, np.zeros(count)], axis=1).astype('<f4')
    index = np.arange(count, dtype=np.int32)[:, None] * 4 + np.array([0, 1, 2, 0, 2, 3], np.int32)
    with open(path, 'wb') as out:
        out.write(struct.pack('<III', MAGIC, count * 4, count * 6))
        out.write(np.repeat(position, 4, axis=0).tobytes())
        out.write(np.repeat(colour, 4, axis=0).tobytes())
        out.write(index.astype('<i4').tobytes())


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tiles', type=Path, default=WORKSPACE / '.local/earth-nasa-500m')
    parser.add_argument('--source', type=Path, default=WORKSPACE / '.local/earth-nasa')
    parser.add_argument('--shader', type=Path, default=SHADER)
    parser.add_argument('--output', type=Path, default=HERE.parents[1] / 'app/starship')
    parser.add_argument('--cache', type=Path, default=WORKSPACE / '.local/starship-cities')
    parser.add_argument('--receipt', type=Path, help='Where to write cities-preparation.json (default: next to the cache, so it never ships)')
    args = parser.parse_args()
    source = args.shader.read_text()
    belt_top, belt_scale = shader_float(source, 'BELT_TOP'), shader_float(source, 'BELT_SCALE')
    args.cache.mkdir(parents=True, exist_ok=True)
    tiles = read_tiles(args.tiles)
    coarse = coarse_light(args.source)
    grid, known = world_grid(tiles, coarse)
    records = [tile_candidates(name, tiles, args.cache) for name in tiles]
    records.append(coarse_candidates(coarse, known))
    tile_names = {name: TILES[name][:2] for name in tiles}
    del tiles, coarse
    all_records = {k: np.concatenate([r[k] for r in records]) for k in records[0]}
    keep = (all_records['lat'] > LATITUDES[0]) & (all_records['lat'] < LATITUDES[1])
    r = {k: v[keep] for k, v in all_records.items()}
    near = blur(grid, 1.0)
    wide = blur(grid, 3.0)
    metro = blur(grid, 8.0)
    r_near, r_wide, r_metro = sample(near, r['lat'], r['lon']), sample(wide, r['lat'], r['lon']), sample(metro, r['lat'], r['lon'])
    around = np.sqrt(np.maximum(r_near * r_wide, 1e-7))

    names = [p[0] for p in PASSES] + ['specks']
    # Which beads a pass lays first: spokes by how strong the artery is, roads by how long a line they sit on, the rest by the light around them.
    r['priority'] = np.where(r['kind'] == 0, np.log(np.maximum(r['artery'], 1e-4)) + .5 * np.log(around),
                             np.where(r['kind'] == 2, np.log(np.maximum(r['corridor'], 1e-3)) + .3 * np.log(around), np.log(around)))
    closest = np.array([SPACING_KM[n][0] for n in names])[r['kind']]
    farthest = np.array([SPACING_KM[n][1] for n in names])[r['kind']]
    fade = np.clip(np.log(around / AMP_TABLE[0][0]) / math.log(AMP_TABLE[-1][0] / AMP_TABLE[0][0]), 0, 1)
    r['spacing'] = farthest + (closest - farthest) * fade

    hub_lat, hub_lon = hubs_of(wide)
    wants = [list(b) for b in BUDGET]
    for k, (west, east, _) in enumerate(wants[:-1]):
        wants[k][2] -= int(((hub_lon >= west) & (hub_lon < east)).sum())
    wants[-1][2] -= int(sum(1 for lo in hub_lon if not any(w <= lo < e for w, e, _ in wants[:-1])))
    assert sum(b[2] for b in BUDGET) <= MAX_QUADS
    chosen = lay_beads(r, wants, hub_lat, hub_lon, [PASS_SHARE[n] for n in names])
    lat, lon, kind = r['lat'][chosen], r['lon'][chosen], r['kind'][chosen]
    around, metro_here = around[chosen], r_metro[chosen]
    local = r_near[chosen] / np.maximum(r_wide[chosen], 1e-5)
    on_line = np.where(kind == 2, r['corridor'][chosen] / ROAD_REF, r['artery'][chosen] / ARTERY_REF)

    table_x, table_y = np.log([t[0] for t in AMP_TABLE]), np.log([t[1] for t in AMP_TABLE])
    amp = np.exp(np.interp(np.log(around), table_x, table_y))
    amp *= np.clip(local, 0.3, 3.0) ** AMP_LOCAL
    amp = np.where(kind < len(PASSES), amp * np.clip(on_line, ON_LINE[0], ON_LINE[1]), amp)
    strong = (kind < len(PASSES)) & (on_line >= STRONG_LINE) & (amp > FAINT_TOP)
    joined = chain_extent(np.concatenate([lat[strong], hub_lat]), np.concatenate([lon[strong], hub_lon]), CHAIN_REACH_KM)
    strong[strong] = joined[:int(strong.sum())] >= CHAIN_LEAST_KM
    tiers = {'strong_beads': int(strong.sum()), 'faint_beads_and_specks': int((~strong).sum())}
    amp = np.where(strong, amp, amp / (1 + amp / FAINT_TOP))
    hub_metro = sample(metro, hub_lat, hub_lon)
    hub_amp = np.exp(np.interp(np.log(hub_metro), np.log([t[0] for t in HUB_AMP]), np.log([t[1] for t in HUB_AMP])))
    for i in range(len(hub_lat)):
        dy = (lat[strong] - hub_lat[i]) * 111.19
        dx = ((lon[strong] - hub_lon[i] + 180.0) % 360.0 - 180.0) * 111.19 * math.cos(math.radians(hub_lat[i]))
        near_hub = int((dx * dx + dy * dy < HUB_BEADS_KM ** 2).sum())
        hub_amp[i] *= HUB_LONE + (1 - HUB_LONE) * max(min(near_hub / HUB_BEADS, 1.0), min(hub_metro[i] / HUB_METRO, 1.0) ** 4)

    lat = np.concatenate([lat, hub_lat])
    lon = np.concatenate([lon, hub_lon])
    amp = np.concatenate([amp, hub_amp])
    metro_all = np.concatenate([metro_here, hub_metro])
    sprawl = np.clip(np.log(np.maximum(metro_all, 1e-4) / 1e-3) / math.log(300.0), 0, 1)
    pale = smoothstep(math.log(PALE_FROM), math.log(PALE_TO), np.log(amp))
    pale = np.clip(pale + SPREAD * (sprawl - .5) * (1 - pale), 0, 1)
    tint = AMBER[None, :] * (1 - pale[:, None]) + HOT[None, :] * pale[:, None]

    order = np.argsort(-amp)
    lat, lon, amp, tint = lat[order], lon[order], amp[order], tint[order]
    u = lon / 360.0 + .5
    v = (belt_top - np.sin(np.radians(lat))) * belt_scale
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / 'cities.dat'
    write_mesh(path, u, v, amp, tint)
    receipt = {'tiers': tiers, 'quads': len(u), 'triangles': len(u) * 2, 'bytes': path.stat().st_size, 'hubs': len(hub_lat), 'latitudes': list(LATITUDES),
               'tiles': {name: TILES[name][3] for name in tile_names}, 'coarse_map': COARSE_MAP[1],
               'by_pass': {n: int((kind == i).sum()) for i, n in enumerate(names)}, 'budget': [list(b) for b in BUDGET], 'amp_range': [float(amp.min()), float(amp.max())],
               'amp_p': {str(q): round(float(np.percentile(amp, q)), 4) for q in (5, 25, 50, 75, 95, 99)},
               'in_tiles': int(sum(((lon >= w) & (lon < w + TILE_DEGREES) & (lat >= n - TILE_DEGREES)).sum() for w, n in tile_names.values()))}
    (args.receipt or args.cache.parent / 'cities-preparation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('CITIES_OK ' + json.dumps(receipt))


if __name__ == '__main__':
    main()
