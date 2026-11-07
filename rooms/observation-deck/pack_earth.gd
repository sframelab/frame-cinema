extends SceneTree
# Package the prepared sky data as mipmapped, compressed Image resources, without imports.
# Usage:
#   Godot --headless --path <project> --script <absolute>/pack_earth.gd -- \
#     --input <prepared-directory> --output <directory> [--mode belt|cap|equirect] [--only name,name]
# Or set FRAME_CINEMA_EARTH_INPUT / FRAME_CINEMA_EARTH_OUTPUT.
# Inputs (each packed when present; at least one is required):
#   earth-surface.png, earth-masks.png -> BC7 with mips, 4:1 (belt mode, the default). earth-clouds.png -> the same, 8192x2880: its 1 km source has rows to fill, and under 32 MiB the renderer's upload memory stays where it was.
#   cloud-detail.png -> one channel, mips, BC4, square.
#   earth-day.png, earth-extra.png -> BC7 with mips; square in cap mode, 2:1 in equirect mode.
#   galaxy.exr -> RGBH, mips, BC6H (BPTC float); must be 4:1.
# Output defaults to input. The receipt (sky-pack-receipt.json) is always written next to
# the inputs, so packing straight into project/starship never ships it. Copy the .res files
# into project/starship afterwards. Source NASA originals are not used or modified here.

const EARTH := {"belt": ["earth-surface", "earth-masks", "earth-clouds"], "cap": ["earth-day", "earth-extra"], "equirect": ["earth-day", "earth-extra"]}
const EARTH_ASPECT := {"belt": 4.0, "cap": 1.0, "equirect": 2.0}
const CLOUD_BELT_ASPECT := 8192.0 / 2880.0

func _initialize() -> void:
	var input := OS.get_environment("FRAME_CINEMA_EARTH_INPUT")
	var output := OS.get_environment("FRAME_CINEMA_EARTH_OUTPUT")
	var mode := "belt"
	var only := PackedStringArray()
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		var argument := args[index]
		if argument in ["--help", "-h"]:
			print("pack_earth.gd -- --input <dir> [--output <dir>] [--mode belt|cap|equirect] [--only earth-surface,earth-masks,earth-clouds,galaxy]")
			quit()
			return
		if argument not in ["--input", "--output", "--mode", "--only"] or index + 1 >= args.size():
			push_error("Expected --input, --output, --mode or --only followed by a value.")
			quit(2)
			return
		var value := args[index + 1]
		match argument:
			"--input": input = value
			"--output": output = value
			"--mode": mode = value
			"--only": only = value.split(",", false)
		index += 2
	if mode not in EARTH:
		push_error("--mode must be belt, cap or equirect.")
		quit(2)
		return
	if input.is_empty():
		push_error("Set --input or FRAME_CINEMA_EARTH_INPUT.")
		quit(2)
		return
	if output.is_empty():
		output = input
	if not input.is_absolute_path() or not output.is_absolute_path():
		push_error("Use absolute input/output directories so packaging is independent of the project path.")
		quit(2)
		return
	if DirAccess.make_dir_recursive_absolute(output) != OK:
		push_error("Could not create output directory: " + output)
		quit(2)
		return
	var jobs: Array[Dictionary] = []
	for name in EARTH[mode]:
		jobs.append({"name": name, "file": name + ".png", "aspect": CLOUD_BELT_ASPECT if mode == "belt" and name == "earth-clouds" else EARTH_ASPECT[mode],
			"format": "BPTC RGBA UNORM (BC7)"})
	jobs.append({"name": "cloud-detail", "file": "cloud-detail.png", "aspect": 1.0, "format": "RGTC R (BC4)"})
	jobs.append({"name": "galaxy", "file": "galaxy.exr", "aspect": 4.0, "format": "BPTC RGB unsigned float (BC6H)"})
	var records: Array[Dictionary] = []
	for job in jobs:
		if not only.is_empty() and not only.has(job.name):
			continue
		var source: String = input.path_join(job.file)
		if not FileAccess.file_exists(source):
			print("SKY_PACK_SKIP ", job.name)
			continue
		var data := Image.load_from_file(source)
		if data == null or data.is_empty():
			push_error("Could not load: " + source)
			quit(2)
			return
		if data.get_width() != int(round(data.get_height() * float(job.aspect))):
			push_error("Expected a %s:1 texture for %s (%s mode), got %dx%d" % [str(job.aspect), job.name, mode, data.get_width(), data.get_height()])
			quit(2)
			return
		if job.name == "galaxy":
			data.convert(Image.FORMAT_RGBH)
		if job.name == "cloud-detail":
			data.convert(Image.FORMAT_R8)
		data.generate_mipmaps()
		if data.compress(Image.COMPRESS_S3TC if job.name == "cloud-detail" else Image.COMPRESS_BPTC, Image.COMPRESS_SOURCE_GENERIC) != OK:
			push_error("Compression failed: " + job.name)
			quit(2)
			return
		var destination := output.path_join(str(job.name) + ".res")
		if ResourceSaver.save(data, destination) != OK:
			push_error("Could not save: " + destination)
			quit(2)
			return
		var record := {"file": str(job.name) + ".res", "width": data.get_width(), "height": data.get_height(),
			"format": job.format, "image_format": data.get_format(), "gpu_bytes_with_mips": data.get_data_size(),
			"bytes": FileAccess.open(destination, FileAccess.READ).get_length(),
			"sha256": FileAccess.get_sha256(destination)}
		records.append(record)
		print("SKY_PACK ", JSON.stringify(record))
	if records.is_empty():
		push_error("Nothing to pack in " + input)
		quit(2)
		return
	# Merge with an earlier receipt so separate Earth and galaxy runs keep one record per file.
	var receipt_path := input.path_join("sky-pack-receipt.json")
	var merged: Array = records.duplicate()
	if FileAccess.file_exists(receipt_path):
		var previous: Variant = JSON.parse_string(FileAccess.get_file_as_string(receipt_path))
		if previous is Dictionary and previous.get("textures") is Array:
			var fresh := records.map(func(r): return r.file)
			for old in previous.textures:
				if old is Dictionary and not fresh.has(old.get("file")):
					for key in old:
						if old[key] is float and old[key] == floorf(old[key]):
							old[key] = int(old[key])
					merged.append(old)
	var receipt := FileAccess.open(receipt_path, FileAccess.WRITE)
	if receipt == null:
		push_error("Could not write packing receipt.")
		quit(2)
		return
	receipt.store_string(JSON.stringify({"engine": Engine.get_version_info().string, "mode": mode, "output": output,
		"textures": merged}, "\t") + "\n")
	receipt.close()
	quit()
