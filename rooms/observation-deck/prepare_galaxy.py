"""Build the Observation Deck's Milky Way from NASA's real all-sky map as a float equirect strip.

Run with the pinned Blender (it supplies numpy and the EXR reader and writer):
    blender --background --python prepare_galaxy.py -- [--source <exr>] [--output <galaxy.exr>]
        [--exposure X] [--tint r,g,b] [--preview <png>]

Source: NASA/Goddard SVS Deep Star Maps 2020, milkyway_2020_8k_gal.exr (8192x4096, galactic plate
carree, l increasing to the left, top row +b). It already has the resolved stars removed.
Output: 4096x1024 float galaxy.exr (linear RGB). u = galactic longitude (lon = (u - .5) * 360 deg,
galactic centre at u = .5, seamless across u = 0/1); v = sin(galactic latitude) mapped from -0.6
(row 0, v = 0) to +0.6 (v = 1). space.gdshader reads it with guv = (atan(g.z, g.x)/TAU + .5,
g.y/1.2 + .5) and scales it by galaxy_exposure. The band is a true great circle: nothing here moves
it, so its path in the room is the shader's galaxy basis alone.
Arrays are top-row-first; the bpy image write flips rows (row-order rule).
Default output: <workspace>/.local/starship-earth/maps/galaxy.exr, then run pack_earth.gd.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
# Keep the script folder off the import path. It used to hold inspect.py (now
# view_room.py), which shadowed the standard-library module numpy imports.
sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != HERE]

import bpy
import numpy as np

WORKSPACE = HERE.parents[1]
SOURCE = WORKSPACE / 'downloads/milkyway_2020_8k_gal.exr'  # NASA SVS Deep Star Maps 2020, 8k galactic
SOURCE_SHA256 = 'd319113f35e45f7f66f2844f088639cc07cda74a5049299a6098d41e2ade3d28'
WIDTH, HEIGHT = 4096, 1024
SIN_LAT_MAX = 0.6
# Stored scale: the graded strip tops out near .05 linear and BC6H keeps its precision in normal
# half-floats (above 6.1e-5), so it is stored 8x up and space.gdshader's galaxy_exposure divides it back.
SCALE = 8.0
# The strip is shown at this gain: galaxy_exposure = SHOWN_GAIN / SCALE (.1875). One number and no rebake, checked by
# check_integration.py. 1.5x and B/R 1.75 were picked on 2026-11-03 from four test grades.
SHOWN_GAIN = 1.5
LUMA = np.array([.2126, .7152, .0722])
# Grade, in the map's luminance: band median .017, p99.9 .2, |b| 20-25 deg .004, off-band grain about .001.
# BLACK takes the grain to true black; EXPOSURE puts the band median near 3 10-bit steps (.002 linear each) and
# |b| 20 deg near half a step; KNEE holds the bulge to .045 linear, under the top 2.5 mag of the stars (.6 cap),
# so it stays faint light and not an image. These levels are the strip's, before SHOWN_GAIN.
BLACK = 0.0013
EXPOSURE = 0.47
KNEE = 0.1
# Hue: the map's band is warm (B/R about .62), and TINT_KEEP keeps part of that variation, so dust stays warmer than
# the star clouds. TINT lands the band at B/R 2.9, a little bluer than the 1.75
# picked on 2026-11-03. HALO_TINT is that 1.75, kept where the band has faded: one 10-bit step of a saturated tint there rounds to navy.
TINT = (0.53, 1.03, 2.08)
HALO_TINT = (0.70, 1.03, 1.57)
TINT_KEEP = 0.5
# Fades out before the strip ends at |sin b| .6 (36.9 deg). The band is under half a 10-bit step by |sin b| .44, so this
# only tapers the Magellanic Clouds and leaves no latitude to read as an edge.
FADE_SIN = (0.44, 0.60)
# Multi-scale grade: the knee sets the level from a 3 deg blur, and the map's own contrast at finer and wider scales goes back
# on top of it, since the knee is what flattened the band. Blurs in degrees at the band, where a strip texel is .0879 x .0671.
TEXEL_DEG = (0.0879, 0.0671)
MID_DEG, FINE_DEG, WIDE_DEG, KEEP_DEG = 3.0, 0.7, 12.0, 6.0
# Powers on the ratios fine / mid, texel / fine and mid / wide. The texel ratio stays under 1, because band stars now carry
# the finest points as a fixed-angle kernel, which holds still better than texels do.
GAIN_MID, GAIN_FINE, GAIN_WIDE = 1.6, 0.9, 1.15
# The powers and the bluer tint fade in with the 3 deg level (map luminance), so nothing new appears off the band.
BAND_FROM, BAND_FULL = 0.006, 0.02
# Off the band the texel ratio is mostly grain: keep this much of it.
HALO_GRAIN = 0.6
# The contrast must not move the 6 deg mean by more than this.
KEEP_RANGE = (0.6, 1.2)
# Shown 10-bit steps (.00196) taken off the band only, so its gaps reach about 2 steps; and the soft ceiling, 60% of it linear.
STEP = 2.0 / 1023.0
BAND_BLACK = 1.25
CEILING = 34.0


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def read_source(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    w, h = image.size
    pixels = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    # bpy rows are bottom-up, so row 0 here is b = -90; the source's l increases to the left.
    return pixels.reshape(h, w, 4)[:, ::-1, :3]


def to_strip(source):
    """Exact area average into the strip's cells: 2:1 in longitude, sin(lat) rows through a cumulative sum."""
    h, w = source.shape[:2]
    assert w == 2 * WIDTH and h == w // 2, 'Expected an 8192x4096 map'
    box = (source[:, 0::2] + source[:, 1::2]) * 0.5
    edges = (np.degrees(np.arcsin((np.arange(HEIGHT + 1) / HEIGHT - 0.5) * 2.0 * SIN_LAT_MAX)) + 90.0) / 180.0 * h
    total = np.zeros((h + 1,) + box.shape[1:], np.float64)
    total[1:] = np.cumsum(box.astype(np.float64), axis=0)
    low = np.floor(edges).astype(int)
    frac = (edges - low)[:, None, None]
    at_edge = total[low] * (1.0 - frac) + total[low + 1] * frac
    return (at_edge[1:] - at_edge[:-1]) / (edges[1:] - edges[:-1])[:, None, None]


def blur(field, degrees):
    """Gaussian in degrees at the band. Wraps both ways: the strip's top and bottom rows are black."""
    fy = np.fft.fftfreq(field.shape[0])[:, None]
    fx = np.fft.rfftfreq(field.shape[1])[None, :]
    sx, sy = degrees / TEXEL_DEG[0], degrees / TEXEL_DEG[1]
    return np.fft.irfft2(np.fft.rfft2(field) * np.exp(-2.0 * np.pi ** 2 * ((sx * fx) ** 2 + (sy * fy) ** 2)), s=field.shape)


def grade(strip, exposure, tint):
    lum = strip @ LUMA
    mid = np.maximum(blur(lum, MID_DEG), 1e-6)
    fine = np.maximum(blur(lum, FINE_DEG), 1e-6)
    band = smoothstep(BAND_FROM, BAND_FULL, mid)
    glow = np.maximum(mid - BLACK, 0.0)
    level = exposure * glow / (1.0 + glow / KNEE)
    wide = np.maximum(blur(lum, WIDE_DEG) - BLACK, 2e-4)
    level = level * np.clip(glow / wide, 0.1, 4.0) ** ((GAIN_WIDE - 1.0) * band)
    to_mid = np.clip(np.maximum(fine - BLACK, 0.0) / np.maximum(mid - BLACK, 2e-4), 0.0, 3.0) ** (1.0 + (GAIN_MID - 1.0) * band)
    to_fine = np.clip(np.maximum(lum - BLACK, 0.0) / np.maximum(fine - BLACK, 2e-4), 0.0, 3.0)
    to_fine = (1.0 - band) * (1.0 + HALO_GRAIN * (to_fine - 1.0)) + band * to_fine ** GAIN_FINE
    shown = level * to_mid * np.maximum(to_fine, 0.0)
    shown *= np.clip(blur(level, KEEP_DEG) / np.maximum(blur(shown, KEEP_DEG), 1e-6), *KEEP_RANGE)
    shown = np.maximum(shown - BAND_BLACK * STEP / SHOWN_GAIN * band, 0.0)
    top = CEILING * STEP / SHOWN_GAIN
    shown = np.where(shown > 0.6 * top, 0.6 * top + 0.4 * top * (1.0 - np.exp(-(shown - 0.6 * top) / (0.4 * top))), shown)
    hue = np.clip(strip / np.maximum(lum, 1e-6)[..., None], 0.25, 4.0) ** TINT_KEEP
    hue /= (hue @ LUMA)[..., None]
    halo = np.array(HALO_TINT)
    rgb = shown[..., None] * hue * (halo + (np.array(tint) - halo) * band[..., None])
    sin_lat = np.abs((np.arange(HEIGHT) + 0.5) / HEIGHT - 0.5) * 2.0 * SIN_LAT_MAX
    return rgb * (1.0 - smoothstep(FADE_SIN[0], FADE_SIN[1], sin_lat))[:, None, None]


def write_image(name, rgb, path, file_format):
    h, w = rgb.shape[:2]
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[..., :3] = rgb
    image = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=file_format == 'OPEN_EXR')
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(np.flipud(rgba).ravel())
    image.update()
    image.filepath_raw = str(path)
    image.file_format = file_format
    image.save()
    bpy.data.images.remove(image)


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=WORKSPACE / '.local/starship-earth/maps/galaxy.exr')
    parser.add_argument('--exposure', type=float, default=EXPOSURE)
    parser.add_argument('--tint', type=lambda s: [float(v) for v in s.split(',')], default=list(TINT))
    parser.add_argument('--preview', type=Path, help='Optional half-size gamma preview PNG (display only)')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == SOURCE_SHA256, 'Source differs from its pin: %s' % args.source
    strip = to_strip(read_source(args.source.resolve()))
    graded = grade(strip, args.exposure, args.tint)
    # write_image flips rows for bpy; to_strip's row 0 is sin lat -0.6, stored top-row-first as the old strip was.
    write_image('galaxy', (graded * SCALE).astype(np.float32), output, 'OPEN_EXR')
    if args.preview:
        small = graded.reshape(HEIGHT // 2, 2, WIDTH // 2, 2, 3).mean(axis=(1, 3))
        write_image('galaxy preview', np.clip(small / graded.max(), 0, 1) ** (1 / 2.2), args.preview.resolve(), 'PNG')
    lat = np.abs(np.degrees(np.arcsin((np.arange(HEIGHT) + 0.5) / HEIGHT * 2.0 * SIN_LAT_MAX - SIN_LAT_MAX)))
    near = graded[lat < 5]
    stats = {"linear_max": graded.max(axis=(0, 1)).tolist(), "band_median_luma": float(np.median(near @ LUMA)),
             "blue_over_red": float(near[..., 2].sum() / near[..., 0].sum()), "scale": SCALE, "exposure": args.exposure, "tint": args.tint,
             "level_by_abs_lat": {str(lo): float(np.median(graded[(lat >= lo) & (lat < lo + 5)] @ LUMA)) for lo in range(0, 35, 5)}}
    receipt = {"file": output.name, "size": [WIDTH, HEIGHT], "source": args.source.name,
               "mapping": {"u": "galactic longitude, lon = (u - .5)*360 deg, centre at u = .5", "v": "sin(lat)/1.2 + .5 (row 0 = sin lat -0.6)", "band_centre": "latitude 0"},
               "grade": {"black": BLACK, "knee": KNEE, "tint_keep": TINT_KEEP, "fade_sin": FADE_SIN, "halo_tint": HALO_TINT, "scales_deg": [MID_DEG, FINE_DEG, WIDE_DEG, KEEP_DEG],
                         "gains": [GAIN_MID, GAIN_FINE, GAIN_WIDE], "band": [BAND_FROM, BAND_FULL], "halo_grain": HALO_GRAIN, "keep_range": KEEP_RANGE, "band_black_steps": BAND_BLACK, "ceiling_steps": CEILING},
               "stats": stats, "blender": bpy.app.version_string}
    (output.parent / 'galaxy-preparation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('GALAXY_OK ' + json.dumps({"output": str(output), **stats}))


main()
