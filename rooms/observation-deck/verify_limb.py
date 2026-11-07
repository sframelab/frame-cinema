"""Prove the drawn Earth is one sphere: fit a circle to its limb from sky-only renders.

Renders space.gdshader alone in every direction (verify_limb.gd), finds the limb in the images without
using the shader's geometry, turns it into directions on the unit sphere and fits a circle there. Two
measurements. "geometry": only the razor line drawn (twilight, night side and cities off, sun at the planet
centre, so the rim is even all round), and its peak, so brightness cannot move it. "shipped": every default but
one, the outer flank of the razor line at a fixed level, so the limb's brightness (brightest toward the sun) can
move it a little; lit clouds and cities also cross that level, so only crossings near the geometry fit count as
limb. The one exception is limb_fall, held low: the fall away from the hidden sun scales the rim's height by over
20x, which changes no shape, and a fixed level on that flank would measure the height. Writes verification/limb-round.json.

Run from anywhere with the workspace venv; needs the GPU, in a 64x64 window placed off-screen.
--shader and --maps measure other files; --no-write only prints the result.
"""
from pathlib import Path
import argparse, json, math, os, re, shutil, subprocess, sys

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != HERE]

import numpy as np
from PIL import Image

ROOT = HERE.parents[1]
SHIP = HERE.parents[1] / 'app/starship'
GODOT = Path(os.environ.get('GODOT', str(ROOT / '.local/deps/godot-4.7.2/Godot_v4.7.2-stable_win64.exe')))
STAGE = ROOT / '.local/starship-limb'
SIZE = 2048
LEVEL = 110.0      # luma of the flank crossing
DARK_SPAN = 24     # px of sky a crossing must have on its dark side
RIDGE_FLOOR = 60.0
TARGET_DEG = 0.1
# limb_fall for both measurements: with the sun on the planet centre this leaves the rim at about .55, the level the fit's neighbour rule
# was set at; with the sun where it ships it leaves the rim between .75 and 1.04 round the limb.
EVEN_RIM_FALL = 0.708
# Every yaw at three pitches: 90 deg square frames overlap, so the whole limb is seen at least once, sky and floor.
SHOTS = [['y%03d_p%+03d' % (yaw, pitch), yaw, pitch] for yaw in range(0, 360, 30) for pitch in (-50, -20, 10)]


def godot(stage, shots, overrides, output, size):
    env = dict(os.environ, APPDATA=str(stage / 'user-data'), STARSHIP_LIMB_OUT=str(output), STARSHIP_LIMB_SHOTS=json.dumps(shots),
               STARSHIP_LIMB_SIZE=str(size), STARSHIP_LIMB_PARAMS=json.dumps(overrides))
    log = stage / 'render.log'
    args = [str(GODOT), '--path', str(stage), '--xr-mode', 'off', '--audio-driver', 'Dummy', '--rendering-method', 'mobile',
            '--resolution', '64x64', '--position', '-10000,-10000', '--log-file', str(log), '--script', 'res://verify_limb.gd']
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    result = subprocess.run(args, env=env, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW, timeout=900)
    text = log.read_text(errors='replace')
    bad = [line for line in text.splitlines() if any(marker in line for marker in ('SCRIPT ERROR', 'SHADER ERROR', 'ERROR:'))]
    if result.returncode or bad or 'STARSHIP_LIMB_OK' not in text:
        raise RuntimeError('verify_limb.gd failed: %s %s' % (result.returncode, bad[:6]))


def luma(path):
    rgb = np.asarray(Image.open(path).convert('RGB'), dtype=np.float32)
    return rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)


def flank_points(y):
    """Fixed-level crossings along rows and columns with a full DARK_SPAN of sky on the dark side."""
    points = []
    for axis, field in (('row', y), ('column', y.T)):
        for line_index in range(0, field.shape[0], 2):
            line = field[line_index]
            above = line >= LEVEL
            for i in np.flatnonzero(above[1:] != above[:-1]):
                rising = above[i + 1]
                dark = line[max(i - DARK_SPAN, 0):i + 1] if rising else line[i + 1:i + 2 + DARK_SPAN]
                if dark.size < DARK_SPAN or dark.max() >= LEVEL:
                    continue
                pos = i + (LEVEL - line[i]) / (line[i + 1] - line[i]) + .5
                points.append((pos, line_index + .5) if axis == 'row' else (line_index + .5, pos))
    return np.array(points, dtype=np.float64).reshape(-1, 2)


def ridge_points(y):
    """Peaks of the razor line along rows and columns, to a sub-pixel by a parabola through the top three samples."""
    points = []
    for axis, field in (('row', y), ('column', y.T)):
        for line_index in range(0, field.shape[0], 2):
            line = field[line_index]
            top = np.flatnonzero((line[1:-1] >= line[:-2]) & (line[1:-1] > line[2:]) & (line[1:-1] > RIDGE_FLOOR)) + 1
            for i in top:
                # A real crossing of the line, not a scan running along it.
                if line[max(i - 12, 0):i - 5].max(initial=0) > .6 * line[i] or line[i + 6:i + 13].max(initial=0) > .6 * line[i]:
                    continue
                a, b, c = float(line[i - 1]), float(line[i]), float(line[i + 1])
                curve = a - 2 * b + c
                pos = i + .5 + (.5 * (a - c) / curve if curve < 0 else 0.0)
                points.append((pos, line_index + .5) if axis == 'row' else (line_index + .5, pos))
    return np.array(points, dtype=np.float64).reshape(-1, 2)


def directions(points, yaw, pitch, size):
    focal = size / 2
    cam = np.stack([(points[:, 0] - size / 2) / focal, -(points[:, 1] - size / 2) / focal, -np.ones(len(points))], axis=-1)
    cam /= np.linalg.norm(cam, axis=-1, keepdims=True)
    y, p = math.radians(yaw), math.radians(pitch)
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    return cam @ (ry @ rx).T


def fit_circle(d):
    """Small circle on the unit sphere: a plane fit, then Gauss-Newton on the angular residuals."""
    mean = d.mean(axis=0)
    _, _, vt = np.linalg.svd(d - mean, full_matrices=False)
    center = vt[-1] * (np.sign(vt[-1] @ mean) or 1.0)
    radius = math.acos(float(np.clip(center @ mean, -1, 1)))
    for _ in range(20):
        cosine = np.clip(d @ center, -1, 1)
        angle = np.arccos(cosine)
        residual = angle - radius
        u = np.cross(center, [0.0, 1.0, 0.0])
        u /= np.linalg.norm(u)
        v = np.cross(center, u)
        sine = np.maximum(np.sin(angle), 1e-9)
        jacobian = np.stack([-(d @ u) / sine, -(d @ v) / sine, -np.ones(len(d))], axis=-1)
        step = np.linalg.lstsq(jacobian, -residual, rcond=None)[0]
        center = center + step[0] * u + step[1] * v
        center /= np.linalg.norm(center)
        radius += step[2]
        if np.abs(step).max() < 1e-9:
            break
    return center, radius


def azel(v):
    return math.degrees(math.atan2(v[0], -v[2])), math.degrees(math.asin(max(-1.0, min(1.0, v[1]))))


def measure(d, label, near=None):
    """Fit, drop far outliers with a limit that scales with the scatter, refit. near = (center, radius, limit deg) keeps
    only points that close to an earlier fit, which is what separates the shipped limb from the lit surface below it."""
    keep = np.ones(len(d), bool)
    if near is not None:
        keep = np.abs(np.degrees(np.arccos(np.clip(d @ near[0], -1, 1)) - near[1])) <= near[2]
    surface = int((~keep).sum())
    d = d[keep]
    keep = np.ones(len(d), bool)
    for _ in range(8):
        center, radius = fit_circle(d[keep])
        residual = np.degrees(np.arccos(np.clip(d @ center, -1, 1))) - math.degrees(radius)
        limit = max(.5, 4 * 1.4826 * float(np.median(np.abs(residual[keep]))))
        new = np.abs(residual) <= limit
        if (new == keep).all():
            break
        keep = new
    r = residual[keep]
    az = np.degrees(np.arctan2(d[keep, 0], -d[keep, 2]))
    edges = np.arange(-180, 181, 30)
    bins = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (az >= lo) & (az < hi)
        bins.append({'az': [int(lo), int(hi)], 'points': int(m.sum()), 'mean_deg': round(float(r[m].mean()), 4) if m.any() else None,
                     'max_abs_deg': round(float(np.abs(r[m]).max()), 4) if m.any() else None})
    caz, cel = azel(center)
    result = {'points': int(keep.sum()), 'rejected': int((~keep).sum()), 'surface_crossings_left_out': surface,
              'center': [round(float(c), 5) for c in center], 'center_az_deg': round(caz, 3), 'center_el_deg': round(cel, 3),
              'radius_deg': round(math.degrees(radius), 4), 'residual_rms_deg': round(float(np.sqrt((r * r).mean())), 4),
              'residual_p99_deg': round(float(np.percentile(np.abs(r), 99)), 4), 'residual_max_deg': round(float(np.abs(r).max()), 4),
              'limb_el_seen_deg': [round(math.degrees(math.asin(float(d[keep, 1].min()))), 1), round(math.degrees(math.asin(float(d[keep, 1].max()))), 1)],
              'residual_by_az': bins}
    print(label, {k: v for k, v in result.items() if k != 'residual_by_az'}, flush=True)
    return result


def run_set(stage, overrides, finder, name, size):
    output = stage / 'renders' / name
    if output.exists():
        shutil.rmtree(output)
    godot(stage, SHOTS, overrides, output, size)
    found = []
    for shot, yaw, pitch in SHOTS:
        points = finder(luma(output / (shot + '.png')))
        if len(points):
            found.append(directions(points, yaw, pitch, size))
    return np.concatenate(found)


def shader_vec3(source, name):
    return [float(v) for v in re.search(r'uniform\s+vec3\s+' + name + r'\s*=\s*vec3\(([^)]*)\)', source).group(1).split(',')]


def shader_float(source, name):
    return float(re.search(r'uniform\s+float\s+' + name + r'\s*=\s*([-0-9.eE+]+)', source).group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--shader', type=Path, default=SHIP / 'space.gdshader')
    parser.add_argument('--maps', type=Path, default=SHIP, help='Folder with earth-surface.res, earth-masks.res and earth-clouds.res')
    parser.add_argument('--stage', type=Path, default=STAGE)
    parser.add_argument('--size', type=int, default=SIZE)
    parser.add_argument('--no-write', action='store_true')
    args = parser.parse_args()
    stage = args.stage.resolve()
    (stage / 'starship').mkdir(parents=True, exist_ok=True)
    (stage / 'project.godot').write_text('config_version=5\n[application]\nconfig/name="Observation Deck limb check"\nconfig/use_custom_user_dir=true\nconfig/custom_user_dir_name="s"\n[rendering]\nrenderer/rendering_method="mobile"\n[display]\nwindow/size/viewport_width=64\nwindow/size/viewport_height=64\n')
    shutil.copyfile(HERE / 'verify_limb.gd', stage / 'verify_limb.gd')
    shutil.copyfile(args.shader, stage / 'starship/space.gdshader')
    shutil.copyfile(SHIP / 'galaxy.res', stage / 'starship/galaxy.res')
    for name in ('earth-surface.res', 'earth-masks.res', 'earth-clouds.res'):
        shutil.copyfile(args.maps / name, stage / 'starship' / name)
    source = args.shader.read_text()
    planet = shader_vec3(source, 'planet_direction')
    geometry = measure(run_set(stage, {'galaxy_exposure': 0.0, 'twilight_gain': 0.0, 'night_gain': 0.0, 'city_gain': 0.0, 'sun': planet, 'limb_fall': EVEN_RIM_FALL},
                               ridge_points, 'geometry', args.size), 'geometry')
    near = (np.array(geometry['center']), math.radians(geometry['radius_deg']), max(1.0, .5 + 1.5 * geometry['residual_max_deg']))
    shipped = measure(run_set(stage, {'galaxy_exposure': 0.0, 'limb_fall': EVEN_RIM_FALL}, flank_points, 'shipped', args.size), 'shipped', near)
    length = math.sqrt(sum(c * c for c in planet))
    expected = [c / length for c in planet]
    report = {'what': 'A circle fitted to the Earth limb on the unit sphere, from sky-only renders in every direction; nothing about the shader geometry is used to find the limb',
              'renders': {'frames': len(SHOTS), 'size_px': args.size, 'fov_deg': 90.0, 'yaw_step_deg': 30, 'pitches_deg': [-50, -20, 10],
                          'stars_and_galaxy': 'off (no star mesh in this stage, galaxy_exposure 0), so no star can pass for the limb'},
              'shader_planet_direction': planet, 'expected_center_az_el_deg': [round(v, 3) for v in azel(expected)],
              'expected_radius_deg': round(math.degrees(math.asin(1 / shader_float(source, 'planet_distance'))), 3),
              'target_residual_deg': TARGET_DEG,
              'shipped': dict(shipped, method='every shader default but limb_fall %g; fixed luma %g on the outer flank of the razor line, which sits a little outside the geometric limb, and further where the rim is brighter' % (EVEN_RIM_FALL, LEVEL)),
              'geometry': dict(geometry, method='only the razor line drawn, even rim all round (twilight, night and city gain 0, sun on the planet centre, limb_fall %g); its peak by a parabola, which brightness cannot move' % EVEN_RIM_FALL),
              'passes': shipped['residual_max_deg'] <= TARGET_DEG and geometry['residual_max_deg'] <= TARGET_DEG}
    if not args.no_write:
        target = HERE / 'verification/limb-round.json'
        target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('Wrote', target, flush=True)
    print('LIMB_ROUND', 'pass' if report['passes'] else 'FAIL', flush=True)


if __name__ == '__main__':
    main()
