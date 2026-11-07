"""Build the Observation Deck's star mesh (stars.dat) from real stars, in tiers.

Run with the workspace venv (numpy only). The Yale catalogue and the NASA-derived arrays are untrusted data: run this with
python -I from another folder, it only parses fixed-width numbers and plain arrays.
    python -I prepare_stars.py [--output <dir>] [--yale <ybsc5.gz>] [--extracted <npz>] [--peaks <npz>] [--lane <npy>] [--open-sky <npz>] [--shader <space.gdshader>] [--chunks N] [--clouds N] [--dust N]

Sources, brightest first:
- Yale Bright Star Catalog, 5th revised ed.: true J2000 positions, V and B-V, to about V 6.5. Every star at V 6.5 or brighter comes from it.
- stars_extracted.npz: peaks of NASA's Deep Star Maps 2020 (starmap minus milkyway), magnitudes by rank. Stars fainter than Yale; off the band to the
  density picked by eye, in the band further down.
- mw_peaks.npz (prepare_mw_peaks.py): every local maximum of the milkyway map within 20 deg of the plane, with the star-cloud level read at each one. The clouds and
  the dust are thinned from these by the real local density, so they stay real peaks at real places and fall where the light is.
- lane_field.npy (prepare_dust.py): the share of light the dust map blocks, at the Milky Way strip's own size.
- shown_glow.npy (prepare_dust.py): the band as the sky shader shows it, glow x dust x black point, smoothed by about .25 deg. Dust and cloud stars are thinned by it, so they hang on clouds and not on black.
open_sky.npz says which directions the glass can ever show. Stars fainter than Yale outside it are not in the mesh.

Tiers, all in one file. The shader needs only the amplitude code; everything that depends on a star's place was settled here:
- hero: brightest catalogue stars. A tight core and, from SKIRT_FROM up, a faint wide skirt.
- mid: catalogue and clouds. A tight kernel, trimmed to where it still rounds to a 10-bit step.
- dust: amplitude under DUST_TOP. The kernel floor, trimmed the same way.

Output stars.dat, read by starship_room.gd star_mesh_chunks(): u32 magic 'STR2', u32 chunk count, u32 vertex count, then per chunk u32 first vertex, u32 vertices,
vec3 aabb min, vec3 aabb max, then vec3 float32 position x vertices, RGBA8 x vertices. No index: each star is three unique vertices. A vertex holds a corner of the
star's triangle as a direction, so the vertex stage does no geometry but the projection. The limb test and its fade are baked: a star behind the disc is not in the
file and a star near the limb has its dimmed amplitude and its reddened tint. RGB is the star's tint, A its amplitude, ln(amp / AMP_MIN) / ln(AMP_MAX / AMP_MIN).

Room space comes from the galactic basis and planet in space.gdshader, so stars and Milky Way are one sky: change the basis there, then rerun this. The receipt records the basis, and check_integration.py refuses a mesh on another one.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != HERE]

import numpy as np

WORKSPACE = Path(__file__).resolve().parents[2]
SHADER = WORKSPACE / 'app/starship/space.gdshader'
YALE = WORKSPACE / 'downloads/yale/ybsc5.gz'
EXTRACTED = WORKSPACE / 'work/stars_extracted.npz'
OPEN_SKY = WORKSPACE / 'work/open_sky.npz'
PEAKS = WORKSPACE / 'work/mw_peaks.npz'
LANE = WORKSPACE / 'work/lane_field.npy'
GLOW = WORKSPACE / 'work/shown_glow.npy'
PINS = {'yale': '3dc44b1e90be8fbe5bcc7656032560f51275f985c7e3f783c9028e1838ec7bed', 'extracted': '2e202098af33e2013964bec3d0092da8ce8c892055e3816c74f5405f6441aff4',
        'open_sky': '33735e4e06910a20e713c3eca1b14e476cb7e0583f6a67707803f2e4fdfcbe70',
        'peaks': '6c98ae84d3f5d35113ff0a6b43c1ff546043736f4f9da553c666f224e63e4cf7', 'lane': '370eb4a36fdaeb4bda223ea9b72544e56b93b1251ad09d2fee8a36e1db716ef8', 'glow': 'a34e8fcc1e00228d67ea2fed7f70907b7eb6423b8d16529442ae73af87a295de'}
MAGIC = 0x32525453  # 'STR2'
# The one number picked by eye: mesh stars per deg^2 outside the band (|b| >= 10 deg).
DENSITY = 0.6
# A hero's peak falls by half when it lands between pixels, so the top of the ladder sits past where 0.5.13 stopped (.6, code 184 at best, 135 at worst).
CAP = 1.4
# The brightness ladder, V to linear amplitude: straight lines in log amplitude between these knots, off the band and on it. The density limit's V is the last knot, at LADDER_FLOOR.
LADDER = ((0.8, 1.4), (4.2, 0.26), (5.2, 0.11), (6.5, 0.04), (7.0, 0.025))
LADDER_FLOOR = 0.0105
# Real map stars fainter than the off-band limit, kept only near the plane on the glass.
BAND_REAL_MAG = 8.6
BAND_REAL_B = 15.0
BAND_REAL_FLOOR = 0.0065
# Inside dark lanes real foreground stars remain: a map star is dropped with probability LANE_DROP * lane and dimmed by LANE_DIM * lane. Yale's stars stay as they are.
LANE_DROP = 0.85
LANE_DIM = 0.5
# Clouds and dust: how many, the map level that means none and the level that means full, and how hard the light concentrates them.
CLOUD_STARS = 18000
DUST_STARS = 22000
RHO_LO = 0.009
RHO_HI = 0.055
CLOUD_POWER = 2.2
DUST_POWER = 1.7
ENVELOPE_B = 12.0
# Where the shown band has no light a star still has this share of its chance: real foreground stars. Full chance from GLOW_HI up, in linear luminance. One 10-bit step is .00196.
GLOW_LO = 0.0006
GLOW_HI = 0.008
DUST_GAP = 0.04
CLOUD_GAP = 0.15
# Amplitude ladder of the clouds and the dust, a power law by rank of the map's own peak height.
CLOUD_TOP, CLOUD_FLOOR, CLOUD_SLOPE = 0.18, 0.008, 1.0
DUST_TOP, DUST_FLOOR, DUST_SLOPE = 0.0065, 0.0045, 1.35
# Kernel half-width in radians by tier, as tight as the per-star stability test allows at the view centre: FWHM .12 to .127 deg against .138. The .0027 floor of James et al. 2015 went past the 2x limit there, and dust at .0034 did on flux. A tighter MID_R reads crisper and twinkles more.
DUST_R = 0.0036
MID_R = 0.0034
HERO_R = 0.0034
HERO_R_TOP = 0.0031
# Stars from here up have a skirt: one triangle of SKIRT_R radius holds the core and the wings. Must match stars.gdshader.
SKIRT_FROM = 0.4
SKIRT_R = 0.0105
# A star's triangle stops where its kernel rounds to nothing: t = min(T0 + T1 code, T2 + T3 code), never under the exact cut for half a 10-bit step. Must match stars.gdshader.
TRIM = (0.27, 0.873, 0.485, 0.339)
# Air near the limb, as stars.gdshader used to do per vertex.
LIMB_FADE_DEG = 3.0
LIMB_RED = np.array([1.0, 0.42, 0.20])
AMP_MIN = 0.001
AMP_MAX = 1.4
# With 116,604 for the rest of the room and objects at most 6,000, this sits under the room limit of 180,000 in test_starship_integration.gd, which is what stands in for GPU time.
MAX_STARS = 57000
EQUATORIAL_TO_GALACTIC = np.array([[-0.0548755604, -0.8734370902, -0.4838350155],
                                   [0.4941094279, -0.4448296300, 0.7469822445],
                                   [-0.8676661490, -0.1980763734, 0.4559837762]])
YALE_STARS = 9096
YALE_NEAR_DEG = 0.1
YALE_FAINTEST = 6.5
YALE_MERGE_DEG = 0.05
TINT_KEEP = 0.7
# Band stars: the map's peak colour by rank onto this spread of tints, warm to hot. Real order, not the map's warm cast.
BAND_TINT = ((0.0, (1.0, 0.82, 0.64)), (0.08, (1.0, 0.92, 0.82)), (0.15, (0.62, 0.79, 1.0)), (0.70, (0.50, 0.72, 1.0)), (1.0, (0.42, 0.66, 1.0)))
# The clouds and the dust, colder still, so grain on a blue cloud reads as part of it and not as white salt on top.
BAND_COLD = np.array([0.78, 0.95, 1.22])
SEED = 20261103
# Chunk boxes sit at this distance (STAR_BOX in starship_room.gd) and carry a margin for the head's reach.
BOX = 1000.0
BOX_MARGIN = 12.0


def shader_vec3(source, name):
    match = re.search(r'uniform\s+vec3\s+' + name + r'\s*=\s*vec3\(([^)]*)\)', source)
    assert match, 'space.gdshader has no default for ' + name
    return np.array([float(v) for v in match.group(1).split(',')])


def shader_float(source, name):
    match = re.search(r'uniform\s+float\s+' + name + r'\s*=\s*([-0-9.eE+]+)', source)
    assert match, 'space.gdshader has no default for ' + name
    return float(match.group(1))


def field(line, start, end):
    try:
        return float(line[start - 1:end])
    except ValueError:
        return None


def read_yale(path):
    rows = []
    names = []
    with gzip.open(path, 'rt', encoding='ascii', errors='replace') as stream:
        for line in stream:
            parts = [field(line, *span) for span in ((76, 77), (78, 79), (80, 83), (85, 86), (87, 88), (89, 90), (103, 107))]
            if any(p is None for p in parts):
                continue
            ra = math.radians(15.0 * (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0))
            dec = (parts[3] + parts[4] / 60.0 + parts[5] / 3600.0) * (-1.0 if line[83] == '-' else 1.0)
            dec = math.radians(dec)
            bv = field(line, 110, 114)
            rows.append((math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec), parts[6], 0.6 if bv is None else bv))
            names.append('HR %d %s' % (int(line[0:4]), ' '.join(line[4:14].split())))
    table = np.array(rows, np.float64)
    assert len(table) == YALE_STARS, 'Unexpected Yale row count: %d' % len(table)
    return table[:, :3], table[:, 3], table[:, 4], np.array(names)


def merge_close(d, v, bv, names):
    order = np.argsort(v, kind='stable')
    d, v, bv, names = d[order], v[order], bv[order], names[order]
    flux = 10.0 ** (-0.4 * v)
    keep = np.ones(len(v), bool)
    near = math.cos(math.radians(YALE_MERGE_DEG))
    for i in range(len(v)):
        if keep[i]:
            with_it = np.nonzero(keep[i + 1:] & (d[i + 1:] @ d[i] > near))[0] + i + 1
            flux[i] += flux[with_it].sum()
            keep[with_it] = False
    return d[keep], -2.5 * np.log10(flux[keep]), bv[keep], names[keep], int((~keep).sum())


def bv_tint(bv):
    kelvin = 4600.0 * (1.0 / (0.92 * np.clip(bv, -0.3, 1.8) + 1.7) + 1.0 / (0.92 * np.clip(bv, -0.3, 1.8) + 0.62))
    stops = [3500.0, 5800.0, 8500.0, 20000.0]
    tint = np.stack([np.interp(kelvin, stops, channel) for channel in ((1.0, 1.0, 0.85, 0.62), (0.62, 0.92, 0.90, 0.74), (0.35, 0.82, 1.0, 1.0))], axis=1)
    return tint * TINT_KEEP + (1.0 - TINT_KEEP)


def map_tint(rgb):
    ratio = np.log2(np.clip(rgb[:, 2] / np.maximum(rgb[:, 0], 1e-6), 0.25, 4.0))
    return bv_tint(0.6 - 0.55 * ratio)


def band_tint(rgb):
    """The map is warm all over. Its peak colours keep their order and land on a real population's spread: a few warm stars, most blue-white."""
    ratio = np.log(np.maximum(rgb[:, 2], 1e-6) / np.maximum(rgb[:, 0], 1e-6))
    # The densest clouds are the warmest in the map, because it blends real stars into a warm mean; half of the rank comes from each star's own hash, so warm stars do not pile up there.
    spread = np.modf(np.abs(rgb @ np.array([9973.0, 7919.0, 6101.0])) * 1000.0)[0]
    score = np.argsort(np.argsort(ratio, kind='stable'), kind='stable') / max(len(ratio) - 1, 1) + spread
    rank = np.argsort(np.argsort(score, kind='stable'), kind='stable') / max(len(ratio) - 1, 1)
    stops = [s for s, _ in BAND_TINT]
    return np.stack([np.interp(rank, stops, [c[i] for _, c in BAND_TINT]) for i in range(3)], 1)


def load_stars(yale, extracted):
    assert Path(yale).exists(), 'The brightest stars come from the Yale catalogue, and it is not at %s' % yale
    data = np.load(extracted)
    d = data['d'].astype(np.float64)
    m = data['m'].astype(np.float64)
    equatorial, v, bv, names = read_yale(yale)
    yd, v, bv, names, merged = merge_close(equatorial @ EQUATORIAL_TO_GALACTIC.T, v, bv, names)
    faint = np.nonzero(m > YALE_FAINTEST)[0]
    near = math.cos(math.radians(YALE_NEAR_DEG))
    clear = np.ones(len(faint), bool)
    for start in range(0, len(faint), 4000):
        clear[start:start + 4000] = (d[faint[start:start + 4000]] @ yd.T).max(axis=1) < near
    keep = faint[clear]
    tint = np.concatenate([bv_tint(bv), map_tint(data['rgb'][keep].astype(np.float64))])
    is_yale = np.concatenate([np.ones(len(v), bool), np.zeros(len(keep), bool)])
    counts = {"yale_rows": YALE_STARS, "yale_stars_after_merging": len(v), "yale_rows_merged": merged, "map_peaks": len(d), "map_peaks_on_a_yale_star": int((~clear).sum()), "map_peaks_used": len(keep)}
    return np.concatenate([yd, d[keep]]), np.concatenate([v, m[keep]]), tint, np.concatenate([names, np.full(len(keep), '')]), is_yale, data['rgb'][keep].astype(np.float64), counts


def magnitude_limit(d, m, density):
    outside = np.abs(d[:, 2]) >= math.sin(math.radians(10.0))
    area = 41252.96 * (1.0 - math.sin(math.radians(10.0)))
    wanted = int(round(density * area))
    ranked = np.sort(m[outside])
    assert wanted < len(ranked), 'Density beyond the source list'
    return float(ranked[wanted])


def amplitude(m, limit):
    knots = list(LADDER) + [(limit, LADDER_FLOOR)]
    return np.minimum(np.exp(np.interp(m, [k[0] for k in knots], np.log([k[1] for k in knots]))), CAP)


def on_open_sky(room, path):
    mask = np.load(path)['open']
    lon = np.arctan2(room[:, 0], -room[:, 2])
    lat = np.arcsin(np.clip(room[:, 1], -1.0, 1.0))
    h, w = mask.shape
    return mask[np.clip(((lat / np.pi + 0.5) * h).astype(int), 0, h - 1), ((lon / (2.0 * np.pi) + 0.5) * w).astype(int) % w]


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lane_at(gal, lane_path):
    """Dark-lane field at galactic directions, from a strip-sized array (same u, v as the Milky Way map)."""
    field_ = np.load(lane_path, mmap_mode='r')
    h, w = field_.shape
    x = ((np.arctan2(gal[:, 1], gal[:, 0]) / (2.0 * np.pi) + 0.5) * w).astype(int) % w
    y = np.clip(((gal[:, 2] / 1.2 + 0.5) * h).astype(int), 0, h - 1)
    # DUST's lane_field.npy holds the blocked share as uint8; mine is float.
    scale = 255.0 if field_.dtype == np.uint8 else 1.0
    return np.asarray(field_[y, x]).astype(np.float64) / scale * (np.abs(gal[:, 2]) < 0.6)


def thin(p, count, rng):
    """Weighted choice without replacement of `count` from probabilities p, reproducible (exponential race)."""
    keys = rng.random(len(p)) ** (1.0 / np.maximum(p, 1e-12))
    return np.argsort(-keys, kind='stable')[:count]


def ladder_by_rank(score, top, floor, slope):
    """Amplitude by rank of score under a power law, N(>A) proportional to A^-slope, from floor to top."""
    rank = np.argsort(np.argsort(-score, kind='stable'), kind='stable')
    u = (rank + 0.5) / len(score)
    return np.minimum((floor ** -slope * u + top ** -slope * (1.0 - u)) ** (-1.0 / slope), top)


def band_population(peaks, lane_path, glow_path, usable, clouds, dust, rng):
    """Clouds and dust thinned from the real peaks: more where the map is bright, none in the deep of a lane or far off the plane."""
    b = peaks['b'].astype(np.float64)
    cloud = peaks['cloud'].astype(np.float64)
    broad = peaks['broad'].astype(np.float64)
    ex = peaks['ex'].astype(np.float64)
    lane = lane_at(peaks['gal'].astype(np.float64), lane_path)
    usable = usable & (ex > 0)
    glow = np.load(glow_path, mmap_mode='r')
    gal = peaks['gal'].astype(np.float64)
    gx = ((np.arctan2(gal[:, 1], gal[:, 0]) / (2.0 * np.pi) + 0.5) * glow.shape[1]).astype(int) % glow.shape[1]
    gy = np.clip(((gal[:, 2] / 1.2 + 0.5) * glow.shape[0]).astype(int), 0, glow.shape[0] - 1)
    shown = np.clip((np.asarray(glow[gy, gx]).astype(np.float64) - GLOW_LO) / (GLOW_HI - GLOW_LO), 0.0, 1.0)
    level = np.clip((cloud - RHO_LO) / (RHO_HI - RHO_LO), 0.0, 1.0)
    relief = np.clip(cloud / np.maximum(broad, 1e-4), 0.6, 1.6)
    envelope = np.exp(-0.5 * (b / ENVELOPE_B) ** 4)
    weight = lambda power, cut: level ** power * relief ** 1.5 * (1.0 - cut * lane) ** 2 * envelope * usable
    # Clouds take the strongest peaks of the densest places.
    chosen_cloud = thin(weight(CLOUD_POWER, 0.98) * ex * (CLOUD_GAP + (1.0 - CLOUD_GAP) * shown), clouds, rng)
    free = np.ones(len(b), bool)
    free[chosen_cloud] = False
    chosen_dust = thin(weight(DUST_POWER, 0.92) * free * (DUST_GAP + (1.0 - DUST_GAP) * shown), dust, rng)
    return chosen_cloud, chosen_dust


def kernel_radius(amp):
    """Half-width of the kernel by tier. The tone curve is near a log, so a bright star shows wider: the top goes tighter."""
    r = np.where(amp < DUST_TOP, DUST_R, MID_R)
    return np.where(amp >= 0.1, HERO_R + (HERO_R_TOP - HERO_R) * smooth(0.1, 0.6, amp), r)


def build(args):
    shader = args.shader.read_text()
    x, pole, z = (shader_vec3(shader, name) for name in ('galaxy_x', 'galaxy_pole', 'galaxy_z'))
    planet = shader_vec3(shader, 'planet_direction')
    planet /= np.linalg.norm(planet)
    limb = math.degrees(math.asin(1.0 / shader_float(shader, 'planet_distance')))
    to_room = lambda g: g[:, :1] * x + g[:, 1:2] * z + g[:, 2:3] * pole
    d, m, tint, names, is_yale, map_rgb, counts = load_stars(args.yale, args.extracted)
    limit = magnitude_limit(d, m, args.density)
    room = to_room(d)
    bb = np.degrees(np.arcsin(np.clip(d[:, 2], -1.0, 1.0)))
    seen = on_open_sky(room, args.open_sky)
    keep = (m <= limit) & (is_yale | seen)
    extra = (~is_yale) & (m > limit) & (m <= BAND_REAL_MAG) & seen & (np.abs(bb) < BAND_REAL_B)
    rng = np.random.default_rng(SEED)
    lane_cat = lane_at(d, args.lane)
    amp = amplitude(m, limit)
    amp[extra] = np.exp(np.interp(m[extra], [limit, BAND_REAL_MAG], np.log([LADDER_FLOOR, BAND_REAL_FLOOR])))
    use = keep | extra
    gone = (~is_yale) & (rng.random(len(m)) < LANE_DROP * lane_cat)
    use &= ~gone
    amp = np.where(is_yale, amp, amp * (1.0 - LANE_DIM * lane_cat))
    # Band stars of the map list get the real population's tints.
    faint_rows = np.nonzero(~is_yale)[0]
    inband = np.abs(bb[faint_rows]) < BAND_REAL_B
    tint = tint.copy()
    tint[faint_rows[inband]] = band_tint(map_rgb[inband])
    peaks = np.load(args.peaks)
    groom = to_room(peaks['gal'].astype(np.float64))
    usable = on_open_sky(groom, args.open_sky) & (groom @ planet < math.cos(math.radians(limb)))
    chosen_cloud, chosen_dust = band_population(peaks, args.lane, args.glow, usable, args.clouds, args.dust, rng)
    pop = np.concatenate([chosen_cloud, chosen_dust])
    pop_tint = band_tint(peaks['rgb'][pop].astype(np.float64)) * BAND_COLD
    ex = peaks['ex'].astype(np.float64)
    amp_cloud = ladder_by_rank(ex[chosen_cloud], CLOUD_TOP, CLOUD_FLOOR, CLOUD_SLOPE)
    amp_dust = ladder_by_rank(ex[chosen_dust], DUST_TOP, DUST_FLOOR, DUST_SLOPE)
    all_room = np.concatenate([room[use], groom[pop]])
    all_amp = np.concatenate([amp[use], amp_cloud, amp_dust])
    all_tint = np.concatenate([tint[use], pop_tint])
    # Limb: a star behind the disc is not drawn, one over the last LIMB_FADE_DEG dims and reddens.
    above = np.degrees(np.arccos(np.clip(all_room @ planet, -1.0, 1.0))) - limb
    air = smooth(0.0, LIMB_FADE_DEG, above)[:, None]
    all_amp = all_amp * air[:, 0] ** 2
    all_tint = all_tint * (LIMB_RED + (1.0 - LIMB_RED) * air)
    alive = (above > 0.0) & (all_amp >= AMP_MIN)
    order = np.argsort(-all_amp, kind='stable')
    order = order[alive[order]]
    brightest = []
    for i in np.argsort(m)[:20]:
        brightest.append({"star": str(names[i]), "v": round(float(m[i]), 2), "amp": round(float(amp[i]), 4), "az": round(math.degrees(math.atan2(room[i, 0], -room[i, 2])), 1), "el": round(math.degrees(math.asin(room[i, 1])), 1), "in_mesh": bool(use[i])})
    info = dict(counts=counts, limit=limit, catalogue=int(use.sum()), band_real_extra=int((extra & use).sum()), lane_dropped=int((gone & (keep | extra)).sum()), clouds=len(chosen_cloud), dust=len(chosen_dust), brightest=brightest)
    return all_room[order], all_amp[order], all_tint[order], info


def code_of(amp):
    return np.clip(np.round(np.log(np.maximum(amp, AMP_MIN) / AMP_MIN) / math.log(AMP_MAX / AMP_MIN) * 255.0), 0, 255)


def skirted(amp):
    # As stars.gdshader decides it, from the code, not the true amplitude.
    return AMP_MIN * np.exp(code_of(amp) / 255.0 * math.log(AMP_MAX / AMP_MIN)) >= SKIRT_FROM


def corners_of(room, amp):
    """The triangle of each star around the unit circle its kernel lives in. Skirted stars get the skirt's radius; others stop where the kernel rounds to nothing."""
    side = np.cross(room, np.where(np.abs(room[:, 1:2]) < 0.9, np.array([[0.0, 1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]])))
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    up = np.cross(room, side)
    c = code_of(amp) / 255.0
    trim = np.minimum(TRIM[0] + TRIM[1] * c, TRIM[2] + TRIM[3] * c)
    radius = np.where(skirted(amp), SKIRT_R, kernel_radius(amp) * trim)
    corners = np.empty((len(room), 3, 3))
    for i, (qx, qy) in enumerate(((-1.7320508, -1.0), (1.7320508, -1.0), (0.0, 2.0))):
        corners[:, i] = room + (side * qx + up * qy) * radius[:, None]
    return corners, radius


def chunk_of(room, cells):
    """Cube-face cells of direction, cells x cells on each face."""
    a = np.abs(room)
    face = np.argmax(a, axis=1)
    row = np.arange(len(room))
    major = a[row, face]
    u = room[row, (face + 1) % 3] / major
    v = room[row, (face + 2) % 3] / major
    iu = np.clip(((np.arctan(u) / (np.pi / 4) + 1.0) * 0.5 * cells).astype(int), 0, cells - 1)
    iv = np.clip(((np.arctan(v) / (np.pi / 4) + 1.0) * 0.5 * cells).astype(int), 0, cells - 1)
    sign = (room[row, face] < 0).astype(int)
    return (face * 2 + sign) * cells * cells + iu * cells + iv


def write_mesh(path, room, amp, tint, cells):
    count = len(room)
    assert count <= MAX_STARS, 'Too many stars: %d' % count
    corners, radius = corners_of(room, amp)
    colour = np.empty((count, 4), np.uint8)
    colour[:, :3] = np.round(np.clip(tint, 0.0, 1.0) * 255.0)
    colour[:, 3] = code_of(amp)
    ids = chunk_of(room, cells) if cells > 0 else np.zeros(count, int)
    # Skirted stars are few and wide: their own chunk, first, drawn whenever any part of the sky is.
    ids = np.where(skirted(amp), -1, ids)
    order = np.lexsort((-amp, ids))
    table = []
    first = 0
    for value in np.unique(ids):
        members = order[ids[order] == value]
        pts = corners[members].reshape(-1, 3) * BOX
        lo, hi = pts.min(axis=0) - BOX_MARGIN, pts.max(axis=0) + BOX_MARGIN
        table.append((first * 3, len(members) * 3, lo, hi))
        first += len(members)
    with open(path, 'wb') as out:
        out.write(struct.pack('<III', MAGIC, len(table), count * 3))
        for start, n, lo, hi in table:
            out.write(struct.pack('<II6f', start, n, *lo, *hi))
        out.write(corners[order].reshape(-1, 3).astype('<f4').tobytes())
        out.write(np.repeat(colour[order], 3, axis=0).tobytes())
    return order, table, radius


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--density', type=float, default=DENSITY)
    parser.add_argument('--output', type=Path, default=Path('.'))
    parser.add_argument('--shader', type=Path, default=SHADER)
    parser.add_argument('--yale', type=Path, default=YALE)
    parser.add_argument('--extracted', type=Path, default=EXTRACTED)
    parser.add_argument('--peaks', type=Path, default=PEAKS)
    parser.add_argument('--lane', type=Path, default=LANE)
    parser.add_argument('--glow', type=Path, default=GLOW)
    parser.add_argument('--open-sky', type=Path, default=OPEN_SKY)
    parser.add_argument('--clouds', type=int, default=CLOUD_STARS)
    parser.add_argument('--dust', type=int, default=DUST_STARS)
    parser.add_argument('--chunks', type=int, default=3, help='cells per cube face; 0 for one chunk')
    parser.add_argument('--set', action='append', default=[], help='NAME=VALUE: override a constant for a trial')
    parser.add_argument('--only', choices=('dust', 'nodust'), help='for the per-star stability test, which can only follow lonely stars')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    for item in args.set:
        name, value = item.split('=', 1)
        globals()[name] = eval(value, {'__builtins__': {}})
    for name, digest in PINS.items():
        assert hashlib.sha256(getattr(args, name).read_bytes()).hexdigest() == digest, 'Source differs from its pin: %s' % getattr(args, name)
    room, amp, tint, info = build(args)
    if args.only:
        pick = amp < DUST_TOP if args.only == 'dust' else amp >= DUST_TOP
        room, amp, tint = room[pick], amp[pick], tint[pick]
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / 'stars.dat'
    order, table, radius = write_mesh(path, room, amp, tint, args.chunks)
    sky = args.shader.read_text()
    receipt = dict(info, basis={n: [round(float(v), 5) for v in shader_vec3(sky, n)] for n in ('galaxy_x', 'galaxy_pole', 'galaxy_z')}, stars=len(room), triangles=len(room), bytes=path.stat().st_size, chunks=len(table), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   over={str(t): int((amp >= t).sum()) for t in (.0028, .0065, .012, .03, .05, .1, .135, .25, .5)}, skirted=int(skirted(amp).sum()), amp_range=[float(amp.min()), float(amp.max())])
    (args.receipt or args.output / 'stars-preparation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('STARS_OK ' + json.dumps({k: v for k, v in receipt.items() if k not in ('brightest', 'counts')}))


if __name__ == '__main__':
    main()
