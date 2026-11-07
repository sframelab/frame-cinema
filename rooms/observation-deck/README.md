# Observation Deck

The Observation Deck is an orbital lounge above Earth's night side, with a
glass canopy, navy sofas and a reflective floor. It uses room index 8 and the
internal folder name `app/starship/`.

The cabin uses geometry at meter scale and lighting baked in Blender's Cycles.
Floor reflections, screen lighting, lamp halos and the sky render at runtime.

## Tools

| File | What it does |
|---|---|
| `build_interior.py` | Generates the cabin geometry, furniture, lamps and bake lights in Blender |
| `build_runtime.py` | Bakes light and colour per part in Cycles, makes the deck's reflection map, and exports the meshes and `starship.json` |
| `bake-params.json` | The tuned light levels the bake uses; command-line flags override them |
| `pack_textures.gd`, `pack_final.gd` | Pack the bake's EXR maps into the Godot images the app loads |
| `stage_preview.py`, `preview.gd` | Render the room on a PC from fixed views, and with `--install` copy a bake into `app/starship/` and refresh its `package.json` |
| `view_room.py`, `inspect.gd` | Interactive desktop viewer |
| `prepare_earth.py`, `make_cloud_tile.py`, `build_cloud_belt.py`, `prepare_cities.py` | The turning Earth: surface, water, clouds and city lights from NASA's maps |
| `prepare_galaxy.py`, `prepare_dust.py`, `prepare_mw_peaks.py` | The Milky Way's glow and dark dust from NASA's Deep Star Maps |
| `prepare_stars.py` | Builds `stars.dat` from the Yale Bright Star Catalogue and peaks extracted from the Deep Star Maps |
| `pack_earth.gd` | Packs the Earth and Milky Way maps |
| `verify_geometry.py`, `verify_limb.py`, `check_integration.py` | Check mesh validity, triangle count, Earth's circular silhouette and app integration |
| `remove_collapsed_faces.py` | An older fix for zero-area triangles, kept for old bakes |

## Rebuilding

Run these from the repository root. Set `B` to Blender 4.5 LTS, `G` to Godot 4.7.2
and `PY` to a Python with `numpy` and `Pillow`. The scripts keep their working
files in `.local/`, which git ignores. The checks start Godot themselves, from
`.local/deps/godot-4.7.2/` unless you set `GODOT` to another copy.

```sh
# The cabin as an editable Blender file (optional)
"$B" --background --python rooms/observation-deck/build_interior.py -- --output .local/observation-deck.blend

# Generate the model and bake lighting into a new folder
"$B" --background --python rooms/observation-deck/build_runtime.py -- --output .local/starship-bake --samples 192

# Preview renders on the PC; nothing in app/ changes
"$PY" rooms/observation-deck/stage_preview.py --bake .local/starship-bake

# Copy the reviewed bake into app/starship and refresh package.json
"$PY" rooms/observation-deck/stage_preview.py --bake .local/starship-bake --install

# Checks
"$PY" rooms/observation-deck/verify_geometry.py --package app/starship --max-triangles 180000
"$PY" rooms/observation-deck/verify_limb.py
"$PY" rooms/observation-deck/check_integration.py
```

For lighting-only changes, use `--relight-from .local/starship-bake` to reuse
the geometry. Changes to geometry or materials need a full bake.

To put a picture on the preview screen instead of a dark panel, save it as
`rooms/observation-deck/screen-picture.png`. The menu picture in
`app/environments/starship-thumb.png` was rendered that way, with Poly Haven's
CC0 "Spruit Sunrise" photo on the screen.

### The Earth and the sky

```sh
"$PY" rooms/observation-deck/prepare_earth.py --belt --download-tiles
"$B" --background --python rooms/observation-deck/prepare_galaxy.py
"$G" --headless --path .local/starship-preview --script "$PWD/rooms/observation-deck/pack_earth.gd" -- --input "$PWD/.local/starship-earth/maps" --output "$PWD/.local/starship-earth/packed" --mode belt
```

Copy the packed `.res` files into `app/starship/`, then run
`stage_preview.py --refresh-package`. The NASA sources, their addresses and
hashes are recorded in `app/starship/space-source.json`.

`stars.dat`, the star mesh, ships in the release. `prepare_stars.py` rebuilds it
from the Yale catalogue (`downloads/yale/ybsc5.gz`, from CDS) and lists of bright
points taken from the Deep Star Maps (in `work/`). The tools that make those
lists aren't in this repository. `prepare_galaxy.py` reads NASA's
`downloads/milkyway_2020_8k_gal.exr`.

## Constraints and checks

- Keep the room under 180,000 triangles and measure frame time on the headset.
  `verify_geometry.py` checks triangle count, not performance.
- Every file in `app/starship/` is listed in its `package.json` with its size and
  hash, and the build refuses a mismatch.
- Keep Earth spherical. Animate the sky through a global shader value;
  changing material values each frame triggers sky rendering again.
- `check_integration.py` also reads a render report (`preview/compare/stats.json`)
  from a comparison tool that is not in this repository. Without it, that one
  check is skipped.
