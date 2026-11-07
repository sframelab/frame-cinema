"""Prepare Observation Deck's Earth maps from pinned NASA source files.

Usage (from any directory):
    python prepare_earth.py [--belt] --output <intermediate-directory>
    python prepare_earth.py --cap --output <intermediate-directory>        (the fixed cap atlas shipped up to 0.5.11)
    python prepare_earth.py --equirect --output <intermediate-directory>   (legacy 2:1 maps)
    python prepare_earth.py --source <NASA-originals> --output <intermediate-directory>
    python prepare_earth.py --download-tiles   (fetches the night-light tiles that are missing, then checks them)

--belt (default) writes the maps of an Earth that turns: a wrapped-longitude band of latitude
BELT_LAT, rows linear in sin(lat) so the shader needs no asin. earth-surface.png 4096x1024,
earth-masks.png 8192x2048 (R city lights, G water), earth-clouds.png 8192x2048 (R clouds, G a
second cloud sample for the window ring). City lights go through the same city_lights recipe as
the cap, its filters joined across the wrap; where the 500 m tiles stop the 3 km map stands in
through a feather (see belt_fallback). The shader takes one longitude offset for the ground and
one for the clouds from the global uniform earth_spin; nothing is baked for one view.

--cap writes a 2048x2048 azimuthal cap atlas, radius 16 deg of surface angle,
centred on the sub-viewer surface normal n0 = (0.3954, 0.8290, 0.3954) in Godot room
space (x right, y up, -z forward). east = normalize(cross(up, n0)),
north = cross(n0, east); atlas row 0 is +north. Atlas pixel (a, b) in [-1, 1]
holds the surface point at surface angle rho from n0 along a*east + b*north, where
|(a, b)| = ln(1 + rho/rho0) / ln(1 + 16 deg/rho0) (rho0 = CAP_RHO0_DEG, a logarithmic
radius that spends texels where the views need them). That surface point shows the
geography GEO_SCALE * rho from the sub-viewer point along the same bearing (feature
scale), with the room tangent frame (east, north, n0) rotated onto the geographic frame
at the sub-viewer point (--sub-lat, --sub-lon, --heading = bearing of room north).
space.gdshader inverts exactly this mapping (see its cap UV). The cloud layer gets an
unsharp mask. City light comes from NASA's 500 m Black Marble 2016 tiles (grayscale set):
every lit source pixel lands in one atlas texel, weighted by its true area, and the
resulting statistics are tone-mapped so real roads, coasts and town chains stay about one
texel wide with a small hot core in each bright area (see city_lights). Nothing random is added.

Defaults: originals in <workspace>/.local/earth-nasa; 500 m tiles in
<workspace>/.local/earth-nasa-500m; intermediate PNGs in <workspace>/.local/starship-earth/maps.
FRAME_CINEMA_EARTH_SOURCE, FRAME_CINEMA_EARTH_TILES and FRAME_CINEMA_EARTH_INPUT can override
these defaults. Run pack_earth.gd next.
Requires Pillow and NumPy. Source imagery is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Keep the script folder off the import path. It used to hold inspect.py (now
# view_room.py), which shadowed the standard-library module numpy imports.
sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != HERE]

import numpy as np
from PIL import Image

WORKSPACE = HERE.parents[1]
SOURCES = {
    "world.200412.3x5400x2700.jpg": "3d38a8ecaceb1cdb51ced7f831e9ac18d261950049616feff6892efcae0dcc26",
    "BlackMarble_2016_3km.jpg": "230aac448ae68c358be433dd518888cccb3a85ccf66f7b44326441c324ad6725",
    "cloud_combined_8192.tif": "d137775d8966ab8d443fd5126dc6e7ad72072bc1ed50555c5818d221735daf0f",
}

# Night lights: Black Marble 2016, grayscale set, 21600x21600 tiles of 90 x 90 deg (15 arc seconds a pixel,
# about 460 m). A1 is 180W-90W and B1 is 90W-0, both 90N-0. They hold 99.6% or more of the rays down to 12 deg below
# the horizon for this sub-viewer and every alternate. The rest of the cap (south of the equator, east of 0) stays on
# the 3 km global map. The colour tiles are not used: subtracting their blue land tint (warm in derive_masks)
# flattens every city into a plateau with a dark hole where the source saturates to white.
TILE_BASE_URL = "https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144897/"
TILE_SIZE, TILE_DEGREES = 21600, 90.0
# file name: west longitude, north latitude, bytes, sha256
TILES = {
    "BlackMarble_2016_A1_gray.jpg": (-180.0, 90.0, 5906921, "4e5a1135eb97ffa17067128f278d329ccf8d8819f469c9c4a40ffda7b77c809b"),
    "BlackMarble_2016_B1_gray.jpg": (-90.0, 90.0, 8388924, "19a3e114e0a3970577813ff54e81e60fe5f32b6c38148468625a8a02f594a33c"),
}
TILE_CHUNK_ROWS = 512
# Basemap level of the 3 km colour map, removed from max(R, G) where the fallback is used.
FALLBACK_BASEMAP = 0.02
# The tiles and the 3 km map must agree on where the light is (atlas correlation after a 2-texel blur).
REGISTRATION_MIN = 0.85

# Shared constants (vision): Godot room space.
PLANET_DIRECTION = np.array([-0.3954, -0.8290, -0.3954])
PLANET_DISTANCE = 1.031
CAP_RADIUS_DEG = 16.0
CAP_SIZE = 2048
# Logarithmic radial atlas coordinate: atlas radius r = ln(1 + rho/RHO0) / ln(1 + R/RHO0) for
# surface angle rho from n0 (R = CAP_RADIUS_DEG). It gives the mid field (rho 3-10 deg, seen at
# grazing angles) 1.3-2x the tangential texels and the far field near the limb (radially
# over-resolved on screen) fewer radial texels, so atlas texels are closer to square on screen.
CAP_RHO0_DEG = 2.5
# Geographic scale: the atlas maps surface angle rho (from n0) to geographic angle
# GEO_SCALE * rho along the same bearing, so the Earth's features read GEO_SCALE times
# smaller than at the true 197 km altitude (an orbital-photo scale). The
# shader's cap UV does not depend on it (CAP_RADIUS_DEG is still the surface-angle radius).
GEO_SCALE = 3.0
# Sources are now minified (atlas texel about 5.2 km at GEO_SCALE 3 against 3-7.4 km source
# pixels), so each atlas texel averages SUPERSAMPLE^2 Catmull-Rom samples.
SUPERSAMPLE = 2
# Sub-viewer (lat, lon) and heading (geographic bearing of room north). The sub-viewer sits off the
# eastern seaboard and the view looks west, so geographic north is to the right. The hero window sees
# the Mississippi and Ohio valley town networks between broken moonlit cloud decks, the next pane left
# Atlanta and the Gulf coast to Houston, and the pane after it the Florida peninsula and Havana (chosen
# from a search over sub-viewer and heading for city strings in the hero window and the side panes,
# then from renders; 30N 74W h-60 keeps the old hero within about a degree but leaves the panes emptier).
SUB_VIEWER = (37.0, -69.0)
HEADING = -90.0
ALTERNATES = [(36.0, -69.0, -85.0), (30.0, -74.0, -60.0)]
CHUNK_ROWS = 256
# front_ref framing (preview.gd): 1672x941, focal 913.4, pitch +1.5 deg.
REF_FOCAL, REF_CENTER, REF_PITCH = 913.4, (836.0, 470.5), 1.5
VIEW_RECT = (100, 150, 460, 380)  # x0, y0, x1, y1 (exclusive)
VIEW_MIN_MAXIMA = 100
CITY_THRESHOLD = 0.35
# cloud_relief: unsharp amount and blur sigma (atlas texels). Final look pass: a gentler, finer
# unsharp mask (0.7 / 3.0 cut hard-edged white flakes out of the thin cloud).
CLOUD_SHARPEN, CLOUD_SIGMA = 0.5, 2.0
# Final look pass: the window ring (atlas radius 0.6-0.95, what the side and hero windows see) held
# only about 15% cloud after the shader ramp; a second, denser cloud sample (Southern Ocean storm
# track) is screen-blended in from atlas radius CLOUD_RING[0] to CLOUD_RING[1] (about 53% there).
# Its heading follows the hero window, which moved 17 deg round the limb when the Earth became one
# sphere at az -45, so the same cloud band still crosses it. It is a cloud sample, not the geography below.
CLOUD_SECOND = (-50.0, 60.0, -17.0)
CLOUD_RING = (0.50, 0.65)
# city_lights (see that function). On screen an atlas texel is about 1.1 px radially and 2.3 px tangentially in the
# hero window, so a one-texel road reads 1-3 px wide. Local contrast: blur sigma (texels) and the floor that keeps dark land
# from dividing by nothing. Line evidence: length (texels each way), directions, the statistic's ceiling, its ramp, and how
# much of its light a town without any line through it keeps. Region: blur sigma, ramp, floor. Threads: gain and soft floor.
CITY_CONTRAST_SIGMA, CITY_CONTRAST_FLOOR = 1.5, 0.2
CITY_LINE_LENGTH, CITY_LINE_ANGLES, CITY_LINE_TOP = 12, 12, 0.5
CITY_LINE_RAMP, CITY_LINE_KEEP = (0.05, 0.3), 0.12
CITY_REGION_SIGMA, CITY_REGION_RAMP, CITY_REGION_KEEP = 12.0, (0.015, 0.12), 0.12
CITY_THREAD_GAIN, CITY_THREAD_FLOOR = 1.6, 0.22
# A dim fill inside a city's flat plateau (a plateau has no local contrast): level, ramp of a blur of the mean, its sigma, easing.
CITY_FILL, CITY_FILL_RAMP, CITY_FILL_SIGMA, CITY_FILL_EASE = 0.3, (0.25, 0.9), 3.0, 3.0
# Three taps along the atlas radius (offset in texels, side weight, gain) round a point that would otherwise read as a flat dash.
CITY_ROUND_OFFSET, CITY_ROUND_WEIGHT, CITY_ROUND_GAIN = 0.7, 0.2, 1.3
# One hot core per bright area: a blur of the near-saturated light, its height against the top within a radius, raised to a
# power, with a ramp on the height itself. A faint falloff around it comes from a wider blur of the same statistic.
CITY_HUB_SIGMA, CITY_HUB_RADIUS, CITY_HUB_POWER, CITY_HUB_RAMP = 1.5, 10, 16.0, (0.05, 0.35)
CITY_HALO, CITY_HALO_SIGMA = 0.12, 2.5
# The hub core gets the same radial rounding, a little wider.
CITY_HUB_ROUND_OFFSET, CITY_HUB_ROUND_WEIGHT, CITY_HUB_ROUND_GAIN = 1.2, 0.25, 1.25
# A last small blur of the light, not the coded level, and a slightly lower peak. The shader cubes the filtered channel, so a
# one-texel thread half a texel off a pixel centre falls to an eighth and it sparkles under head motion. The blur's faint tails
# would lift the night side (2.2 luma on the front patch), so a small floor comes off them. Together they take the flicker on
# city pixels from 19 to 11 levels at a yaw step of .01 deg (21 to 14.5 in pitch).
CITY_SOFT_SIGMA, CITY_SOFT_GAIN, CITY_SOFT_FLOOR = 0.45, 0.85, 0.004
MIRROR_CITIES = {"London": (51.507, -0.128), "Rome": (41.903, 12.496), "Moscow": (55.756, 37.617)}

# Belt. GEO_SCALE x the 14.09 deg surface angle to the limb is 42.3 deg of geography, so from 37N the view reaches 5.3S and 79.3N;
# the margin on each side keeps the row wrap of the repeating sampler out of sight. Height 2048 keeps texels near square around
# 37N (3.9-4.2 km) on an 8192-wide map; 16384 would sit exactly at Turnip's limit, and the source clouds stop at 8192 anyway.
BELT_LAT = (-6.0, 80.0)
BELT_SIZE = (8192, 2048)
# What the viewer sees at spin 0, each launch. The latitude and bearing are the cap's; the longitude is 5 deg east of the cap's, because
# at 30 deg/h the populated United States crosses the hero window from about -62 to -112 of sub-longitude, 1.7 hours (about 20 minutes at
# 0.5.15's 150 deg/h): real lights show from
# -63 on, and a start further west only spends them sooner (from a sweep of renders in 5 and 1 deg steps; see space-source.json).
BELT_FIRST_VIEW = (37.0, -64.0)
# The second cloud sample: the same map at the opposite latitude, moved 13 deg south and 129 deg round, which lays the Southern
# Ocean storm track over the views' latitudes (as CLOUD_SECOND does for the cap). The ring (see the shader) keeps it off nadir.
BELT_SECOND_DLAT, BELT_SECOND_DLON = -13.0, 129.0
# Filters reach at most 3 CITY_REGION_SIGMA texels, so this much wrap padding joins the two ends of the belt.
BELT_WRAP = 48
# Tile light fades into the 3 km map over this many degrees inside the tile edge, so no straight line shows at 0 lon, 180 lon or the equator.
BELT_FEATHER_DEG = 1.5
# The 3 km map shows polar ice at the basemap level, which the tiles' grayscale set does not: nothing above this latitude ramp is
# taken from it (Murmansk and Norilsk stand at 69N).
BELT_FALLBACK_POLAR = (70.0, 73.0)
# Belt correlation with the 3 km map, on tile area only. Lower than the cap's REGISTRATION_MIN because the belt's tile area is all
# of North America and the Arctic down to 0 lat, much of it dark, where the 3 km map's basemap adds a level the tiles do not hold.
BELT_REGISTRATION_MIN = 0.65
# The belt's last softening of the light (see CITY_SOFT_*), for lights that also cross pixels as the Earth turns. The shader squares the
# filtered channel here, where the cap cubed it: half a texel off a pixel centre a thread falls to a quarter, not an eighth. With the wider
# blur that takes the swing of a tracked city pixel under head pitch from 9.6 / 23.8 / 38.9 levels (p50 / p90 / p99, the shipped cap) to
# 5.1 / 13.1 / 23.3; .85 gives 3.7 / 9.2 / 16.9 but the lights start to read as blobs. An 8-bit square root still keeps one 10-bit step of
# the buffer (.002 linear) at level 9, which is above where BC7's error sits on dark texels.
BELT_SOFT_SIGMA, BELT_SOFT_GAIN, BELT_SOFT_FLOOR = 0.65, 1.0, 0.004


def check_sources(source: Path) -> None:
    for filename, expected in SOURCES.items():
        path = source / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"Source hash differs: {path}")
    # Black Marble is 13500x6750 (91.1 MP), just above Pillow's default
    # warning threshold. Permit that known, hash-checked source only.
    Image.MAX_IMAGE_PIXELS = 100_000_000


def download_tiles(tiles: Path) -> None:
    """Fetch missing tiles from their public URLs into their own folder. check_tiles still has to pass before any is opened."""
    tiles.mkdir(parents=True, exist_ok=True)
    for filename in TILES:
        path = tiles / filename
        if not path.exists():
            part = path.with_suffix(".part")
            print(f"Downloading {TILE_BASE_URL}{filename}", flush=True)
            urllib.request.urlretrieve(TILE_BASE_URL + filename, part)
            part.replace(path)


def check_tiles(tiles: Path) -> None:
    for filename, (_, _, size, expected) in TILES.items():
        path = tiles / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}: get it from {TILE_BASE_URL}{filename} or run with --download-tiles")
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Tile differs from its pinned size and hash: {path}")


def derive_masks(night: np.ndarray, ground: np.ndarray, cloud: np.ndarray) -> np.ndarray:
    """R cloud, G city lights from the 3 km map (blue basemap removed; the cap replaces it with city_lights), B water; inputs in 0..1."""
    # The NASA visualization includes a blue land basemap. Remove that
    # tint before treating the warm/white excess as emitted city light.
    warm = np.maximum(night[..., 0], night[..., 1]) - .88 * night[..., 2]
    city = np.clip((warm - .018) * 1.18, 0, 1)
    water = np.clip((ground[..., 2] - ground[..., 0] * 1.12) * 12, 0, 1)
    return np.stack((np.clip(cloud, 0, 1), city, water), axis=-1)


# ---------------------------------------------------------------- legacy equirect
def prepare_equirect(source: Path, output: Path, width: int = 4096) -> None:
    if width not in (2048, 4096, 8192):
        raise ValueError("width must be 2048, 4096 or 8192")
    check_sources(source)
    output.mkdir(parents=True, exist_ok=True)
    size = (width, width // 2)
    day = Image.open(source / "world.200412.3x5400x2700.jpg").convert("RGB").resize(size, Image.Resampling.LANCZOS)
    day.save(output / "earth-day.png")
    cloud = np.asarray(Image.open(source / "cloud_combined_8192.tif").convert("L").resize(size, Image.Resampling.LANCZOS), dtype=np.float32) / 255
    night = np.asarray(Image.open(source / "BlackMarble_2016_3km.jpg").convert("RGB").resize(size, Image.Resampling.LANCZOS), dtype=np.float32) / 255
    ground = np.asarray(day, dtype=np.float32) / 255
    mask = derive_masks(night, ground, cloud)
    Image.fromarray(np.rint(mask * 255).astype(np.uint8)).save(output / "earth-extra.png")
    receipt = {
        "mode": "equirect",
        "dimensions": size,
        "cloud_relief": {"sharpen": CLOUD_SHARPEN, "sigma_texels": CLOUD_SIGMA},
        "surface": "sRGB source image",
        "masks": {"R": "cloud coverage (unsharp-masked for relief)", "G": "city lights with blue basemap removed", "B": "water estimate"},
        "filter": "Pillow Lanczos resize",
        "source_sha256": SOURCES,
        "outputs": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ("earth-day.png", "earth-extra.png")},
    }
    (output / "earth-map-preparation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {width}x{width // 2} NASA Earth maps in {output}")


# ---------------------------------------------------------------- cap frame and geography
def cap_frame():
    n0 = -PLANET_DIRECTION / np.linalg.norm(PLANET_DIRECTION)
    east = np.cross([0.0, 1.0, 0.0], n0)
    east /= np.linalg.norm(east)
    north = np.cross(n0, east)
    return n0, east, north


def geo_frame(lat_deg: float, lon_deg: float):
    """ECEF unit vectors (E, N, U) at a geographic point."""
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    up = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    e = np.array([-math.sin(lo), math.cos(lo), 0.0])
    n = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
    return e, n, up


def tangent_to_latlon(x, y, z, sub_lat, sub_lon, heading):
    """Room tangent components (east, north, n0) -> geographic lat/lon in degrees."""
    h = math.radians(heading)
    ge = x * math.cos(h) + y * math.sin(h)
    gn = -x * math.sin(h) + y * math.cos(h)
    e, n, up = geo_frame(sub_lat, sub_lon)
    g = ge[..., None] * e + gn[..., None] * n + z[..., None] * up
    lat = np.degrees(np.arcsin(np.clip(g[..., 2], -1, 1)))
    lon = np.degrees(np.arctan2(g[..., 1], g[..., 0]))
    return lat, lon


def cap_radius_from_rho(rho):
    """Surface angle from n0 (radians) -> atlas radius (0..1 at CAP_RADIUS_DEG)."""
    r0 = math.radians(CAP_RHO0_DEG)
    return np.log1p(rho / r0) / math.log1p(CAP_RADIUS_DEG / CAP_RHO0_DEG)


def cap_rho_from_radius(radius):
    """Atlas radius (0..1) -> surface angle from n0 (radians)."""
    r0 = math.radians(CAP_RHO0_DEG)
    return r0 * np.expm1(radius * math.log1p(CAP_RADIUS_DEG / CAP_RHO0_DEG))


def latlon_to_atlas(lat_deg, lon_deg, sub_lat, sub_lon, heading, size=CAP_SIZE):
    """Geographic point -> atlas pixel coordinates (x right, y down, pixel centres at +.5)."""
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    g = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    e, n, up = geo_frame(sub_lat, sub_lon)
    ge, gn, z = g @ e, g @ n, g @ up
    h = math.radians(heading)
    x = ge * math.cos(h) - gn * math.sin(h)
    y = ge * math.sin(h) + gn * math.cos(h)
    s = math.hypot(x, y)
    rho = math.atan2(s, z)
    scale = float(cap_radius_from_rho(rho / GEO_SCALE)) / max(s, 1e-12)
    a, b = x * scale, y * scale
    return (a + 1) * size / 2, (1 - b) * size / 2


def atlas_latlon(rows: slice, size, sub_lat, sub_lon, heading):
    """Lat/lon of atlas pixel centres for a band of rows."""
    r = np.arange(rows.start, rows.stop, dtype=np.float64)
    c = np.arange(size, dtype=np.float64)
    a = (c[None, :] + .5) / (size / 2) - 1
    b = 1 - (r[:, None] + .5) / (size / 2)
    a, b = np.broadcast_arrays(a, b)
    radius = np.hypot(a, b)
    rho = cap_rho_from_radius(radius) * GEO_SCALE
    safe = np.maximum(radius, 1e-12)
    x = np.sin(rho) * a / safe
    y = np.sin(rho) * b / safe
    z = np.cos(rho)
    return tangent_to_latlon(x, y, z, sub_lat, sub_lon, heading)


# ---------------------------------------------------------------- Catmull-Rom sampling
def catmull_rom_weights(t):
    t2, t3 = t * t, t * t * t
    return (-.5 * t3 + t2 - .5 * t, 1.5 * t3 - 2.5 * t2 + 1, -1.5 * t3 + 2 * t2 + .5 * t, .5 * t3 - .5 * t2)


def sample_catmull_rom(image: np.ndarray, lat, lon):
    """16-tap Catmull-Rom (a = -0.5) of an equirect uint8 image at lat/lon; x wraps, y clamps.

    Returns float32 values in source units (0..255), unclipped.
    """
    h, w = image.shape[:2]
    channels = 1 if image.ndim == 2 else image.shape[2]
    px = (lon + 180.0) / 360.0 * w - .5
    py = (90.0 - lat) / 180.0 * h - .5
    ix, iy = np.floor(px).astype(np.int64), np.floor(py).astype(np.int64)
    wx, wy = catmull_rom_weights(px - ix), catmull_rom_weights(py - iy)
    result = np.zeros(lat.shape + (channels,), dtype=np.float32)
    for j in range(4):
        yy = np.clip(iy + j - 1, 0, h - 1)
        for i in range(4):
            xx = np.mod(ix + i - 1, w)
            taps = image[yy, xx].astype(np.float32).reshape(lat.shape + (channels,))
            result += (wx[i] * wy[j]).astype(np.float32)[..., None] * taps
    return result


def build_cap(sources: dict, sub_lat, sub_lon, heading, size=CAP_SIZE, layers=("day", "night", "cloud"), ss=None):
    """Sample the requested source layers into cap-atlas float arrays (0..1).

    Each atlas texel is the box average of ss x ss Catmull-Rom samples (ss = SUPERSAMPLE).
    """
    ss = SUPERSAMPLE if ss is None else ss
    out = {name: np.zeros((size, size, 3 if name != "cloud" else 1), dtype=np.float32) for name in layers}
    step = max(1, CHUNK_ROWS // ss)
    for start in range(0, size, step):
        stop = min(size, start + step)
        rows = slice(start * ss, stop * ss)
        lat, lon = atlas_latlon(rows, size * ss, sub_lat, sub_lon, heading)
        for name in layers:
            hi = np.clip(sample_catmull_rom(sources[name], lat, lon) / 255.0, 0, 1)
            out[name][start:stop] = hi.reshape(stop - start, ss, size, ss, -1).mean(axis=(1, 3))
    return out


# ---------------------------------------------------------------- shader geometry (view check)
def camera_basis(yaw_deg, pitch_deg):
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    return ry @ rx


def shader_cap_uv(rays):
    """Rays (G) -> (hit mask, atlas uv) exactly as space.gdshader computes them."""
    p = PLANET_DIRECTION / np.linalg.norm(PLANET_DIRECTION)
    center = p * PLANET_DISTANCE
    along = rays @ center
    closest = rays * along[..., None]
    miss = np.linalg.norm(center - closest, axis=-1)
    hit_mask = (miss < 1.0) & (along > 0)
    depth = np.sqrt(np.maximum(1 - np.minimum(miss, .999999) ** 2, 0))
    hit = rays * (along - depth)[..., None]
    nrm = hit - center
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    n0, east, north = cap_frame()
    sx, sy = nrm @ east, nrm @ north
    ls = np.hypot(sx, sy)
    ang = np.arctan2(ls, nrm @ n0)
    k = cap_radius_from_rho(ang) / np.maximum(ls, 1e-5) / 2
    return hit_mask, .5 + sx * k, .5 - sy * k


def bilinear(channel: np.ndarray, u, v):
    h, w = channel.shape
    x = np.clip(u * w - .5, 0, w - 1.001)
    y = np.clip(v * h - .5, 0, h - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    return (channel[y0, x0] * (1 - fx) * (1 - fy) + channel[y0, x0 + 1] * fx * (1 - fy)
            + channel[y0 + 1, x0] * (1 - fx) * fy + channel[y0 + 1, x0 + 1] * fx * fy)


def view_check(city: np.ndarray) -> dict:
    x0, y0, x1, y1 = VIEW_RECT
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    cam = np.stack([(xs + .5 - REF_CENTER[0]) / REF_FOCAL, -(ys + .5 - REF_CENTER[1]) / REF_FOCAL, -np.ones_like(xs)], axis=-1)
    cam /= np.linalg.norm(cam, axis=-1, keepdims=True)
    rays = cam @ camera_basis(0.0, REF_PITCH).T
    hit, u, v = shader_cap_uv(rays)
    values = np.where(hit, bilinear(city, u, v), 0.0)
    pad = np.pad(values, 1, mode="constant", constant_values=-1)
    neighbours = np.stack([pad[1 + dy:pad.shape[0] - 1 + dy, 1 + dx:pad.shape[1] - 1 + dx]
                           for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx])
    maxima = (values > CITY_THRESHOLD) & (values >= neighbours.max(axis=0)) & hit
    return {"rect": list(VIEW_RECT), "hit_fraction": round(float(hit.mean()), 4), "city_maxima": int(maxima.sum()),
            "threshold": CITY_THRESHOLD, "u_range": [round(float(u[hit].min()), 4), round(float(u[hit].max()), 4)] if hit.any() else None,
            "v_range": [round(float(v[hit].min()), 4), round(float(v[hit].max()), 4)] if hit.any() else None}


def mirror_check(sub_lat, sub_lon, heading) -> dict:
    pts = {name: latlon_to_atlas(*ll, sub_lat, sub_lon, heading) for name, ll in MIRROR_CITIES.items()}
    lx, ly = pts["London"]
    rx, ry = pts["Rome"]
    mx, my = pts["Moscow"]
    cross = (rx - lx) * (my - ry) - (ry - ly) * (mx - rx)
    return {"pixels": {k: [round(float(a), 1), round(float(b), 1)] for k, (a, b) in pts.items()}, "cross": round(float(cross), 1)}


# ---------------------------------------------------------------- cap preparation
def load_sources(source: Path) -> dict:
    return {
        "day": np.asarray(Image.open(source / "world.200412.3x5400x2700.jpg").convert("RGB")),
        "night": np.asarray(Image.open(source / "BlackMarble_2016_3km.jpg").convert("RGB")),
        "cloud": np.asarray(Image.open(source / "cloud_combined_8192.tif").convert("L")),
    }


def blur(field: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur (edge padded), sigma in texels."""
    radius = max(1, int(math.ceil(3 * sigma)))
    taps = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    taps /= taps.sum()
    pad = np.pad(field, radius, mode="edge")
    rows = sum(w * pad[:, i:i + field.shape[1]] for i, w in enumerate(taps))
    return sum(w * rows[i:i + field.shape[0], :] for i, w in enumerate(taps))


def max_filter(field: np.ndarray, radius: int) -> np.ndarray:
    """Maximum over a (2 radius + 1) square, one axis at a time."""
    h, w = field.shape
    pad = np.pad(field, ((radius, radius), (0, 0)), mode="edge")
    rows = field.copy()
    for dy in range(2 * radius + 1):
        rows = np.maximum(rows, pad[dy:dy + h, :])
    pad = np.pad(rows, ((0, 0), (radius, radius)), mode="edge")
    out = rows.copy()
    for dx in range(2 * radius + 1):
        out = np.maximum(out, pad[:, dx:dx + w])
    return out


def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def tile_statistics(tiles: Path, sub_lat: float, sub_lon: float, heading: float, size: int = CAP_SIZE) -> dict:
    """Area coverage of the 500 m tiles per atlas texel, in chunks of source rows.

    Each lit source pixel lands in the texel that holds its centre (a texel covers 6-20 source pixels a side), weighted by
    its true area, and the sums are divided by the texel's geographic area. So "mean" is the real area average of the texel's
    footprint, "p2" (root mean square) leans toward its brightest pixels, and "r8" (mean of v^8, fourth root) follows only its
    near-saturated pixels, which leaves out the soft halo around each town. "covered" marks texels inside the tiles.
    """
    check_tiles(tiles)
    count = size * size
    m1, m2, m8 = np.zeros(count), np.zeros(count), np.zeros(count)
    e, n, up = geo_frame(sub_lat, sub_lon)
    h = math.radians(heading)
    per_degree = TILE_SIZE / TILE_DEGREES
    limit = Image.MAX_IMAGE_PIXELS
    # These are 467 MP each, far above Pillow's warning threshold. Permit that for the hash-checked tiles only.
    Image.MAX_IMAGE_PIXELS = TILE_SIZE * TILE_SIZE + 1
    try:
        for filename, (west, north, _, _) in TILES.items():
            with Image.open(tiles / filename) as opened:
                if opened.size != (TILE_SIZE, TILE_SIZE):
                    raise ValueError(f"Unexpected tile size {opened.size}: {filename}")
                light = np.asarray(opened.convert("L"))
            for start in range(0, TILE_SIZE, TILE_CHUNK_ROWS):
                chunk = light[start:start + TILE_CHUNK_ROWS]
                ys, xs = np.nonzero(chunk)
                if not ys.size:
                    continue
                value = chunk[ys, xs].astype(np.float64) / 255
                lat = np.radians(north - (start + ys + .5) / per_degree)
                lon = np.radians(west + (xs + .5) / per_degree)
                area = np.cos(lat)
                g = np.stack([area * np.cos(lon), area * np.sin(lon), np.sin(lat)], axis=-1)
                ge, gn, z = g @ e, g @ n, g @ up
                x = ge * math.cos(h) - gn * math.sin(h)
                y = ge * math.sin(h) + gn * math.cos(h)
                s = np.hypot(x, y)
                scale = cap_radius_from_rho(np.arctan2(s, z) / GEO_SCALE) / np.maximum(s, 1e-12)
                ix = np.floor((x * scale + 1) * size / 2).astype(np.int64)
                iy = np.floor((1 - y * scale) * size / 2).astype(np.int64)
                inside = (ix >= 0) & (ix < size) & (iy >= 0) & (iy < size)
                index = iy[inside] * size + ix[inside]
                area, value = area[inside], value[inside]
                m1 += np.bincount(index, area * value, count)
                m2 += np.bincount(index, area * value ** 2, count)
                m8 += np.bincount(index, area * value ** 8, count)
            del light
            print(f"EARTH_TILE {filename} done", flush=True)
    finally:
        Image.MAX_IMAGE_PIXELS = limit
    # Geographic area of a texel in units of (source pixel angle)^2: sin(rho) d(rho)/dr / r da db.
    axis = (np.arange(size) + .5) / (size / 2) - 1
    a, b = np.meshgrid(axis, -axis)
    radius = np.maximum(np.hypot(a, b), 1e-9)
    log_norm = math.log1p(CAP_RADIUS_DEG / CAP_RHO0_DEG)
    rho = cap_rho_from_radius(radius) * GEO_SCALE
    drho = GEO_SCALE * math.radians(CAP_RHO0_DEG) * log_norm * np.exp(radius * log_norm)
    texel = np.sin(rho) * drho / radius * (2 / size) ** 2 / math.radians(1 / per_degree) ** 2
    lat, lon = atlas_latlon(slice(0, size), size, sub_lat, sub_lon, heading)
    shape = (size, size)
    return {"mean": m1.reshape(shape) / texel, "p2": np.sqrt(np.maximum(m2.reshape(shape) / texel, 0)), "r8": np.maximum(m8.reshape(shape) / texel, 0) ** .25,
            "covered": (lat >= 0) & (lon < 0)}


def line_evidence(field: np.ndarray) -> np.ndarray:
    """How much a texel sits on a line of light. For each direction, the mean of the field along the segment on each side of
    the texel; the weaker side counts and the best direction wins. A lone town scores low (dark both ways), a road or a chain of
    towns high (lit both ways). It only weights light that is really there, because the result multiplies the data."""
    length = CITY_LINE_LENGTH
    h, w = field.shape
    pad = np.pad(field, length + 1)
    best = np.zeros_like(field)
    for k in range(CITY_LINE_ANGLES):
        angle = math.pi * k / CITY_LINE_ANGLES
        dx, dy = math.cos(angle), math.sin(angle)
        ahead, behind = np.zeros_like(field), np.zeros_like(field)
        for step in range(1, length + 1):
            ox, oy = int(round(dx * step)), int(round(dy * step))
            ahead += pad[length + 1 + oy:length + 1 + oy + h, length + 1 + ox:length + 1 + ox + w]
            behind += pad[length + 1 - oy:length + 1 - oy + h, length + 1 - ox:length + 1 - ox + w]
        best = np.maximum(best, np.minimum(ahead, behind) / length)
    return best


def round_along_radius(field: np.ndarray, offset: float, weight: float) -> np.ndarray:
    """Three taps along the atlas radius. A texel is about twice as wide on screen tangentially as radially, so a single bright
    texel would read as a flat dash, and its radial peak could fall between pixels under head motion."""
    size = field.shape[0]
    axis = np.arange(size) + .5 - size / 2
    x, y = np.meshgrid(axis, axis)
    radius = np.maximum(np.hypot(x, y), 1e-6)
    ox, oy = offset * x / radius, offset * y / radius

    def taps(sx, sy):
        px = np.clip(x + size / 2 - .5 + sx, 0, size - 1.001)
        py = np.clip(y + size / 2 - .5 + sy, 0, size - 1.001)
        x0, y0 = px.astype(np.int32), py.astype(np.int32)
        fx, fy = px - x0, py - y0
        return (field[y0, x0] * (1 - fx) * (1 - fy) + field[y0, x0 + 1] * fx * (1 - fy)
                + field[y0 + 1, x0] * (1 - fx) * fy + field[y0 + 1, x0 + 1] * fx * fy)

    return (1 - 2 * weight) * field + weight * (taps(ox, oy) + taps(-ox, -oy))


def round_isotropic(field: np.ndarray, offset: float, weight: float) -> np.ndarray:
    """The belt's stand-in for round_along_radius: a blur of the same variance (2 weight offset^2), since no direction is special on a map that turns."""
    return blur(field, offset * math.sqrt(2 * weight))


def city_lights(stats: dict, rounding=round_along_radius, soft=(CITY_SOFT_SIGMA, CITY_SOFT_GAIN, CITY_SOFT_FLOOR)) -> np.ndarray:
    """The city channel, from real light only (no random numbers, no thinning that invents gaps).

    Threads: how far a texel's peak-leaning statistic rises above its surroundings, relative to them, so a road across dark
    land, a spoke through a suburb and a town all stand out while a flat city interior does not. Towns with no line of light
    through them recede, and so does light in regions that hold little. Hubs: one small hot core per bright area, from the
    near-saturated light. The shader cubes this channel, so it reads as a coded level, not as linear light;
    the last step blurs the light a little so threads are not narrower than a pixel after that cube (CITY_SOFT_SIGMA).
    """
    p2, mean, r8 = stats["p2"], stats["mean"], stats["r8"]
    around = blur(p2, CITY_CONTRAST_SIGMA)
    contrast = np.clip((p2 - around) / (around + CITY_CONTRAST_FLOOR), 0, 1)
    line = smoothstep(*CITY_LINE_RAMP, line_evidence(np.minimum(p2, CITY_LINE_TOP)))
    region = smoothstep(*CITY_REGION_RAMP, blur(mean, CITY_REGION_SIGMA))
    threads = CITY_THREAD_GAIN * contrast * (CITY_LINE_KEEP + (1 - CITY_LINE_KEEP) * line) * (CITY_REGION_KEEP + (1 - CITY_REGION_KEEP) * region)
    threads = np.clip(threads - CITY_THREAD_FLOOR, 0, None) / (1 - CITY_THREAD_FLOOR)
    local = blur(mean, CITY_FILL_SIGMA)
    fill = CITY_FILL * np.clip(p2, 0, 1) / (1 + CITY_FILL_EASE * (1 - local)) * smoothstep(*CITY_FILL_RAMP, local)
    low = np.clip(rounding(threads + fill, CITY_ROUND_OFFSET, CITY_ROUND_WEIGHT) * CITY_ROUND_GAIN, 0, 1)
    dome = blur(r8, CITY_HUB_SIGMA)
    hub = np.clip(dome / np.maximum(max_filter(dome, CITY_HUB_RADIUS), 1e-4), 0, 1) ** CITY_HUB_POWER * smoothstep(*CITY_HUB_RAMP, dome)
    hub = np.clip(rounding(hub, CITY_HUB_ROUND_OFFSET, CITY_HUB_ROUND_WEIGHT) * CITY_HUB_ROUND_GAIN, 0, 1)
    halo = np.clip(CITY_HALO * blur(r8, CITY_HALO_SIGMA), 0, 1)
    low = low + (1 - low) * halo
    city = np.clip(low + (1 - low) * hub, 0, 1)
    soft = (blur(city ** 3, soft[0]) * soft[1] - soft[2]) / (1 - soft[2])
    return np.cbrt(np.clip(soft, 0, 1)).astype(np.float32)


def ring_weight(size: int) -> np.ndarray:
    a = (np.arange(size) + .5) / (size / 2) - 1
    r = np.hypot(a[None, :], a[:, None])
    t = np.clip((r - CLOUD_RING[0]) / (CLOUD_RING[1] - CLOUD_RING[0]), 0, 1)
    return (t * t * (3 - 2 * t)).astype(np.float32)


def cloud_relief(cloud: np.ndarray) -> np.ndarray:
    """Local contrast for the cloud layer: an unsharp mask (CLOUD_SHARPEN x the difference from a
    CLOUD_SIGMA-texel blur) so moonlit cloud decks show their cells and edges instead of a flat
    haze. The mean is unchanged, so far mips keep the same cover."""
    return np.clip(cloud + CLOUD_SHARPEN * (cloud - blur(cloud, CLOUD_SIGMA)), 0, 1).astype(np.float32)


def city_layer(night: np.ndarray) -> np.ndarray:
    warm = np.maximum(night[..., 0], night[..., 1]) - .88 * night[..., 2]
    return np.clip((warm - .018) * 1.18, 0, 1)


def prepare_cap(source: Path, tiles: Path, output: Path, sub_lat: float, sub_lon: float, heading: float, size: int = CAP_SIZE,
                city_mode: str = "lights") -> None:
    check_sources(source)
    if city_mode == "lights":
        check_tiles(tiles)
    output.mkdir(parents=True, exist_ok=True)
    sources = load_sources(source)
    n0, east, north = cap_frame()
    first = (sub_lat, sub_lon, heading)
    candidates = [first] + [c for c in ALTERNATES if c != first]
    checks = {}
    chosen = None
    nights = {}
    for cand in candidates:
        lat0, lon0, head0 = cand
        mirror = mirror_check(lat0, lon0, head0)
        if mirror["cross"] >= 0:
            raise AssertionError(f"Cap atlas is mirrored: London->Rome->Moscow cross {mirror['cross']} (must be negative)")
        nights[cand] = build_cap(sources, lat0, lon0, head0, size, layers=("night",))["night"]
        view = view_check(city_layer(nights[cand]))
        key = f"{lat0:.1f}N {lon0:.1f}E h{head0:+.0f}"
        checks[key] = {"view": view, "mirror": mirror}
        print(f"EARTH_CAP_CHECK {key} city_maxima={view['city_maxima']} hit={view['hit_fraction']} mirror_cross={mirror['cross']}", flush=True)
        if chosen is None and view["city_maxima"] >= VIEW_MIN_MAXIMA:
            chosen = cand
            break
    if chosen is None:
        best = max(checks, key=lambda k: checks[k]["view"]["city_maxima"])
        chosen = next(c for c in candidates if f"{c[0]:.1f}N {c[1]:.1f}E h{c[2]:+.0f}" == best)
        print(f"EARTH_CAP_WARNING no sub-viewer reached {VIEW_MIN_MAXIMA} city maxima; keeping the best, {best}", flush=True)
    layers = build_cap(sources, chosen[0], chosen[1], chosen[2], size, layers=("day", "cloud"))
    day, night, cloud = layers["day"], nights[chosen], layers["cloud"][..., 0]
    del nights
    if CLOUD_SECOND is not None:
        second = build_cap(sources, *CLOUD_SECOND, size, layers=("cloud",))["cloud"][..., 0]
        cloud = 1 - (1 - cloud) * (1 - second * ring_weight(size))
    Image.fromarray(np.rint(day * 255).astype(np.uint8)).save(output / "earth-day.png")
    mask = derive_masks(night, day, cloud)
    if CLOUD_SHARPEN:
        mask[..., 0] = cloud_relief(mask[..., 0])
    plain_view = view_check(mask[..., 1])
    registration = covered_share = None
    if city_mode == "lights":
        stats = tile_statistics(tiles, chosen[0], chosen[1], chosen[2], size)
        fallback = np.clip((np.maximum(night[..., 0], night[..., 1]) - FALLBACK_BASEMAP) / (1 - FALLBACK_BASEMAP), 0, 1).astype(np.float64)
        # The atlas corners lie outside the cap and are never drawn; the 3 km map's bright polar ice stays out of them.
        axis = (np.arange(size) + .5) / (size / 2) - 1
        fallback *= np.hypot(axis[None, :], axis[:, None]) <= 1
        covered = stats["covered"]
        covered_share = float(covered.mean())
        registration = float(np.corrcoef(blur(stats["mean"], 2.0)[covered], blur(fallback, 2.0)[covered])[0, 1])
        if registration < REGISTRATION_MIN:
            raise AssertionError(f"500 m tiles and 3 km map disagree on where the light is: correlation {registration:.3f}")
        for name in ("mean", "p2", "r8"):
            stats[name] = np.where(covered, stats[name], fallback)
        mask[..., 1] = city_lights(stats)
    Image.fromarray(np.rint(mask * 255).astype(np.uint8)).save(output / "earth-extra.png")
    final_view = view_check(mask[..., 1])
    key = f"{chosen[0]:.1f}N {chosen[1]:.1f}E h{chosen[2]:+.0f}"
    print(f"EARTH_CAP_VIEW {key} city_maxima={final_view['city_maxima']} ({city_mode}; 3 km mask {plain_view['city_maxima']}; final atlas, 8-bit)", flush=True)
    receipt = {
        "mode": "cap",
        "dimensions": [size, size],
        "projection": "azimuthal cap, radius 16 deg of surface angle, centred on n0; row 0 = +north; logarithmic radius "
                      "r = ln(1 + rho/rho0)/ln(1 + 16/rho0); geographic angle = geo_scale x surface angle along the same bearing",
        "rho0_deg": CAP_RHO0_DEG,
        "geo_scale": GEO_SCALE,
        "frame_godot_room_space": {"n0": [round(float(v), 6) for v in n0], "east": [round(float(v), 6) for v in east],
                                   "north": [round(float(v), 6) for v in north], "planet_direction": PLANET_DIRECTION.tolist(),
                                   "planet_distance": PLANET_DISTANCE},
        "cap_radius_deg": CAP_RADIUS_DEG,
        "sub_viewer": {"lat": chosen[0], "lon": chosen[1], "heading_deg": chosen[2],
                       "requested": list(first), "alternates": [list(c) for c in ALTERNATES]},
        "filter": f"Catmull-Rom bicubic (a=-0.5), 16 taps, x wrapped, y clamped, {SUPERSAMPLE}x{SUPERSAMPLE} supersampled and box-averaged per atlas texel, "
                  "chunks of atlas rows; masks derived after resampling",
        "city_lights": {"mode": city_mode, "view_check_3km_mask": plain_view,
                        "tiles": {name: {"url": TILE_BASE_URL + name, "west_lon": t[0], "north_lat": t[1], "bytes": t[2], "sha256": t[3]} for name, t in TILES.items()},
                        "tile_size": TILE_SIZE, "tile_degrees": TILE_DEGREES, "fallback_3km_basemap": FALLBACK_BASEMAP,
                        "covered_share_of_atlas": round(covered_share, 4) if covered_share is not None else None,
                        "registration_correlation_with_3km": round(registration, 4) if registration is not None else None, "registration_min": REGISTRATION_MIN,
                        "contrast": {"sigma_texels": CITY_CONTRAST_SIGMA, "floor": CITY_CONTRAST_FLOOR},
                        "line_evidence": {"length_texels": CITY_LINE_LENGTH, "directions": CITY_LINE_ANGLES, "statistic_top": CITY_LINE_TOP, "ramp": list(CITY_LINE_RAMP), "keep_without_line": CITY_LINE_KEEP},
                        "region": {"sigma_texels": CITY_REGION_SIGMA, "ramp": list(CITY_REGION_RAMP), "keep": CITY_REGION_KEEP},
                        "threads": {"gain": CITY_THREAD_GAIN, "soft_floor": CITY_THREAD_FLOOR},
                        "fill": {"level": CITY_FILL, "ramp": list(CITY_FILL_RAMP), "sigma_texels": CITY_FILL_SIGMA, "ease": CITY_FILL_EASE},
                        "round_along_radius": {"offset_texels": CITY_ROUND_OFFSET, "side_weight": CITY_ROUND_WEIGHT, "gain": CITY_ROUND_GAIN},
                        "hub": {"sigma_texels": CITY_HUB_SIGMA, "radius_texels": CITY_HUB_RADIUS, "power": CITY_HUB_POWER, "ramp": list(CITY_HUB_RAMP),
                                "round_offset_texels": CITY_HUB_ROUND_OFFSET, "round_side_weight": CITY_HUB_ROUND_WEIGHT, "round_gain": CITY_HUB_ROUND_GAIN},
                        "halo": {"level": CITY_HALO, "sigma_texels": CITY_HALO_SIGMA},
                        "soften": {"sigma_texels": CITY_SOFT_SIGMA, "light_gain": CITY_SOFT_GAIN, "light_floor": CITY_SOFT_FLOOR},
                        "note": "real light only, no random numbers: local contrast of the peak-leaning area statistic, weighted by line evidence and regional light, plus one hot core per bright area (see city_lights)"},
        "cloud_relief": {"sharpen": CLOUD_SHARPEN, "sigma_texels": CLOUD_SIGMA},
        "cloud_second_sample": {"sub_viewer": list(CLOUD_SECOND) if CLOUD_SECOND else None, "ring": list(CLOUD_RING),
                                "blend": "1 - (1 - cloud) * (1 - second * smoothstep(ring, atlas radius))"},
        "surface": "sRGB source image",
        "masks": {"R": "cloud coverage (window ring densified by a second sample, unsharp-masked for relief)", "G": "city lights from the 500 m tiles (threads and hubs, cubed by the shader; 3 km fallback outside the tiles)", "B": "water estimate"},
        "checks": checks,
        "final_view_check": final_view,
        "source_sha256": {**SOURCES, **{name: t[3] for name, t in TILES.items()}},
        "outputs": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ("earth-day.png", "earth-extra.png")},
    }
    (output / "earth-map-preparation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {size}x{size} cap atlas (sub-viewer {key}, geo scale {GEO_SCALE}) in {output}")


# ---------------------------------------------------------------- belt preparation
def belt_range() -> tuple:
    return math.sin(math.radians(BELT_LAT[0])), math.sin(math.radians(BELT_LAT[1]))


def belt_grid(width: int, height: int, rows: slice) -> tuple:
    """Lat and lon (degrees) of belt texel centres for a band of rows. Row 0 is north; rows are linear in sin(lat)."""
    z0, z1 = belt_range()
    z = z1 - (np.arange(rows.start, rows.stop) + .5) / height * (z1 - z0)
    lon = -180.0 + (np.arange(width) + .5) / width * 360.0
    return np.broadcast_arrays(np.degrees(np.arcsin(z))[:, None], lon[None, :])


def sample_belt(image: np.ndarray, width: int, height: int, ss: int = 1, dlat=None, dlon: float = 0.0) -> np.ndarray:
    """An equirect source on the belt (0..1). ss box-averages ss x ss Catmull-Rom samples per texel. dlat flips the latitude and adds dlat, dlon adds longitude."""
    channels = 1 if image.ndim == 2 else image.shape[2]
    out = np.zeros((height, width, channels), np.float32)
    step = max(1, CHUNK_ROWS // ss)
    for start in range(0, height, step):
        stop = min(height, start + step)
        lat, lon = belt_grid(width * ss, height * ss, slice(start * ss, stop * ss))
        if dlat is not None:
            lat = np.clip(dlat - lat, -89.9, 89.9)
        lon = (lon + dlon + 180.0) % 360.0 - 180.0
        hi = np.clip(sample_catmull_rom(image, lat, lon) / 255.0, 0, 1)
        out[start:stop] = hi.reshape(stop - start, ss, width, ss, -1).mean(axis=(1, 3))
    return out


def belt_statistics(tiles: Path, width: int, height: int) -> dict:
    """tile_statistics on the belt: a texel has the same geographic area everywhere, since rows are linear in sin(lat)."""
    check_tiles(tiles)
    count = width * height
    m1, m2, m8 = np.zeros(count), np.zeros(count), np.zeros(count)
    per_degree = TILE_SIZE / TILE_DEGREES
    z0, z1 = belt_range()
    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = TILE_SIZE * TILE_SIZE + 1
    try:
        for filename, (west, north, _, _) in TILES.items():
            with Image.open(tiles / filename) as opened:
                light = np.asarray(opened.convert("L"))
            for start in range(0, TILE_SIZE, TILE_CHUNK_ROWS):
                chunk = light[start:start + TILE_CHUNK_ROWS]
                ys, xs = np.nonzero(chunk)
                if not ys.size:
                    continue
                value = chunk[ys, xs].astype(np.float64) / 255
                lat = np.radians(north - (start + ys + .5) / per_degree)
                area = np.cos(lat)
                ix = np.floor((west + (xs + .5) / per_degree + 180.0) / 360.0 * width).astype(np.int64)
                iy = np.floor((z1 - np.sin(lat)) / (z1 - z0) * height).astype(np.int64)
                inside = (ix >= 0) & (ix < width) & (iy >= 0) & (iy < height)
                index = iy[inside] * width + ix[inside]
                area, value = area[inside], value[inside]
                m1 += np.bincount(index, area * value, count)
                m2 += np.bincount(index, area * value ** 2, count)
                m8 += np.bincount(index, area * value ** 8, count)
            del light
            print(f"EARTH_TILE {filename} done", flush=True)
    finally:
        Image.MAX_IMAGE_PIXELS = limit
    texel = (2 * math.pi / width) * ((z1 - z0) / height) / math.radians(1 / per_degree) ** 2
    shape = (height, width)
    return {"mean": m1.reshape(shape) / texel, "p2": np.sqrt(np.maximum(m2.reshape(shape) / texel, 0)), "r8": np.maximum(m8.reshape(shape) / texel, 0) ** .25}


def belt_fallback(night: np.ndarray, width: int, height: int) -> tuple:
    """The 3 km map as light (basemap off, polar ice off) and the weight the tiles get: 1 inside them, feathered to 0 at their edges."""
    lat, lon = belt_grid(width, height, slice(0, height))
    fallback = sample_belt(night, width, height)
    fallback = np.clip((np.maximum(fallback[..., 0], fallback[..., 1]) - FALLBACK_BASEMAP) / (1 - FALLBACK_BASEMAP), 0, 1).astype(np.float64)
    fallback *= 1 - smoothstep(*BELT_FALLBACK_POLAR, lat)
    inward = np.minimum(np.minimum(lat - 0.0, 0.0 - lon), lon + 180.0)
    return fallback, smoothstep(0.0, BELT_FEATHER_DEG, inward)


def wrap_city_lights(stats: dict) -> np.ndarray:
    """city_lights with the belt's two ends joined, so the filters do not cut at 180 lon."""
    pad = {name: np.pad(field, ((0, 0), (BELT_WRAP, BELT_WRAP)), mode="wrap") for name, field in stats.items()}
    coded = city_lights(pad, round_isotropic, (BELT_SOFT_SIGMA, BELT_SOFT_GAIN, BELT_SOFT_FLOOR))[:, BELT_WRAP:-BELT_WRAP]
    # city_lights codes for the cap's cube; the belt's shader squares.
    return coded ** 1.5


def wrap_cloud_relief(cloud: np.ndarray) -> np.ndarray:
    return cloud_relief(np.pad(cloud, ((0, 0), (BELT_WRAP, BELT_WRAP)), mode="wrap"))[:, BELT_WRAP:-BELT_WRAP]


def belt_city_statistics(tiles: Path, night: np.ndarray, width: int, height: int) -> tuple:
    """The tile statistics with the 3 km map standing in where the tiles stop, and the checks on that join."""
    stats = belt_statistics(tiles, width, height)
    fallback, weight = belt_fallback(night, width, height)
    covered = weight >= 1
    registration = float(np.corrcoef(blur(stats["mean"], 2.0)[covered], blur(fallback, 2.0)[covered])[0, 1])
    if registration < BELT_REGISTRATION_MIN:
        raise AssertionError(f"500 m tiles and 3 km map disagree on where the light is: correlation {registration:.3f}")
    for name in stats:
        stats[name] = weight * stats[name] + (1 - weight) * fallback
    return stats, registration, float(covered.mean())


def geo_basis_constants(sub_lat: float, sub_lon: float, heading: float) -> dict:
    """What the shader needs to invert the mapping: the columns of GEO_BASIS (room tangent x, y and n0 onto ECEF at spin 0), the cap frame, BELT_TOP and BELT_SCALE."""
    h = math.radians(heading)
    e, n, up = geo_frame(sub_lat, sub_lon)
    n0, east, north = cap_frame()
    z0, z1 = belt_range()
    return {"geo_x": e * math.cos(h) - n * math.sin(h), "geo_y": e * math.sin(h) + n * math.cos(h), "geo_z": up,
            "cap_n0": n0, "cap_east": east, "cap_north": north, "belt_top": z1, "belt_scale": 1 / (z1 - z0)}


def prepare_belt(source: Path, tiles: Path, output: Path) -> None:
    check_sources(source)
    check_tiles(tiles)
    output.mkdir(parents=True, exist_ok=True)
    sources = load_sources(source)
    width, height = BELT_SIZE
    day = sample_belt(sources["day"], width // 2, height // 2, SUPERSAMPLE)
    Image.fromarray(np.rint(day * 255).astype(np.uint8)).save(output / "earth-surface.png")
    del day
    print("EARTH_BELT surface done", flush=True)
    ground = sample_belt(sources["day"], width, height)
    water = np.clip((ground[..., 2] - ground[..., 0] * 1.12) * 12, 0, 1)
    del ground
    base = wrap_cloud_relief(sample_belt(sources["cloud"], width, height)[..., 0])
    second = wrap_cloud_relief(sample_belt(sources["cloud"], width, height, dlat=BELT_SECOND_DLAT, dlon=BELT_SECOND_DLON)[..., 0])
    Image.fromarray(np.rint(np.stack([base, second, np.zeros_like(base)], -1) * 255).astype(np.uint8)).save(output / "earth-clouds.png")
    del base, second
    print("EARTH_BELT clouds done", flush=True)
    stats, registration, covered_share = belt_city_statistics(tiles, sources["night"], width, height)
    city = wrap_city_lights(stats)
    Image.fromarray(np.rint(np.stack([city, water, np.zeros_like(city)], -1) * 255).astype(np.uint8)).save(output / "earth-masks.png")
    constants = geo_basis_constants(*BELT_FIRST_VIEW, HEADING)
    names = ("earth-surface.png", "earth-masks.png", "earth-clouds.png")
    receipt = {
        "mode": "belt",
        "projection": "wrapped longitude, u = lon/360 + .5; latitude %g to %g, v = (sin(top) - sin(lat)) / (sin(top) - sin(bottom)); row 0 = north" % BELT_LAT,
        "dimensions": {"earth-surface": [width // 2, height // 2], "earth-masks": [width, height], "earth-clouds": [width, height]},
        "geo_scale": GEO_SCALE,
        "first_view": {"lat": BELT_FIRST_VIEW[0], "lon": BELT_FIRST_VIEW[1], "bearing_of_room_north_deg": HEADING},
        "shader_constants": {k: (np.round(v, 6).tolist() if isinstance(v, np.ndarray) else round(float(v), 6)) for k, v in constants.items()},
        "city_lights": {"tiles": {name: {"url": TILE_BASE_URL + name, "west_lon": t[0], "north_lat": t[1], "bytes": t[2], "sha256": t[3]} for name, t in TILES.items()},
                        "fallback_3km_basemap": FALLBACK_BASEMAP, "feather_deg": BELT_FEATHER_DEG, "fallback_polar_cut_lat": list(BELT_FALLBACK_POLAR),
                        "covered_share_of_belt": round(covered_share, 4), "registration_correlation_with_3km": round(registration, 4), "registration_min": BELT_REGISTRATION_MIN,
                        "soften": {"sigma_texels": BELT_SOFT_SIGMA, "light_gain": BELT_SOFT_GAIN, "light_floor": BELT_SOFT_FLOOR}, "wrap_padding_texels": BELT_WRAP},
        "cloud_relief": {"sharpen": CLOUD_SHARPEN, "sigma_texels": CLOUD_SIGMA},
        "cloud_second_sample": {"dlat": BELT_SECOND_DLAT, "dlon": BELT_SECOND_DLON},
        "source_sha256": {**SOURCES, **{name: t[3] for name, t in TILES.items()}},
        "outputs": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names},
    }
    (output / "earth-map-preparation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {width}x{height} belt maps in {output}; registration {registration:.3f}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--belt", action="store_true", help="Wrapped latitude belt for an Earth that turns (default)")
    mode.add_argument("--cap", action="store_true", help="The fixed cap atlas shipped up to 0.5.11")
    mode.add_argument("--equirect", action="store_true", help="Legacy 2:1 equirect maps")
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("FRAME_CINEMA_EARTH_SOURCE", str(WORKSPACE / ".local/earth-nasa"))))
    parser.add_argument("--tiles", type=Path, default=Path(os.environ.get("FRAME_CINEMA_EARTH_TILES", str(WORKSPACE / ".local/earth-nasa-500m"))))
    parser.add_argument("--download-tiles", action="store_true", help="Fetch missing 500 m tiles from their public URLs first (their hashes are always checked)")
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("FRAME_CINEMA_EARTH_INPUT", str(WORKSPACE / ".local/starship-earth/maps"))))
    parser.add_argument("--width", type=int, default=4096, choices=(2048, 4096, 8192), help="Legacy equirect width")
    parser.add_argument("--sub-lat", type=float, default=SUB_VIEWER[0])
    parser.add_argument("--sub-lon", type=float, default=SUB_VIEWER[1])
    parser.add_argument("--heading", type=float, default=HEADING, help="Geographic bearing of room north, degrees (0 = north up)")
    parser.add_argument("--geo-scale", type=float, default=GEO_SCALE, help="Geographic angle per surface angle (feature scale)")
    parser.add_argument("--city-mode", choices=("lights", "plain"), default="lights", help="lights: 500 m tiles (default); plain: the 3 km mask as it is")
    args = parser.parse_args()
    globals()["GEO_SCALE"] = args.geo_scale
    if args.download_tiles:
        download_tiles(args.tiles.resolve())
    if args.equirect:
        prepare_equirect(args.source.resolve(), args.output.resolve(), args.width)
    elif not args.cap:
        prepare_belt(args.source.resolve(), args.tiles.resolve(), args.output.resolve())
    else:
        prepare_cap(args.source.resolve(), args.tiles.resolve(), args.output.resolve(), args.sub_lat, args.sub_lon, args.heading, city_mode=args.city_mode)


if __name__ == "__main__":
    main()
