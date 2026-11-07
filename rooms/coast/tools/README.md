# Coast floor tools

These tools edit the Coast's floor meshes and baked lighting. They were used to
restore scan detail under the pebble texture and fix a ledge that intersected
the pebble beds.

Fetch the packed assets in `app/coast/` with `tools/fetch_assets.py` first.
The tools require Godot 4.7.2 and Python with `numpy` and `Pillow`.

| Tool | Usage |
|---|---|
| `dump_raw.gd` | Extracts Godot images to raw float RGBA and preview PNGs. Run headless in a Godot project; set `DUMP_LIST` to `input.res\|output` pairs separated by `;` |
| `bake_merge.py` | Restores scan detail within the pebble bands while retaining the newer bake's lighting |
| `ledge_fix.py` | Lowers the intersecting ledge: `ledge_fix.py <coast folder> <new middle-ledge.bin>` |
| `uncover_relight.py` | Relights the newly exposed pebbles: `uncover_relight.py <original coast folder> <bake-merge folder>` |
| `pack_raw.gd` | Packs raw float RGBA into BC6H Godot images with mipmaps. Set `PACK_LIST` to `input.raw\|output.res\|size` entries |
