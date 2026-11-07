"""Check the ship in the actual Cinema registry, screen placement and room UI.

Run after stage_preview.py has built the runtime package and thumbnail. This
uses an isolated Windows Godot project and never opens XR, browser processes,
production preferences, a Steam entry or a public installer.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT = HERE.parents[1] / "app"
SHIP = PROJECT / "starship"
STAGE = ROOT / ".local/starship-integration-fixture"
OUTPUT = HERE / "verification"
GODOT = Path(os.environ.get('GODOT', str(ROOT / '.local/deps/godot-4.7.2/Godot_v4.7.2-stable_win64.exe')))
FILES = (
    "cinema.gd", "cinema_rooms.gd", "cinema_ui.gd", "cinema_ambient.gd",
    "cinema_ambient.gdshader", "cinema_ambient_field.gdshader",
    "cinema_ambient_diffusion.gdshader", "cinema_glass.gdshader",
    "cinema_thumbnail.gdshader", "cinema_service_art.gdshader",
    "cinema_card.gdshader", "picture_fit.gd", "playback_health.gd",
    "frame_pacing.gd", "viewing_idle.gd", "controller_foreground.gd",
    "test_starship_integration.gd", "stereo/stereo_control.gd",
    "lunar/package.json", "coast/package.json", "desert/package.json",
    "environments/starship-thumb.png",
)


# Runtime files beyond the per-part triplets (which come from starship.json, so new
# groups such as viewer and trim are picked up automatically).
SHIP_FILES = (
    "package.json", "starship.json", "starship_room.gd", "hull.gdshader",
    "space.gdshader", "stars.gdshader", "stars.dat", "cities.gdshader", "cities.dat", "earth-surface.res", "earth-masks.res", "earth-clouds.res", "cloud-detail.res",
    "deck_common.gdshaderinc", "deck.gdshader", "deck_field.gdshader",
    "surround.gdshader", "glow.gdshader",
    "galaxy.res", "dust.res", "objects.dat", "objects.gdshader", "objects-atlas.res", "deck-mirror.res", "deck-wear.res",
)


def shader_vec3(source, name):
    match = re.search(r"uniform\s+vec3\s+" + name + r"\s*=\s*vec3\(([^)]*)\)", source)
    assert match, "space.gdshader has no default for " + name
    return [float(v) for v in match.group(1).split(",")]


def shader_float(source, name):
    match = re.search(r"uniform\s+float\s+" + name + r"\s*=\s*([-0-9.eE+]+)", source)
    assert match, "space.gdshader has no default for " + name
    return float(match.group(1))


def normalized(v):
    length = math.sqrt(sum(c * c for c in v))
    return [c / length for c in v]


def check_constants(metadata):
    """The sky shader and the bake (Earth-proxy world) must agree on the shared constants."""
    source = (SHIP / "space.gdshader").read_text()
    sky = metadata.get("sky")
    assert isinstance(sky, dict), "starship.json has no 'sky' block"
    report = {}
    for name in ("planet_direction", "sun"):
        shader = normalized(shader_vec3(source, name))
        baked = normalized([float(c) for c in sky[name]])
        error = max(abs(a - b) for a, b in zip(shader, baked))
        assert error <= 1e-3, "%s differs between space.gdshader %s and starship.json %s" % (name, shader, baked)
        report[name] = round(error, 6)
    distance = shader_float(source, "planet_distance")
    error = abs(distance - float(sky["planet_distance"]))
    assert error <= 1e-3, "planet_distance differs: space.gdshader %s, starship.json %s" % (distance, sky["planet_distance"])
    report["planet_distance"] = round(error, 6)
    # The twilight fade is shared with the bake proxy. Only the fade: the proxy's band and ring keep their even light round the
    # limb, while the sky's fall away from the hidden sun (limb_fall). See the README's turning Earth section for what that leaves.
    match = re.search(r"float tw = [^;]*?smoothstep\(\s*([-0-9.]+)\s*,\s*([-0-9.]+)\s*,\s*inside_deg\s*\)", source)
    assert match, "space.gdshader has no twilight fade smoothstep(a, b, inside_deg)"
    assert "twilight_fade_deg" in sky, "starship.json sky block has no twilight_fade_deg"
    fade = [float(match.group(1)), float(match.group(2))]
    error = max(abs(a - float(b)) for a, b in zip(fade, sky["twilight_fade_deg"]))
    assert error <= 1e-3, "twilight fade differs: space.gdshader %s, starship.json %s" % (fade, sky["twilight_fade_deg"])
    report["twilight_fade_deg"] = round(error, 6)
    return report


# The Earth is one rigid sphere: nothing may bend or shift the ray before the sphere test.
NON_RIGID = re.compile(r"warp|limb_drop|ray_e|heading", re.IGNORECASE)
RIGID_LINES = ("vec3 ray = normalize(world_to_room * EYEDIR);", "vec3 P = normalize(planet_direction);",
               "vec3 center = P * planet_distance;", "float along = dot(center, ray);",
               "float miss = length(center - along * ray);")


def python_constant(path, name):
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            call = node.value
            # np.array([...]) or a plain list
            return ast.literal_eval(call.args[0] if isinstance(call, ast.Call) else call)
    raise AssertionError("%s has no %s" % (path.name, name))


def check_round_earth(metadata):
    """Fails if warp code or a non-rigid term comes back, if any copy of the centre drifts, or if the limb proof is stale."""
    source = (SHIP / "space.gdshader").read_text()
    found = sorted(set(m.group(0).lower() for m in NON_RIGID.finditer(source)))
    assert not found, "space.gdshader has a non-rigid Earth term again: %s" % found
    for line in RIGID_LINES:
        assert line in source, "space.gdshader no longer tests the sphere with the room ray: missing " + line
    assignments = re.findall(r"(?<![.\w])ray(?:\.[xyzrgb]+)?\s*(?:[-+*/]?=)(?!=)", source)
    assert len(assignments) == 1, "space.gdshader changes the room ray after computing it (%d assignments)" % len(assignments)
    runtime = (HERE / "build_runtime.py").read_text(encoding="utf-8")
    prepare = (HERE / "prepare_earth.py").read_text(encoding="utf-8")
    # prepare_earth.py's heading is the geographic bearing of room north, not a bend in the ray.
    for name, text in (("build_runtime.py", runtime), ("prepare_earth.py", prepare)):
        found = sorted(set(m.group(0).lower() for m in re.finditer(r"warp|limb_drop|ray_e\b", text, re.IGNORECASE)))
        assert not found, "%s has a non-rigid Earth term again: %s" % (name, found)
    sky = metadata.get("sky", {})
    stale = [name for name in ("warp_deg", "limb_drop_deg") if name in sky]
    assert not stale, "starship.json sky block still records %s: the bake predates the round Earth" % stale
    planet = normalized(shader_vec3(source, "planet_direction"))
    sun = normalized(shader_vec3(source, "sun"))
    report = {}
    copies = {"build_runtime.py PLANET_DIRECTION": python_constant(HERE / "build_runtime.py", "PLANET_DIRECTION"),
              "prepare_earth.py PLANET_DIRECTION": python_constant(HERE / "prepare_earth.py", "PLANET_DIRECTION")}
    record = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))
    copies["space-source.json constants"] = record["constants_godot_room_space"]["planet_direction"]
    copies["space-source.json uniforms"] = record["shader"]["uniforms"]["planet_direction"]
    copies["space-source.json belt frame"] = record["belt"]["frame"]["planet_direction"]
    for name, value in copies.items():
        error = max(abs(a - b) for a, b in zip(planet, normalized(value)))
        assert error <= 1e-4, "planet centre differs between space.gdshader %s and %s %s" % (planet, name, value)
    report["planet_copies"] = len(copies)
    error = max(abs(a - b) for a, b in zip(sun, normalized(python_constant(HERE / "build_runtime.py", "SUN_DIRECTION"))))
    assert error <= 1e-4, "sun differs between space.gdshader and build_runtime.py"
    proof = json.loads((OUTPUT / "limb-round.json").read_text(encoding="utf-8"))
    assert proof.get("passes"), "verification/limb-round.json does not pass; run verify_limb.py"
    error = max(abs(a - b) for a, b in zip(normalized(proof["shader_planet_direction"]), planet))
    assert error <= 1e-4, "verification/limb-round.json measured another centre; run verify_limb.py again"
    for name in ("shipped", "geometry"):
        assert proof[name]["residual_max_deg"] <= 0.1, "limb residual %s deg in %s" % (proof[name]["residual_max_deg"], name)
    # The fitted circle has to be the shader's sphere, not only some circle. The shipped flank sits a little
    # outside the limb and leans toward the bright side, so it gets more room than the geometry peak.
    report["limb_residual_max_deg"] = {name: proof[name]["residual_max_deg"] for name in ("shipped", "geometry")}
    fitted = normalized(proof["geometry"]["center"])
    miss = math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(fitted, planet))))))
    assert miss <= 0.05, "the fitted limb centre is %.3f deg from planet_direction" % miss
    radius = math.degrees(math.asin(1 / shader_float(source, "planet_distance")))
    assert abs(proof["geometry"]["radius_deg"] - radius) <= 0.1, "the fitted limb radius %s differs from the sphere's %.3f" % (proof["geometry"]["radius_deg"], radius)
    report["fit_centre_vs_shader_deg"] = round(miss, 4)
    return report


def shader_vec3_constant(source, name):
    match = re.search(r"const\s+vec3\s+" + name + r"\s*=\s*vec3\(([^)]*)\)", source)
    assert match, "space.gdshader has no constant " + name
    return [float(v) for v in match.group(1).split(",")]


def check_turning_earth():
    """The shader's belt constants are the ones prepare_earth.py maps for, the spin is a global uniform every stage can compile, and nothing brings TIME back."""
    source = (SHIP / "space.gdshader").read_text()
    spec = importlib.util.spec_from_file_location("prepare_earth", HERE / "prepare_earth.py")
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    expected = prepare.geo_basis_constants(*prepare.BELT_FIRST_VIEW, prepare.HEADING)
    report = {}
    for name, key in (("CAP_N0", "cap_n0"), ("CAP_EAST", "cap_east"), ("CAP_NORTH", "cap_north")):
        error = max(abs(a - float(b)) for a, b in zip(shader_vec3_constant(source, name), expected[key]))
        assert error <= 1e-5, "%s differs between space.gdshader and prepare_earth.py: %s" % (name, error)
    basis = re.search(r"const\s+mat3\s+GEO_BASIS\s*=\s*mat3\(([^;]*)\);", source)
    assert basis, "space.gdshader has no GEO_BASIS"
    values = [float(v) for v in re.findall(r"-?\d+\.\d+", basis.group(1))]
    wanted = [float(v) for key in ("geo_x", "geo_y", "geo_z") for v in expected[key]]
    error = max(abs(a - b) for a, b in zip(values, wanted))
    assert len(values) == 9 and error <= 1e-5, "GEO_BASIS differs from prepare_earth.py for the first view %s: %s" % (prepare.BELT_FIRST_VIEW, error)
    report["geo_basis_max_error"] = round(error, 7)
    for name, key in (("BELT_TOP", "belt_top"), ("BELT_SCALE", "belt_scale")):
        match = re.search(r"const\s+float\s+" + name + r"\s*=\s*([-0-9.]+)", source)
        assert match and abs(float(match.group(1)) - float(expected[key])) <= 1e-5, "%s differs from prepare_earth.py" % name
    # Comments out: the header says why there is no TIME.
    code = re.sub(r"//[^\n]*", "", source)
    assert not re.search(r"\bTIME\b", code), "space.gdshader reads TIME: that re-renders the radiance map every frame"
    assert "global uniform vec2 earth_spin;" in code, "space.gdshader no longer takes its spin from the global uniform"
    room = (SHIP / "starship_room.gd").read_text()
    assert 'global_shader_parameter_set("earth_spin"' in room, "starship_room.gd does not advance the global earth_spin"
    assert 'set_shader_parameter("earth_spin"' not in room, "earth_spin must stay global: a material uniform re-renders the radiance map"
    project = (PROJECT / "project.godot").read_text()
    limb = (HERE / "verify_limb.gd").read_text()
    section = re.search(r"\[shader_globals\]\n(.*?)(?=\n\[|\Z)", project, re.S)
    assert section, "project.godot has no [shader_globals]"
    for name, kind in (("earth_gain", "float"), ("earth_spin", "vec2")):
        assert ("global uniform %s %s;" % (kind, name)) in code, "space.gdshader no longer takes %s from a global uniform" % name
        assert re.search(r"^%s=\{\s*\"type\": \"%s\"" % (name, kind), section.group(1), re.M), "project.godot does not declare " + name
        assert 'global_shader_parameter_add("%s"' % name in room, "starship_room.gd must declare %s for stages without the project entry" % name
        assert 'has_setting("shader_globals/%s")' % name in room, "starship_room.gd must not declare %s over the project entry" % name
        assert 'global_shader_parameter_add("%s"' % name in limb, "verify_limb.gd must declare " + name
    record = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))
    runtime = {entry["file"]: entry for entry in record["runtime"]}
    for name in ("earth-surface.res", "earth-masks.res", "earth-clouds.res"):
        assert runtime[name]["bytes"] == (SHIP / name).stat().st_size, "space-source.json has another size for " + name
    for retired in ("earth-day.res", "earth-extra.res"):
        assert not (SHIP / retired).exists() and retired not in runtime, retired + " still ships: the belt replaced it"
    report["first_view"] = list(prepare.BELT_FIRST_VIEW)
    return report


def check_galaxy():
    """The Milky Way basis lives in space.gdshader and is recorded twice in space-source.json, and the
    strip and dust map (prepare_dust.py) have no bend of their own, so the band is that great circle: all of them must agree."""
    import ast
    source = (SHIP / "space.gdshader").read_text()
    record = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))
    names = ("galaxy_x", "galaxy_pole", "galaxy_z")
    shader = {name: shader_vec3(source, name) for name in names}
    report = {}
    for label, block in (("constants", record["constants_godot_room_space"]["galaxy_basis"]),
                         ("uniforms", record["shader"]["uniforms"])):
        error = max(abs(a - float(b)) for name in names for a, b in zip(shader[name], block[name]))
        assert error <= 1e-4, "galaxy basis differs between space.gdshader and space-source.json %s: %s" % (label, error)
        report["basis_vs_" + label] = round(error, 6)
    x, p, z = (shader[name] for name in names)
    dot = lambda a, b: sum(u * v for u, v in zip(a, b))
    cross = [p[1] * x[2] - p[2] * x[1], p[2] * x[0] - p[0] * x[2], p[0] * x[1] - p[1] * x[0]]
    ortho = max(abs(dot(x, p)), abs(dot(x, z)), abs(dot(p, z)), *(abs(dot(v, v) - 1) for v in (x, p, z)),
                *(abs(a - b) for a, b in zip(cross, z)))
    assert ortho <= 1e-3, "galaxy basis is not orthonormal and right-handed (z = pole x x): %s" % ortho
    report["orthonormal"] = round(ortho, 6)
    exposure = shader_float(source, "galaxy_exposure")
    assert abs(exposure - float(record["shader"]["uniforms"]["galaxy_exposure"])) <= 1e-6, "galaxy_exposure differs from space-source.json"
    tree = ast.parse((HERE / "prepare_dust.py").read_text(encoding="utf-8"))
    names_ = ("BEND", "EXPOSURE", "DUST_DEPTH", "GRAIN_DEPTH", "TINT_DUST", "GLOW_BLACK", "SIN_MAX", "TONE_TOP", "TONE_KNEE", "BAND_TINT", "GLOW_WANDER")
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in names_:
                constants[target.id] = ast.literal_eval(node.value)
            elif isinstance(target, ast.Tuple) and all(isinstance(e, ast.Name) for e in target.elts) and target.elts[0].id == "GRAIN_DEPTH":
                constants.update(zip((e.id for e in target.elts), ast.literal_eval(node.value)))
            elif isinstance(target, ast.Tuple) and all(isinstance(e, ast.Name) for e in target.elts) and target.elts[0].id == "TONE_TOP":
                constants.update(zip((e.id for e in target.elts), ast.literal_eval(node.value)))
    assert "BEND" not in constants and "bend" not in record["galaxy"], "The Milky Way must stay a true great circle: no BEND"
    assert abs(exposure - constants["EXPOSURE"]) <= 1e-6, "galaxy_exposure differs from prepare_dust.py EXPOSURE"
    assert abs(exposure - float(record["galaxy"]["grade"]["exposure"])) <= 1e-6, "galaxy_exposure differs from space-source.json galaxy.grade.exposure"
    # The sky's dust constants are the ones prepare_dust.py baked its star fields with.
    for name in ("DUST_DEPTH", "GRAIN_DEPTH", "GLOW_BLACK", "TONE_TOP", "TONE_KNEE", "GLOW_WANDER"):
        assert abs(shader_constant_float(source, name) - float(constants[name])) <= 1e-6, name + " differs between space.gdshader and prepare_dust.py"
    tint = shader_vec3_constant(source, "TINT_DUST")
    assert max(abs(a_ - float(b_)) for a_, b_ in zip(tint, constants["TINT_DUST"])) <= 1e-6, "TINT_DUST differs between space.gdshader and prepare_dust.py"
    band_tint = shader_vec3_constant(source, "BAND_TINT")
    assert max(abs(a_ - float(b_)) for a_, b_ in zip(band_tint, constants["BAND_TINT"])) <= 1e-6, "BAND_TINT differs between space.gdshader and prepare_dust.py"
    assert "uniform sampler2D dust" in source and "abs(g.y) < 0.3" in source, "space.gdshader no longer reads the dust map on its rows"
    room = (SHIP / "starship_room.gd").read_text()
    assert 'set_shader_parameter("dust"' in room, "starship_room.gd does not bind dust.res: an unbound dust map reads black and the band goes about 5x too bright"
    runtime = {entry["file"]: entry for entry in record["runtime"]}
    for name in ("galaxy.res", "dust.res"):
        assert runtime[name]["bytes"] == (SHIP / name).stat().st_size, "space-source.json has another size for " + name
        assert (SHIP / name).stat().st_size < 32 * 1048576, name + " is at the 32 MiB line"
    report["band"] = {"exposure": exposure, "dust_depth": constants["DUST_DEPTH"]}
    report["scale_matches_strip"] = True
    return report


# Real places, galactic degrees from J2000. A slide of the sky along the band keeps the pole, so the plane tests below cannot see a mesh left behind. These can.
REAL_STARS = (("Sirius", 227.224, -8.900), ("Canopus", 261.213, -25.285), ("Alpha Centauri", 315.734, -0.679), ("Arcturus", 15.060, 69.103), ("Vega", 67.445, 19.244), ("Capella", 162.589, 4.568), ("Rigel", 209.237, -25.254), ("Procyon", 213.702, 13.019), ("Achernar", 290.845, -58.793), ("Betelgeuse", 199.791, -8.953), ("Hadar", 311.764, 1.252), ("Altair", 47.746, -8.913), ("Aldebaran", 180.968, -20.252), ("Antares", 351.946, 15.066), ("Spica", 316.115, 50.844), ("Pollux", 192.228, 23.403), ("Fomalhaut", 20.490, -64.920), ("Deneb", 84.281, 2.002))
REAL_OBJECTS = (("Carina", 287.60, -0.63), ("Large Magellanic Cloud", 280.46, -32.88), ("Small Magellanic Cloud", 302.79, -44.32), ("47 Tucanae", 305.89, -44.88), ("Lagoon", 5.96, -1.17), ("Trifid", 7.00, -0.25), ("Swan", 15.05, -0.68), ("Eagle", 16.95, 0.79), ("Sagittarius Star Cloud", 12.70, -0.90), ("M22", 9.90, -7.55))
# Cut on purpose, with the radius its stars reached. A mesh that still holds one is an older build, and the places above would not say so.
CUT_OBJECTS = (("Omega Centauri", 309.10, 14.96, 0.7),)


def real_place(sky, l_deg, b_deg):
    x_, p_, z_ = (shader_vec3(sky, n) for n in ("galaxy_x", "galaxy_pole", "galaxy_z"))
    l_, b_ = math.radians(l_deg), math.radians(b_deg)
    return normalized([math.cos(b_) * math.cos(l_) * x_[i] + math.cos(b_) * math.sin(l_) * z_[i] + math.sin(b_) * p_[i] for i in range(3)])


def check_stars():
    """The star mesh: same amplitude code as prepare_stars.py, at infinity, no eye depth in front of the Earth, none of it behind the disc, inside the star budget. The limb is baked by prepare_stars.py from space.gdshader, so the star shader holds no planet constants to compare."""
    import ast
    sky = (SHIP / "space.gdshader").read_text()
    stars = (SHIP / "stars.gdshader").read_text()
    assert "vec4(mat3(MODELVIEW_MATRIX) * corner_dir, 0.0)" in stars, "stars.gdshader no longer draws at w = 0"
    for name in ("DEPTH_HERO", "DEPTH_MID", "DEPTH_DUST"):
        assert float(re.search(r"const float " + name + r" = ([-0-9.eE+]+)", stars).group(1)) >= 0.0, name + " would float stars in front of the Earth"
    code = re.sub(r"//[^\n]*", "", stars + sky)
    assert not re.search(r"\bTIME\b", code), "A sky shader reads TIME: it would re-render the radiance map every frame"
    assert "star_layer" not in sky, "space.gdshader still has the lattice stars"
    assert re.search(r"global uniform float earth_gain", sky), "earth_gain must stay a global: a material uniform re-renders the radiance map"
    tree = ast.parse((HERE / "prepare_stars.py").read_text(encoding="utf-8"))
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("AMP_MIN", "AMP_MAX", "MAX_STARS", "MAGIC")}
    amp_min = float(re.search(r"const float AMP_MIN = ([-0-9.eE+]+)", stars).group(1))
    log_range = float(re.search(r"const float AMP_LOG_RANGE = ([-0-9.eE+]+)", stars).group(1))
    assert abs(amp_min - constants["AMP_MIN"]) <= 1e-9, "AMP_MIN differs between stars.gdshader and prepare_stars.py"
    assert abs(log_range - math.log(constants["AMP_MAX"] / constants["AMP_MIN"])) <= 1e-3, "AMP_LOG_RANGE differs from prepare_stars.py"
    data = (SHIP / "stars.dat").read_bytes()
    magic, chunks, vertices = struct.unpack("<III", data[:12])
    assert magic == constants["MAGIC"] and vertices % 3 == 0, "stars.dat header is not one triangle per star"
    assert vertices // 3 <= constants["MAX_STARS"], "Too many stars: %d" % (vertices // 3)
    assert len(data) == 12 + chunks * 32 + vertices * 16, "stars.dat size does not match its header"
    # Baked limb: no star's centre lies behind the disc, so a change of the planet without a rerun of prepare_stars.py fails here.
    planet = normalized(shader_vec3(sky, "planet_direction"))
    limit = math.cos(math.asin(1 / shader_float(sky, "planet_distance")))
    worst = -1.0
    offset = 12 + chunks * 32
    for i in range(vertices // 3):
        x, y, z = struct.unpack_from("<3f", data, offset + i * 36)
        length = math.sqrt(x * x + y * y + z * z)
        worst = max(worst, (x * planet[0] + y * planet[1] + z * planet[2]) / length)
    assert worst < limit + 2e-3, "stars.dat holds a star behind the Earth's disc: rerun prepare_stars.py"
    # The mesh must lie on the sky's basis. The faintest tier hangs on the band, so its galactic latitude tells a stale mesh with no receipt; the receipt says which basis it was baked on.
    pole = normalized(shader_vec3(sky, "galaxy_pole"))
    near = total = 0
    for i in range(vertices // 3):
        offset_ = 12 + chunks * 32 + i * 36
        if data[12 + chunks * 32 + vertices * 12 + i * 12 + 3] / 255.0 < 0.2584:
            x, y, z = struct.unpack_from("<3f", data, offset_)
            total += 1
            near += abs(x * pole[0] + y * pole[1] + z * pole[2]) < 0.14 * math.sqrt(x * x + y * y + z * z)
    assert total > 1000 and near / total > 0.75, "stars.dat does not follow space.gdshader's galactic basis (%d of %d faint stars within 8 deg of the plane): rerun prepare_stars.py" % (near, total)
    # The shader picks the skirt from the amplitude code; the triangle must have been cut for the same answer, or the star's core is 3.39x too tight and it pops.
    skirt_from = float(re.search(r"const float SKIRT_FROM = ([-0-9.eE+]+)", stars).group(1))
    for i in range(vertices // 3):
        corner = struct.unpack_from("<9f", data, 12 + chunks * 32 + i * 36)
        cx, cy, cz = (corner[0] + corner[3] + corner[6]) / 3, (corner[1] + corner[4] + corner[7]) / 3, (corner[2] + corner[5] + corner[8]) / 3
        size = math.sqrt((corner[6] - cx) ** 2 + (corner[7] - cy) ** 2 + (corner[8] - cz) ** 2) / 2
        amp = amp_min * math.exp(data[12 + chunks * 32 + vertices * 12 + i * 12 + 3] / 255.0 * log_range)
        assert (amp >= skirt_from) == (size > 0.007), "stars.dat star %d: its triangle and the shader disagree on its skirt: rerun prepare_stars.py" % i
    # Real stars where the sky says they are: each one clear of the disc has a mesh star within .06 deg.
    centres = []
    for i in range(vertices // 3):
        corner = struct.unpack_from("<9f", data, 12 + chunks * 32 + i * 36)
        centres.append(normalized(((corner[0] + corner[3] + corner[6]) / 3, (corner[1] + corner[4] + corner[7]) / 3, (corner[2] + corner[5] + corner[8]) / 3)))
    near_cos = math.cos(math.radians(0.06))
    tested = 0
    for label, l_, b_ in REAL_STARS:
        want = real_place(sky, l_, b_)
        if want[0] * planet[0] + want[1] * planet[1] + want[2] * planet[2] > limit - 0.01:
            continue
        tested += 1
        assert max(c[0] * want[0] + c[1] * want[1] + c[2] * want[2] for c in centres) > near_cos, "stars.dat has no star at %s's place on space.gdshader's basis: rerun prepare_stars.py" % label
    assert tested >= 8, "Too few real stars clear of the disc to test the mesh's basis: %d" % tested
    receipt = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))["stars"]["receipt"]
    for name in ("galaxy_x", "galaxy_pole", "galaxy_z"):
        assert max(abs(a - float(b)) for a, b in zip(shader_vec3(sky, name), receipt["basis"][name])) <= 1e-4, name + " differs between space.gdshader and the star mesh's receipt: rerun prepare_stars.py"
    # The Focus ramp reaches the stars and objects through the global only: a material uniform would be a write per frame, and it stops at no zero but the one in a tool.
    for label, code_ in (("stars.gdshader", stars), ("objects.gdshader", (SHIP / "objects.gdshader").read_text())):
        assert "global uniform float earth_gain;" in code_, label + " must read the Focus ramp from the global"
    assert "(milky * earth_gain + field)" in sky, "space.gdshader: the band and the field must follow the Focus ramp"
    return {"stars": vertices // 3, "triangles": vertices // 3, "chunks": chunks, "faint_on_band": round(near / total, 3)}


def check_objects():
    """The deep-sky node: same planet as the sky, at infinity, drawn after the stars, its atlas under the memory line, inside its triangle budget."""
    sky = (SHIP / "space.gdshader").read_text()
    objects = (SHIP / "objects.gdshader").read_text()
    for name in ("planet_direction",):
        assert shader_vec3(sky, name) == shader_vec3(objects, name), name + " differs between space.gdshader and objects.gdshader"
    assert shader_float(sky, "planet_distance") == shader_float(objects, "planet_distance"), "planet_distance differs between space.gdshader and objects.gdshader"
    assert "vec4(mat3(MODELVIEW_MATRIX) * corner_dir, 0.0)" in objects, "objects.gdshader no longer draws at w = 0"
    code = re.sub(r"//[^\n]*", "", objects)
    assert not re.search(r"\bTIME\b", code), "objects.gdshader reads TIME"
    room = (SHIP / "starship_room.gd").read_text()
    assert 'set_shader_parameter("atlas"' in room, "starship_room.gd does not bind the objects' atlas"
    record_ = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))["objects"]
    for name in ("galaxy_x", "galaxy_pole", "galaxy_z"):
        assert max(abs(a - float(b)) for a, b in zip(shader_vec3(sky, name), record_["basis"][name])) <= 1e-4, name + " differs between space.gdshader and the objects' record: rerun prepare_objects.py"
    data = (SHIP / "objects.dat").read_bytes()
    magic, vertices = struct.unpack("<II", data[:8])
    assert magic == 0x534A424F and vertices % 3 == 0 and len(data) == 8 + vertices * 24, "objects.dat header does not match its size"
    assert vertices // 3 <= 6000, "Too many object triangles: %d" % (vertices // 3)
    # The sprites are mostly on the band, so a mesh on another basis shows here, with no receipt to trust.
    pole = normalized(shader_vec3(sky, "galaxy_pole"))
    near = total = 0
    for i in range(0, vertices, 6):
        if data[8 + vertices * 20 + i * 4 + 3] != 0:
            break
        c = [sum(struct.unpack_from("<f", data, 8 + (i + k) * 12 + axis * 4)[0] for k in range(6)) for axis in range(3)]
        total += 1
        near += abs(c[0] * pole[0] + c[1] * pole[1] + c[2] * pole[2]) < 0.14 * math.sqrt(c[0] * c[0] + c[1] * c[1] + c[2] * c[2])
    assert total >= 20 and near / total > 0.6, "objects.dat does not follow space.gdshader's galactic basis (%d of %d sprites within 8 deg of the plane): rerun prepare_objects.py" % (near, total)
    # Real objects where the sky says they are: a sprite's centre within .05 deg of each.
    quads = []
    for i in range(0, vertices, 6):
        if data[8 + vertices * 20 + i * 4 + 3] != 0:
            break
        quads.append(normalized([sum(struct.unpack_from("<f", data, 8 + (i + k) * 12 + axis * 4)[0] for k in range(6)) for axis in range(3)]))
    for label, l_, b_ in REAL_OBJECTS:
        want = real_place(sky, l_, b_)
        assert max(c[0] * want[0] + c[1] * want[1] + c[2] * want[2] for c in quads) > math.cos(math.radians(0.05)), "objects.dat has no sprite at %s's place on space.gdshader's basis: rerun prepare_objects.py" % label
    stars_at = [normalized(struct.unpack_from("<3f", data, 8 + i * 12)) for i in range(len(quads) * 6, vertices, 3)]
    for label, l_, b_, r_ in CUT_OBJECTS:
        want = real_place(sky, l_, b_)
        assert max(c[0] * want[0] + c[1] * want[1] + c[2] * want[2] for c in quads) < math.cos(math.radians(0.05)), "objects.dat still has a sprite at %s's place, which was cut: rerun prepare_objects.py" % label
        assert max(c[0] * want[0] + c[1] * want[1] + c[2] * want[2] for c in stars_at) < math.cos(math.radians(r_)), "objects.dat still has stars at %s's place, which was cut: rerun prepare_objects.py" % label
    assert (SHIP / "objects-atlas.res").stat().st_size < 16 * 1048576, "objects-atlas.res is over its 16 MiB budget"
    record = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))
    runtime = {entry["file"]: entry for entry in record["runtime"]}
    for name in ("objects.dat", "objects-atlas.res"):
        assert runtime[name]["bytes"] == (SHIP / name).stat().st_size, "space-source.json has another size for " + name
    return {"triangles": vertices // 3}


def shader_constant_float(source, name):
    match = re.search(r"const\s+float\s+" + name + r"\s*=\s*([-0-9.eE+]+)", source)
    assert match, "a sky shader has no constant " + name
    return float(match.group(1))


def check_cities():
    """The city mesh: same planet, geography, air and cloud shell as the sky, the sky's own cloud map, at infinity. Its constants are copies, so they cannot be allowed to drift."""
    import ast
    sky = (SHIP / "space.gdshader").read_text()
    cities = (SHIP / "cities.gdshader").read_text()
    for name in ("planet_direction", "sun"):
        assert shader_vec3(sky, name) == shader_vec3(cities, name), name + " differs between space.gdshader and cities.gdshader"
    for name in ("planet_distance", "limb_fall", "city_gain"):
        assert shader_float(sky, name) == shader_float(cities, name), name + " differs between space.gdshader and cities.gdshader"
    for name in ("CAP_N0", "CAP_EAST", "CAP_NORTH"):
        assert shader_vec3_constant(sky, name) == shader_vec3_constant(cities, name), name + " differs between space.gdshader and cities.gdshader"
    basis = [re.search(r"const\s+mat3\s+GEO_BASIS\s*=\s*mat3\(([^;]*)\);", text).group(1) for text in (sky, cities)]
    assert basis[0] == basis[1], "GEO_BASIS differs between space.gdshader and cities.gdshader"
    for name in ("BELT_TOP", "BELT_SCALE", "RING_LO", "RING_HI", "AIR_SOFT", "AIR_TAU", "LIMB_NEAREST", "CLOUD_H"):
        assert shader_constant_float(sky, name) == shader_constant_float(cities, name), name + " differs between space.gdshader and cities.gdshader"
    # Inline copies in the vertex stage.
    for text in ("d2 * (108.17 + d2 * (-215.83 + d2 * 338.51))", "(1.0 - smoothstep(5.0, 9.0, inside_deg))", "smoothstep(-0.20, -0.02, ndl)"):
        assert text in sky and text in cities, text + " differs between space.gdshader and cities.gdshader"
    # A light's shape must not follow what fades, or a hub blinks as it crosses SKIRT_FROM; its skirt reads the light before the room's dimmer, or a metro loses its glow in Focus.
    assert cities.index("extent = amp > SKIRT_FROM") < cities.index("amp *= limb"), "cities.gdshader: a light's extent must come from its amplitude before any fade"
    assert "earth_gain" not in cities[cities.index("amp *= limb"):cities.index("float dim =")], "cities.gdshader: the room's dimmer must stay out of the fades"
    assert cities.index("float wide = smoothstep(SKIRT_FROM, 1.4, amp);") < cities.index("min(amp * dim, CITY_CAP"), "cities.gdshader: the skirt must read the light before the room's dimmer"
    assert "vec4(mat3(MODELVIEW_MATRIX) * corner_dir, 0.0)" in cities, "cities.gdshader no longer draws at w = 0"
    assert "global uniform vec2 earth_spin;" in cities and "global uniform float earth_gain;" in cities, "cities.gdshader must read the two globals"
    code = re.sub(r"//[^\n]*", "", cities)
    assert not re.search(r"\bTIME\b", code), "cities.gdshader reads TIME"
    tree = ast.parse((HERE / "prepare_cities.py").read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if isinstance(node.targets[0], ast.Tuple) and [t.id for t in node.targets[0].elts] == ["AMP_MIN", "AMP_MAX"]:
                constants["AMP_MIN"], constants["AMP_MAX"] = ast.literal_eval(node.value)
            elif isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("MAGIC", "MAX_QUADS"):
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    amp_min = shader_constant_float(cities, "AMP_MIN")
    assert abs(amp_min - constants["AMP_MIN"]) <= 1e-9, "AMP_MIN differs between cities.gdshader and prepare_cities.py"
    assert abs(shader_constant_float(cities, "AMP_LOG_RANGE") - math.log(constants["AMP_MAX"] / constants["AMP_MIN"])) <= 1e-3, "AMP_LOG_RANGE differs from prepare_cities.py"
    magic, vertices, indices = struct.unpack("<III", (SHIP / "cities.dat").read_bytes()[:12])
    assert magic == constants["MAGIC"] and vertices % 4 == 0 and indices == vertices // 4 * 6, "cities.dat header is not quads"
    assert vertices // 4 <= constants["MAX_QUADS"], "Too many city quads: %d" % (vertices // 4)
    assert (SHIP / "cities.dat").stat().st_size == 12 + vertices * 16 + indices * 4, "cities.dat size does not match its header"
    room = (SHIP / "starship_room.gd").read_text()
    assert 'set_shader_parameter("detail"' in room, "starship_room.gd does not bind the cloud detail tile: it would read black"
    assert 'set_shader_parameter("clouds", sky_material.get_shader_parameter("clouds"))' in room, "The city lights must share the sky's cloud map"
    record = json.loads((SHIP / "space-source.json").read_text(encoding="utf-8"))
    runtime = {entry["file"]: entry for entry in record["runtime"]}
    for name in ("cities.dat", "cloud-detail.res"):
        assert runtime[name]["bytes"] == (SHIP / name).stat().st_size, "space-source.json has another size for " + name
    return {"quads": vertices // 4, "triangles": vertices // 2}


LOCAL_PATH = re.compile(rb"[A-Za-z]:(?:\\\\|\\|/)+(?:Users|Documents and Settings)(?:\\\\|\\|/)|/(?:home|Users)/[^/\s\"']+/")


def local_paths(collected):
    """Shipped ship files must not carry a drive, home or workspace path (bake manifests once did)."""
    home = str(Path.home())
    markers = {home.encode(), home.replace("\\", "/").encode(), home.replace("\\", "\\\\").encode()}
    leaks = []
    for name, path in sorted(collected.items()):
        if not (name.startswith("starship/") or name == "environments/starship-thumb.png"):
            continue
        data = path.read_bytes()
        if LOCAL_PATH.search(data) or any(marker in data for marker in markers):
            leaks.append(name)
    return leaks


def check_package():
    metadata = json.loads((SHIP / "starship.json").read_text())
    expected = {"starship/" + name for name in SHIP_FILES}
    expected.add("environments/starship-thumb.png")
    assert metadata.get("parts"), "Ship manifest has no geometry"
    for part in metadata["parts"]:
        for suffix in (".bin", "-lighting.res", "-albedo.res"):
            expected.add("starship/" + part["name"] + suffix)
    spec = importlib.util.spec_from_file_location("cinema_public_collector", HERE.parent / "release/build_public.py")
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    collected = collector.collect(PROJECT)
    missing = sorted(expected - collected.keys())
    assert not missing, "Public collector omits required ship files: " + str(missing)
    assert "test_starship_integration.gd" not in collected, "Development integration fixture would ship"
    assert "test_starship_surround.gd" not in collected, "Development geometry fixture would ship"
    tests = sorted(name for name in collected if Path(name).name.startswith("test_"))
    assert not tests, "Development test scripts would ship: " + str(tests)
    constants = check_constants(metadata)
    print("Sky constants agree between space.gdshader and starship.json:", constants, flush=True)
    round_earth = check_round_earth(metadata)
    print("The Earth is one rigid sphere (shader, bake, belt frame, proof):", round_earth, flush=True)
    turning = check_turning_earth()
    print("The Earth turns on a global uniform, from maps that match the shader:", turning, flush=True)
    galaxy = check_galaxy()
    print("Galaxy basis agrees between space.gdshader, space-source.json and prepare_dust.py:", galaxy, flush=True)
    stars = check_stars()
    print("Star mesh agrees with space.gdshader and prepare_stars.py:", stars, flush=True)
    cities = check_cities()
    print("City mesh agrees with space.gdshader and prepare_cities.py:", cities, flush=True)
    objects = check_objects()
    print("Deep-sky node agrees with space.gdshader:", objects, flush=True)
    leaks = local_paths(collected)
    assert not leaks, "Shipped ship files contain local paths: " + str(leaks)
    print("No local paths in", sum(1 for n in collected if n.startswith("starship/")), "shipped ship files.", flush=True)
    records = {
        name: {"bytes": collected[name].stat().st_size,
               "sha256": hashlib.sha256(collected[name].read_bytes()).hexdigest()}
        for name in sorted(expected)
    }
    report = {"scope": "Public collector only; no installer built or published",
              "required_files": len(records), "runtime_bytes": sum(r["bytes"] for r in records.values()),
              "test_scripts_excluded": True, "local_paths": leaks, "sky_constants_max_error": constants, "round_earth": round_earth, "turning_earth": turning,
              "galaxy_basis": galaxy, "stars": stars, "cities": cities, "objects": objects, "files": records}
    (OUTPUT / "package-files.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Public collector includes all", len(records), "required ship files; excludes both fixtures.", flush=True)


def stage():
    STAGE.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = STAGE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / name, target)
    shutil.copytree(SHIP, STAGE / "starship", dirs_exist_ok=True)
    font_candidates = [PROJECT / "InterVariable.ttf", ROOT / ".local/prime-plex-ui-fixture/InterVariable.ttf"]
    font = next((path for path in font_candidates if path.is_file()), None)
    if font is None:
        raise FileNotFoundError("InterVariable.ttf is needed to check the actual room menu")
    shutil.copy2(font, STAGE / "InterVariable.ttf")
    (STAGE / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/name="Frame Cinema ship integration fixture"\n'
        'config/use_custom_user_dir=true\nconfig/custom_user_dir_name="s"\n'
        '[rendering]\nrenderer/rendering_method="mobile"\n'
        '[display]\nwindow/size/viewport_width=64\nwindow/size/viewport_height=64\n'
    )


def check_image_quality():
    """The renders that last wrote preview/compare/stats.json (stage_preview.py --install) must pass the shimmer gate and the lamp limit."""
    report = HERE / "preview/compare/stats.json"
    if not report.exists():
        print("SHIP_IMAGE_QUALITY_SKIPPED: no preview/compare/stats.json; the render comparison tool is not in this repository")
        return
    stats = json.loads(report.read_text())
    shimmer = stats.get("shimmer", {})
    assert len(shimmer) == 6, "stats.json has %d headset sequences, expected 6" % len(shimmer)
    worst = {name: entry["tile_p99_max"] for name, entry in shimmer.items() if entry["tile_p99_max"] > 12}
    assert not worst, "Shimmer gate (tile p99 at most 12): %s" % worst
    peak = stats.get("lens_peak", {})
    assert set(peak) == {"L055", "L100", "gate_1_6"}, "stats.json has no lens peak record at both room lights"
    assert peak["gate_1_6"], "Lamp pixels over 1.6 linear: %s" % peak
    assert stats.get("real_sky", {}).get("ok"), "Real-sky star gates: %s" % stats.get("real_sky")
    print("SHIP_IMAGE_QUALITY_OK shimmer", max(entry["tile_p99_max"] for entry in shimmer.values()), "lamp peak", peak["L055"]["max"], peak["L100"]["max"])


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    check_package()
    check_image_quality()
    stage()
    log_path = OUTPUT / "integration.log"
    args = [str(GODOT), "--path", str(STAGE), "--xr-mode", "off", "--audio-driver", "Dummy",
            "--rendering-method", "mobile", "--resolution", "64x64", "--position", "-10000,-10000",
            "--log-file", str(log_path), "--script", "res://test_starship_integration.gd"]
    env = dict(os.environ, APPDATA=str(ROOT / ".local/ship-test-data"), FRAME_CINEMA_STARSHIP_TEST_OUT=str(OUTPUT))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    result = subprocess.run(args, env=env, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW, timeout=180)
    log = log_path.read_text(errors="replace")
    print(log[-6000:])
    if result.returncode or "SCRIPT ERROR" in log or "SHADER ERROR" in log or "ERROR:" in log:
        raise RuntimeError("Ship integration failed; inspect " + str(log_path))
    proof = json.loads((OUTPUT / "integration.json").read_text())
    assert not proof["failures"], proof["failures"]
    assert (OUTPUT / "room-menu.png").is_file(), "Actual menu was not rendered"
    print("SHIP_INTEGRATION_OK", proof["checks"], "checks; desktop only, not headset validation.")


if __name__ == "__main__":
    run()
