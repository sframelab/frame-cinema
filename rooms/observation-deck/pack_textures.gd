extends SceneTree

# Packs a bake directory's EXRs into compressed Image resources.
# Parts: lighting and albedo, each at its own EXR size (resolutions differ per part).
# Extras (starship.json "extras"): RGBH -> BC6H, RGB8 -> BC7, both with mipmaps.

# Lamp faces, shaped at the pack so it costs nothing at runtime (emission lighting only, before the mips).
# Every emission face is its own two-triangle island, an axis-aligned rectangle in the atlas.
# - LENS_LIMIT scales a texel down to 1.36 keeping its hue: the bake's gloss of each lamp's own spill
#   rect reads up to 8.2, and with BC6H's overshoot 1.36 leaves every lens texel at or under the 1.6 limit.
# - A lens face falls to LENS_RIM over its outer LENS_RAMP_M and its thin box sides sit at LENS_RIM. MSAA
#   only smooths the rim's first step, so a lower step is what stops it crawling. The core stays white-hot.
# - Diode faces lose the warm gloss they pick up from nearby lamps (DIODE_LIMIT, which also removes
#   the dotted white line on the curb tops) and ramp across the strip only, so joints between faces stay
#   lit; DIODE_GAIN keeps the strip's total light.
const LENS_LIMIT := 1.36
const LENS_RIM := 0.45
const LENS_RAMP_M := 0.006
const DIODE_LIMIT := Vector3(0.1, 0.22, 0.6)
const DIODE_RIM := 0.35
const DIODE_RAMP_M := 0.006
const DIODE_GAIN := 1.2
# A ramp takes at most this share of a narrow face; shorter sides than SIDE_FACE_M are box sides.
const RAMP_SHARE := 0.35
const SIDE_FACE_M := 0.0065

func _initialize() -> void:
	var source := OS.get_environment("STARSHIP_BAKE")
	var destination := OS.get_environment("STARSHIP_DEST")
	assert(not source.is_empty() and not destination.is_empty())
	var metadata: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(source.path_join("starship.json")))
	for part in metadata.parts:
		for kind in ["lighting", "albedo"]:
			var name: String = str(part.name) + "-" + str(kind)
			var image := Image.load_from_file(source.path_join(name + ".exr"))
			assert(image != null and not image.is_empty(), name)
			if name == "emission-lighting":
				_shape_lamps(image, source, metadata)
			image.convert(Image.FORMAT_RGBH)
			image.generate_mipmaps()
			assert(image.compress(Image.COMPRESS_BPTC) == OK, name)
			assert(ResourceSaver.save(image, destination.path_join(name + ".res")) == OK, name)
			print("SHIP_TEXTURE ", name, " ", image.get_width(), "x", image.get_height(), " ", image.get_data_size())
	for extra in metadata.get("extras", []):
		var name: String = str(extra.name)
		var path := source.path_join(name + ".exr")
		if not FileAccess.file_exists(path):
			print("SHIP_PACK_SKIP ", name)
			continue
		var image := Image.load_from_file(path)
		assert(image != null and not image.is_empty(), name)
		if name == "deck-mirror":
			_print_marker(image)
		var format := str(extra.get("format", "RGBH"))
		if format == "RGB8":
			image.convert(Image.FORMAT_RGB8)
		else:
			image.convert(Image.FORMAT_RGBH)
		image.generate_mipmaps()
		assert(image.compress(Image.COMPRESS_BPTC) == OK, name)
		assert(ResourceSaver.save(image, destination.path_join(name + ".res")) == OK, name)
		print("SHIP_TEXTURE ", name, " ", image.get_width(), "x", image.get_height(), " ", image.get_data_size(), " ", format)
	quit()

func _shape_lamps(image: Image, source: String, metadata: Dictionary) -> void:
	image.convert(Image.FORMAT_RGBF)
	var width := image.get_width()
	var height := image.get_height()
	var texels := image.get_data().to_float32_array()
	for i in range(0, texels.size(), 3):
		var peak := maxf(texels[i], maxf(texels[i + 1], texels[i + 2]))
		if peak > LENS_LIMIT:
			var scale := LENS_LIMIT / peak
			texels[i] *= scale
			texels[i + 1] *= scale
			texels[i + 2] *= scale
	var file := FileAccess.open(source.path_join("emission.bin"), FileAccess.READ)
	assert(file != null and file.get_32() == 0x524f434b)
	var count := file.get_32()
	var index_count := file.get_32()
	var positions := file.get_buffer(count * 12).to_vector3_array()
	file.get_buffer(count * 28) # normals and tangents
	var uvs := file.get_buffer(count * 8).to_vector2_array()
	var indices := file.get_buffer(index_count * 4).to_int32_array()
	var faces := 0
	var diodes := 0
	for first in range(0, index_count, 6):
		var corners := PackedInt32Array()
		for index in indices.slice(first, first + 6):
			if not corners.has(index):
				corners.append(index)
		assert(corners.size() == 4, "An emission face must be one island of two triangles")
		var low := Vector2(INF, INF)
		var high := -low
		var center := Vector3.ZERO
		for corner in corners:
			var texel := uvs[corner] * Vector2(width, height)
			low = low.min(texel)
			high = high.max(texel)
			center += positions[corner] * 0.25
		# Metres along each atlas axis: the corner pair that lies along it.
		var along_x := -1.0
		var along_y := -1.0
		var best_x := INF
		var best_y := INF
		for a in 4:
			for b in range(a + 1, 4):
				var span := ((uvs[corners[a]] - uvs[corners[b]]) * Vector2(width, height)).abs()
				var metres := positions[corners[a]].distance_to(positions[corners[b]])
				if span.y < best_x:
					best_x = span.y
					along_x = metres
				if span.x < best_y:
					best_y = span.x
					along_y = metres
		var diode := _lamp_kind(center, metadata.glows) == "blue"
		var short := minf(along_x, along_y)
		var rim := DIODE_RIM if diode else LENS_RIM
		var ramp := minf(DIODE_RAMP_M if diode else LENS_RAMP_M, RAMP_SHARE * short)
		var per_x := along_x / maxf(high.x - low.x, 0.001)
		var per_y := along_y / maxf(high.y - low.y, 0.001)
		# Two texels past the rectangle: filtering reads the margin too.
		for y in range(maxi(int(floor(low.y)) - 2, 0), mini(int(ceil(high.y)) + 2, height)):
			for x in range(maxi(int(floor(low.x)) - 2, 0), mini(int(ceil(high.x)) + 2, width)):
				var level := rim
				if short >= SIDE_FACE_M:
					var dx := minf(x + 0.5 - low.x, high.x - x - 0.5) * per_x
					var dy := minf(y + 0.5 - low.y, high.y - y - 0.5) * per_y
					# A diode run is several faces in a line, so only the strip's width ramps.
					var distance := (dx if along_x < along_y else dy) if diode else minf(dx, dy)
					level = lerpf(rim, 1.0, smoothstep(0.0, ramp, distance))
				var at := (y * width + x) * 3
				if diode:
					texels[at] = minf(texels[at], DIODE_LIMIT.x) * DIODE_GAIN
					texels[at + 1] = minf(texels[at + 1], DIODE_LIMIT.y) * DIODE_GAIN
					texels[at + 2] = minf(texels[at + 2], DIODE_LIMIT.z) * DIODE_GAIN
				texels[at] *= level
				texels[at + 1] *= level
				texels[at + 2] *= level
		faces += 1
		if diode:
			diodes += 1
	image.set_data(width, height, false, Image.FORMAT_RGBF, texels.to_byte_array())
	print("SHIP_LAMPS_SHAPED faces=", faces, " diode_faces=", diodes)

# The lamp a face belongs to, by its centre against glows.json's mounting boxes.
func _lamp_kind(center: Vector3, glows: Array) -> String:
	for glow in glows:
		var c := Vector3(glow.c[0], glow.c[1], glow.c[2])
		var n := Vector3(glow.n[0], glow.n[1], glow.n[2])
		var u := Vector3(glow.u[0], glow.u[1], glow.u[2])
		var offset := center - c
		if absf(offset.dot(u)) <= float(glow.size[0]) * 0.5 + 0.012 and absf(offset.dot(n.cross(u))) <= float(glow.size[1]) * 0.5 + 0.012 and absf(offset.dot(n)) <= 0.03:
			return str(glow.kind)
	assert(false, "An emission face belongs to no lamp")
	return ""

# Brightest pixel of the mirror map, for the orientation re-check against the bake log.
func _print_marker(image: Image) -> void:
	var best := -1.0
	var at := Vector2i.ZERO
	for y in image.get_height():
		for x in image.get_width():
			var c := image.get_pixel(x, y)
			var value := c.r + c.g + c.b
			if value > best:
				best = value
				at = Vector2i(x, y)
	print("SHIP_MIRROR_MARKER ", at.x, " ", at.y)
