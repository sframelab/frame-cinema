"""Build the Observation Deck's two Milky Way maps from NASA's real one: galaxy (smooth glow of unresolved stars) and dust (what stands in front of it).

Run with the venv Python, from another folder, -I. Data files are parsed only:
    python -I -B prepare_dust.py --work <folder holding mw8kgal.npy, band_stars.npz> --out <folder>

Input: NASA/Goddard SVS Deep Star Maps 2020, milkyway, 8192x4096, galactic plate carree, as mw8kgal.npy (top row +b, l increasing to the left).
Output: galaxy.raw, float32 RGB, 4096x1024, rows linear in sin b, row 0 = -.6, u = l / 360 + .5, the same mapping as prepare_galaxy.py and stored 1 / galaxy_exposure up.
        dust.raw, uint8 RG, 8192x1024, the same but rows |sin b| < .3. R: optical depth, .2 per unit, zero at .5, below that the clumps that stand out of the band.
        G: fine grain of faint stars, zero at .5. lane_field.npy and shown_glow.npy: for the star mesh. Pack the two raw files with pack_final.gd: galaxy.res (BC6H) and dust.res (BC5).
The band's route, its big lanes and its clouds are the map's. filament_warp moves edges by up to about a third of a degree, with fixed-seed noise, so round contours tear.
"""
import argparse, hashlib, math
from pathlib import Path
import cv2
import numpy as np

cv2.setNumThreads(6)
LUMA = np.array([.2126, .7152, .0722], np.float32)
# The basis band_stars.npz was written on, 2026-11-02. The list holds room directions on this basis, so these stay as they are whatever space.gdshader's basis is now: nothing here depends on the sky's turn.
GX = np.array([0.1586, 0.4067, -0.8997]); GP = np.array([-0.9726, 0.2210, -0.0716]); GZ = np.array([-0.1697, -0.8864, -0.4307])
SOURCE_SHA256 = 'a12fbea3c65f36fe29ceab0b1cd2ac49df77b6518788664a3bdd48c63a4049c4'
BAND_STARS_SHA256 = '43c2735e6bd2e730fba1feaf4925540d4188edcc81633a705fe275bda4fc8591'
SIN_MAX = .6
W8, H8 = 8192, 2048
PXD = W8 / 360.0
ROWS_ISO = int(round(H8 * PXD * .0336))   # rows that make pixels square at b = 0
LO, HI = 3e-4, .5                         # log range of the 8-bit working copy
LN = math.log(HI / LO)
STEP = 2 / 1023
EXPOSURE = .1875                          # galaxy_exposure in space.gdshader
DUST_DEPTH = .8                           # DUST_DEPTH in space.gdshader: how much of the stored optical depth the sky uses. It is one number there, so it needs no new map. Here it only feeds the two fields for the star mesh
GRAIN_DEPTH, TINT_DUST, GLOW_BLACK = 3.0, (.8, 1.0, 1.22), .008798   # the same three constants of space.gdshader
TONE_TOP, TONE_KNEE, BAND_TINT = 1.17, .017, (.60, .86, 1.08)   # the same three of space.gdshader: mids down, top kept, less red
GLOW_WANDER = 1.6                         # the same in space.gdshader: slow waves in the black point, on the galactic basis, so the band's edge has no long straight run
# Grade
TINT = np.array([.50, 1.03, 2.25], np.float32)   # band hue. B/R about 2.3-2.7 after the dust's own colour
E, KNEE = .62, .075                       # level of the glow, and the knee that holds the bulge under the film's attention
SPLIT, SPLIT_F = 3.0, .75                 # deg: the glow keeps what is wider than SPLIT; dust has two scales, split there and at SPLIT_F
H_FINE, H_GLOW = 6, 12                    # non-local means strength on the log map: edges stay, grain goes
POST = .03                                # deg, takes the flat-plateau facets off the denoised map
FILAMENT = .25                            # scale of filament_warp's offsets
G_LANE, G_KNOT, G_MID_LANE, G_MID_KNOT, G_FF = 3.4, 3.0, 2.6, 2.2, 1.5   # powers on the map's own contrast, by scale, and for compact knots over a .3 deg surround
T_CVX, T_CAP = .35, 2.0                   # how brightening bends: convex, then a soft cap in optical depth
BLACK_OFFLINE = .5                        # steps taken off the glow before the band edge
SIGMA_B, FLOOR_C, ISO_P = 8.0, .06, 1.0   # band edge: follows the map's isophotes, inside a wide gaussian in latitude
HUE_K, HUE_LARGE = 1.6, .35               # real hue against its own 8 deg mean, and how much of that mean stays
GRAIN_S, GRAIN_C, GRAIN_W1, GRAIN_LIM = .06, 1.0, .25, .8   # deg, and weights: clumps of faint stars more than their texel-level grain


def enc(a):
    return np.clip(np.log(np.maximum(a, LO) / LO) / LN * 255, 0, 255).astype(np.uint8)


def dec(c):
    return np.exp(np.asarray(c, np.float32) / 255 * LN) * LO


def gs(a, deg):
    """Gaussian in degrees at the band on a strip whose rows are sin b. Wraps in longitude."""
    h, w = a.shape[:2]
    sx = deg * w / 360.0; sy = deg / (1.2 / h * 57.2958)
    pad = int(sx * 4) + 2
    p = np.concatenate([a[:, -pad:], a, a[:, :pad]], 1)
    return cv2.GaussianBlur(p, (0, 0), sigmaX=sx, sigmaY=sy, borderType=cv2.BORDER_REFLECT)[:, pad:-pad]


def to_strip(src, rows):
    h = src.shape[0]
    edges = (np.degrees(np.arcsin((np.arange(rows + 1) / rows - .5) * 2 * SIN_MAX)) + 90) / 180 * h
    total = np.zeros((h + 1,) + src.shape[1:], np.float64)
    total[1:] = np.cumsum(src.astype(np.float64), axis=0)
    low = np.floor(edges).astype(int)
    frac = (edges - low)[:, None, None]
    at = total[low] * (1 - frac) + total[low + 1] * frac
    return ((at[1:] - at[:-1]) / (edges[1:] - edges[:-1])[:, None, None]).astype(np.float32)


def stars_out(strip, band_stars):
    """Printed stars, by the catalogue and by being far over their surround, replaced with a 9 px median of the log map."""
    L = strip @ LUMA
    z = np.load(band_stars)
    room = z['room'].astype(np.float64)
    gx, gp, gz = room @ GX, room @ GP, room @ GZ
    u = (np.arctan2(gz, gx) / (2 * np.pi) + .5) * W8
    v = (gp / 1.2 + .5) * H8
    m = np.zeros((H8, W8), np.uint8)
    ok = (v >= 0) & (v < H8)
    m[v[ok].astype(int), u[ok].astype(int) % W8] = 1
    md = dec(cv2.medianBlur(enc(L), 9))
    mk = cv2.dilate(m, np.ones((3, 3), np.uint8)).astype(bool)
    mk |= L > md * 2.2
    r = np.where(mk, md / np.maximum(L, 1e-6), 1.0)[..., None]
    return strip * r, L * r[..., 0]


def denoise(L, h, tw=5, sw=15, med=3):
    iso = cv2.resize(L, (W8, ROWS_ISO), interpolation=cv2.INTER_AREA)
    n = cv2.fastNlMeansDenoising(enc(iso), None, h=h, templateWindowSize=tw, searchWindowSize=sw)
    if med:
        n = cv2.medianBlur(n, med)
    return cv2.resize(dec(n), (W8, H8), interpolation=cv2.INTER_CUBIC)


def noise2(shape, deg, seed):
    h, w = shape
    r = np.random.default_rng(seed)
    f = 2 ** max(0, int(math.log2(max(deg * w / 360 / 2, 1))))
    sh, sw = h // f + 8, w // f
    n = r.normal(size=(sh, sw)).astype(np.float32)
    sx = deg * w / 360.0 / f; sy = deg / (1.2 / h * 57.2958) / f
    k = int(max(sx, sy) * 4) + 2
    p = np.concatenate([n[:, -k:], n, n[:, :k]], 1)
    p = cv2.GaussianBlur(p, (0, 0), sigmaX=sx, sigmaY=sy, borderType=cv2.BORDER_REFLECT)[:, k:-k]
    if f > 1:
        q = np.concatenate([p[:, -2:], p, p[:, :2]], 1)
        p = cv2.resize(q, ((sw + 4) * f, sh * f), interpolation=cv2.INTER_CUBIC)[:, 2 * f:-2 * f][:h, :w]
    p = p[:h, :w]
    return p / p.std()


def filament_warp(field, scale, seed=7):
    octs = ((.7, .22 * scale), (.28, .11 * scale), (.11, .045 * scale))
    h, w = field.shape[:2]
    ys, xs = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing='ij')
    dx = np.zeros((h, w), np.float32); dy = np.zeros((h, w), np.float32)
    for i, (deg, amp) in enumerate(octs):
        dx += noise2((h, w), deg, seed + 2 * i) * amp * w / 360.0
        dy += noise2((h, w), deg, seed + 2 * i + 1) * amp / (1.2 / h * 57.2958)
    return cv2.remap(field, xs + dx, ys + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def glow(ls_glow, rgb):
    g = gs(ls_glow, SPLIT) * E
    g = g / (1 + g / KNEE)
    g = cv2.resize(g, (4096, 1024), interpolation=cv2.INTER_AREA)
    sb = (np.arange(1024) + .5) / 1024 * 1.2 - .6
    b = np.degrees(np.arcsin(sb))[:, None]
    g = np.maximum(g - BLACK_OFFLINE * STEP, 0)
    ref = gs(g, 5.0)[np.abs(b)[:, 0] < 4].mean(0, keepdims=True)
    iso = np.clip(gs(g, 1.2) / np.maximum(ref, 1e-5), 0, 1.5) ** ISO_P
    g = g * iso * (FLOOR_C + (1 - FLOOR_C) * np.exp(-.5 * (b / SIGMA_B) ** 2))
    t = np.clip((np.abs(sb)[:, None] - .44) / .16, 0, 1)
    g = g * (1 - t ** 2 * (3 - 2 * t))
    hue = rgb / np.maximum(rgb @ LUMA, 1e-6)[..., None]
    near = np.stack([gs(hue[..., i], .4) for i in range(3)], -1)
    wide = np.stack([gs(hue[..., i], 8.0) for i in range(3)], -1)
    col = TINT * np.clip(near / np.maximum(wide, 1e-3), .3, 3) ** HUE_K * np.clip(wide, .25, 4) ** HUE_LARGE
    col = col / (col @ LUMA)[..., None]
    return (g[..., None] * col / EXPOSURE).astype(np.float32)


def depth(ls):
    ls = filament_warp(ls, FILAMENT)
    ls = np.maximum(gs(ls, POST), 1e-5)
    gf = np.maximum(gs(ls, SPLIT_F), 1e-5)
    gm = np.maximum(gs(ls, SPLIT), 1e-5)
    tf, tm = np.log(gf / ls), np.log(gm / gf)
    out = np.where(tf > 0, tf * G_LANE, tf * G_KNOT) + np.where(tm > 0, tm * G_MID_LANE, tm * G_MID_KNOT)
    out = out + np.minimum(np.log(np.maximum(gs(ls, .3), 1e-5) / ls), 0) * G_FF
    out = np.where(out < 0, out * (1 - T_CVX * out), out)
    out = np.where(out < 0, -T_CAP * (1 - np.exp(out / T_CAP)), out)
    # Brightening is for the band's clouds. Off it, a real globular cluster in the map would come up as a saturated round dot.
    bb = np.degrees(np.arcsin((np.arange(out.shape[0]) + .5) / out.shape[0] * 1.2 - .6))[:, None]
    w = np.clip((14 - np.abs(bb)) / 6, 0, 1)
    return np.where(out < 0, out * w * w * (3 - 2 * w), out)


def dust(tau, filled, ls):
    lf = np.maximum(filled, 1e-5)
    l2 = np.maximum(gs(lf, GRAIN_S), 1e-5)
    grain = np.clip((GRAIN_W1 * np.log(lf / l2) + GRAIN_C * np.log(l2 / np.maximum(ls, 1e-5))) / GRAIN_LIM, -1, 1)
    q = H8 // 4
    r = np.clip((tau[q:-q] + 2.5) * .2, 0, 1)
    sb = np.abs((np.arange(r.shape[0]) + .5) / r.shape[0] - .5) * 2
    f = np.clip((sb - .85) / .15, 0, 1)[:, None]
    r = r * (1 - f) + .5 * f
    g = (.5 + .5 * grain[q:-q]) * (1 - f) + .5 * f
    return (np.clip(np.stack([r, g], -1), 0, 1) * 255 + .5).astype(np.uint8)


def lane_field(tau):
    return (cv2.resize((1 - np.exp(-np.maximum(tau, 0) * DUST_DEPTH)).astype(np.float32), (4096, 1024), interpolation=cv2.INTER_AREA) * 255 + .5).astype(np.uint8)


def shown_glow(gl, du):
    """The band as the sky shader shows it at earth_gain 1, luminance in linear, smoothed by about .25 deg so a star follows its cloud and not the grain. Same order as the shader: dust, black point taken before the grain, tone, tint. float16, 4096x1024, rows as galaxy.raw."""
    h, w = gl.shape[:2]
    fog = cv2.resize(du.astype(np.float32) / 255.0, (w, h // 2), interpolation=cv2.INTER_AREA)
    lane = np.zeros((h, w), np.float32)
    grain = np.zeros((h, w), np.float32)
    lane[h // 4:h // 4 + h // 2] = (2.5 - fog[..., 0] * 5.0) * DUST_DEPTH
    grain[h // 4:h // 4 + h // 2] = (fog[..., 1] - .5) * GRAIN_DEPTH
    m = gl * EXPOSURE
    seen = m[..., 1:2] * np.exp(lane)[..., None]
    sb = (np.arange(h) + .5) / h * 1.2 - .6
    lon = ((np.arange(w) + .5) / w - .5) * 2 * np.pi
    gy = sb[:, None].astype(np.float32) * np.ones((h, w), np.float32)
    cb = np.sqrt(1 - gy ** 2)
    gx, gz = cb * np.cos(lon)[None].astype(np.float32), cb * np.sin(lon)[None].astype(np.float32)
    wave = np.sin(17 * gx + 9 * gy - 13 * gz) * np.sin(-11 * gx + 19 * gy + 7 * gz) + .5 * np.sin(31 * gx - 23 * gy + 19 * gz + .7)
    m = m * np.exp((lane + grain)[..., None] * np.array(TINT_DUST, np.float32)) * (seen / (seen + GLOW_BLACK * np.exp(GLOW_WANDER * wave)[..., None]))
    m = m * (TONE_TOP * m[..., 1:2] / (m[..., 1:2] + TONE_KNEE)) * np.array(BAND_TINT, np.float32)
    L = m @ LUMA
    pad = np.concatenate([L[:, -40:], L, L[:, :40]], 1)
    return cv2.GaussianBlur(pad, (0, 0), sigmaX=2.8, sigmaY=3.7)[:, 40:-40].astype(np.float16)


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--work', required=True)
    a.add_argument('--out', required=True)
    a = a.parse_args()
    work, out = Path(a.work), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256((work / 'mw8kgal.npy').read_bytes()).hexdigest() == SOURCE_SHA256, 'Source differs from its pin'
    assert hashlib.sha256((work / 'band_stars.npz').read_bytes()).hexdigest() == BAND_STARS_SHA256, 'band_stars.npz differs from its pin'
    src = np.load(work / 'mw8kgal.npy', mmap_mode='r')
    assert src.shape == (4096, 8192, 3), src.shape
    # Row 0 becomes b -90, and l increases to the right.
    strip = to_strip(np.asarray(src).astype(np.float32)[::-1, ::-1], H8)
    s, filled = stars_out(strip, work / 'band_stars.npz')
    ls_fine = denoise(filled, H_FINE)
    ls_glow = denoise(filled, H_GLOW)
    rgb = cv2.resize(np.stack([gs(s[..., i], .35) for i in range(3)], -1), (4096, 1024), interpolation=cv2.INTER_AREA)
    gl = glow(ls_glow, rgb)
    tau = depth(ls_fine)
    du = dust(tau, filled, ls_fine)
    gl.tofile(out / 'galaxy.raw')
    du.tofile(out / 'dust.raw')
    np.save(out / 'lane_field.npy', lane_field(tau))
    np.save(out / 'shown_glow.npy', shown_glow(gl, du))
    print('PREPARE_DUST_OK', 'galaxy', hashlib.sha256(gl.tobytes()).hexdigest()[:16], 'dust', hashlib.sha256(du.tobytes()).hexdigest()[:16])


if __name__ == '__main__':
    main()
