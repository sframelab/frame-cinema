# Rooms

Rooms share a seated eye height of 1.65 m and a screen 4.5 m ahead. SteamVR
draws the video as a separate overlay; room geometry and shaders provide the
surroundings and respond to the screen's light.

| Room | Menu name | Folder | Saved index |
|---|---|---|---|
| Moon | Lunar Landscape | `app/lunar/` | 3 |
| Coast | Coastal Dusk | `app/coast/` | 4 |
| Dark Room | Dark Room | Drawn in code | 5 |
| Desert | Desert Alcove | `app/desert/` | 6 |
| Observation Deck | Observation Deck | `app/starship/` | 8 |

Room indices are stored in user preferences. Keep them stable and do not reuse
the retired indices 0–2 or 7.

## Room files

- **Script:** `cinema_rooms.gd` loads the room, calls `setup()` and caches it.
  Later switches show or hide the cached room. `set_light()` adjusts room
  lighting; `refresh_transform()` handles recentering.
- **Meshes:** `.bin` files hold positions, normals, tangents, UVs and triangle
  indices, loaded directly into Godot arrays.
- **Baked lighting:** textures such as `*-lighting.res` and `*-albedo.res`
  store precomputed lighting and color in GPU formats, including BC6H.
  This reduces the lighting work needed during playback.
- **Shaders:** water, sand, sky and reflections respond or move at runtime.
- **Manifest:** `package.json` records file sizes, SHA-256 hashes, sources and
  licenses. Its presence makes the room available in the app; the build also
  verifies the Observation Deck's file hashes.
- **Thumbnail:** `app/environments/<id>-thumb.png`, a 768×480 render.

## Screen lighting

`ambient_sampler` samples the browser surface at 384×216 and passes edge colors
to `cinema_ambient.gd`. Room shaders use those colors to light nearby surfaces.
The samples remain on the headset; see [Privacy](../release/PRIVACY.md) for
storage details.

The **Environment** menu controls ambient mode and brightness. **Focus** dims
the room and the Observation Deck's sky.

## Performance

Measure room frame times on the headset with video playing, in several viewing
directions. The app targets 72 Hz, but room rendering shares that frame time
with the rest of the app and compositor. A fast desktop preview does not prove
headset performance.

Keep mesh and texture sizes close to the existing rooms. The Observation Deck
has a 180,000-triangle limit, checked by `verify_geometry.py`. That check does
not measure frame time.

## Observation Deck

The Deck is an orbital lounge above Earth's night side, with city lights below
and the Milky Way overhead. Its build tools are in
[`rooms/observation-deck/`](../rooms/observation-deck/README.md):

1. `build_interior.py` generates the cabin in Blender.
2. `build_runtime.py` bakes lighting in Cycles and exports meshes.
3. `pack_textures.gd` creates Godot image resources. `stage_preview.py` renders
   previews and can copy a bake into `app/starship/`.
4. The `prepare_*.py` scripts process Earth and sky data; `pack_earth.gd` packs
   the maps.

The cabin and lighting can be rebuilt here. Rebuilding the star mesh still
requires intermediate files from tools not included in the repository.

## Moon, Coast and Desert

These rooms use Poly Haven CC0 scans and skies, with reduced geometry and baked
lighting. Asset sources are listed in each room's `package.json` and in
[Third-party notices](../THIRD_PARTY_NOTICES.md).

The original asset-generation scripts depend on a private working directory
and are not included. The runtime scripts and shaders are in `app/`;
[`rooms/coast/tools/`](../rooms/coast/tools/README.md) contains tools for
editing the Coast floor and its lighting.

## Adding a room

1. Create a folder such as `app/greenhouse/` with a `Node3D` script implementing
   `setup(prefix, environment)`, `set_light(level)` and `refresh_transform()`.
   Use `app/desert/desert_room.gd` as a starting point.
2. Add a `package.json` with file hashes, sources and licenses.
3. Append the room ID and menu name to `IDS` and `NAMES` in
   `app/cinema_rooms.gd`. Update `available()`, `available_indices()` and `_build()`.
4. Add a 768×480 seated-view thumbnail at `app/environments/<id>-thumb.png`.
5. Use the shared seat and screen coordinates.
6. Add large files to the release and `assets.json`.
7. Check appearance and frame timing on the headset with video playing.
