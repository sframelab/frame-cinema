extends Node3D

# Observation Deck runtime (2026-11-02 v4). Room space is Godot metres: eye (0, 1.65, 0),
# forward -Z, deck tops .480, screen centre (0, 2.1, -4.5). All lighting is baked; the
# runtime adds only cheap per-pixel terms: the deck's parallax mirror lookup (and its
# movie-field variant while ambient glow is on), an analytic movie light, one draw of
# additive lamp halos, the near-black screen housing and the sky. No post-processing and
# no scene lights: Cinema's two screen OmniLights stay hidden here (set_screen_spill). The stars are one
# additive mesh at infinity (stars.gdshader); the room dimmer reaches neither them nor the Milky Way.

# Fixed paths, so _build_surround() works before setup() (the surround test).
const SURROUND_SHADER := preload("res://starship/surround.gdshader")
const GLOW_SHADER := preload("res://starship/glow.gdshader")
const PART_SPILL := {"deck": 0.6, "shell": 0.35, "detail": 0.5, "trim": 0.5, "seating": 0.8, "viewer": 0.8, "emission": 0.0}
const PART_RIM := {"shell": 0.9, "detail": 0.6, "trim": 0.5}
const RUNTIME_DEFAULTS := {"mirror_strength": 1.6, "screen_gain": 0.8, "glow_amber": 0.35, "glow_blue": 0.30,
	"mirror_f0": 0.04, "mirror_f90": 1.0, "mirror_fresnel_pow": 5.0, "sheen_albedo_ref": 0.035,
	"slit_glow": 1.0, "blue_pool": 0.12, "bed_gloss": 0.4}
# Non-scalar runtime keys (bake-params.json "runtime"): the deck's cool satin sheen (linear RGB)
# and the reflection strength across the wear map (scuffed, polished). Defaults are inert/v4.
const RUNTIME_VECTORS := {"sheen": [0.0, 0.0, 0.0], "wear_range": [0.55, 1.2], "screen_sheen": [0.012, 0.014, 0.020]}
const AMBER_TINT := Color(1.0, 0.40, 0.10)
const BLUE_TINT := Color(0.10, 0.35, 1.0)
const AMBER_SIGMA := 0.022
const BLUE_SIGMA := 0.025
const GLOW_MARGIN := 0.06
# Vertex colours are 8-bit: glow.gdshader doubles COLOR.rgb and reads sigma as COLOR.a/10.
const GLOW_COLOR_SCALE := 0.5
# Warm white: a 2-4 px slit core must read white-hot through AgX, like the baked lens cores.
const SLIT_COLOR := Color(1.0, 0.78, 0.50)
# Slit spill on the post face: exp(-d^2 / SPILL_K), d in metres from the slit edge.
const SPILL_K := 0.0002
# The housing slits sit in a dark monolith: a tighter halo than the cabin lamps.
const SLIT_SIGMA := 0.012
const PROFILE_VARIANTS := ["deck as hull", "field off", "movie light off", "PracticalGlow hidden", "stars hidden", "cities hidden", "objects hidden"]
# Movie light. Energy is Cinema's two lights together (10 x peak x gain each) plus a little for the
# dark cabin; the source sits at their midpoint, 1.25 m in front of the picture and .45 m below
# its centre. MOVIE_LIMIT is the soft limit in _apply_spill.
const MOVIE_ENERGY := 24.0
const MOVIE_LIMIT := 1.0
const MOVIE_SOURCE_DROP := 0.45
const MOVIE_SOURCE_AHEAD := 1.25
# Every star is one triangle in the sky and every city light one quad, so their 2 m mesh bounds mean nothing: this box always holds the eye.
const STAR_BOX := 1000.0
# The Earth follows the light only below the default level, down to EARTH_FOCUS at Focus (room light .12), and never
# rises past the default. The ramp is much slower than the lamps: it reads as eyes adapting, not as a dimmer on the
# planet. A global uniform, so its frames do not re-render the radiance map (see space.gdshader).
const EARTH_FOCUS := 0.55
const EARTH_RAMP_SECONDS := 15.0
const FOCUS_LIGHT := 0.12
const DEFAULT_LIGHT := 0.55
# The Earth turns at ten times the true rate, one turn in 2.4 hours (since 0.5.15; 0.5.14 turned at 30), surface moving
# east, so the ground comes out of the limb toward the viewer. The clock is the app's, so each launch opens on the view
# space.gdshader holds at spin 0.
const EARTH_DEG_PER_HOUR := 150.0
# Clouds run 8% ahead of the ground, so they cross the lights instead of riding on them.
const CLOUD_SPEED := 1.08

var metadata: Dictionary = {}
var triangles := 0
# Every material that follows the room light linearly (hull parts, deck variants).
var materials: Array[ShaderMaterial] = []
# Emission part: follows the emitter curve e = min(s, 1.15)^1.7.
var emission_materials: Array[ShaderMaterial] = []
var runtime := RUNTIME_DEFAULTS.merged(RUNTIME_VECTORS)
var deck_node: MeshInstance3D
var deck_material: ShaderMaterial
var deck_field_material: ShaderMaterial
var deck_hull_material: ShaderMaterial
var practical_glow: MeshInstance3D
var sky_material: ShaderMaterial
var sky_resource: Sky
var star_node: MeshInstance3D
var star_material: ShaderMaterial
var object_node: MeshInstance3D
var object_material: ShaderMaterial
var city_node: MeshInstance3D
var city_material: ShaderMaterial
var earth_level := 1.0
var earth_ramp: Tween
var earth_settled := false
var saved_basis := Basis(Vector3.ZERO, Vector3.ZERO, Vector3.ZERO)
var screen_center := Vector3(0, 2.1, -4.5)
var screen_width := 4.2
var screen_surround: Node3D
var surround_material: ShaderMaterial
var glow_material: ShaderMaterial
var amber_material: StandardMaterial3D
var shadow_material: StandardMaterial3D
var housing_width := -1.0
var housing_slits: Array[Rect2] = []
var room_light := 0.55
var last_light := -1.0
var source_root := ""
# Cinema's ambient glow reads this (cinema_ambient.gd): a halo tight enough for the glass cabin
# that still shows past the housing, no haze sheet over the stars.
var ambient_profile := {"haze": false, "halo_spread": 0.7}
var field_texture: Texture2D
var field_size := Vector2.ZERO
var field_gain := 0.0
var profile_deck_hull := false
var profile_field_off := false
var profile_movie_off := false
# The movie light's inputs from cinema_ambient.gd: left and right spill, then the top, right,
# bottom and left edge averages, all before the mode's gain.
var spill_colors := PackedColorArray()
var spill_gain := 0.0
var spill_picture := Vector2.ZERO
# Every material that takes the movie light: the hull parts and the deck's field variant.
var movie_materials: Array[ShaderMaterial] = []

static func mesh_file(path: String) -> ArrayMesh:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null and file.get_32() == 0x524f434b, "Invalid ship mesh: " + path)
	var count := file.get_32()
	var indices := file.get_32()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_NORMAL] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_TANGENT] = file.get_buffer(count * 16).to_float32_array()
	arrays[Mesh.ARRAY_TEX_UV] = file.get_buffer(count * 8).to_vector2_array()
	arrays[Mesh.ARRAY_INDEX] = file.get_buffer(indices * 4).to_int32_array()
	assert(file.get_position() == file.get_length(), "Truncated ship mesh: " + path)
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

# stars.dat (prepare_stars.py): a table of direction chunks, each with its own box, then positions and RGBA8 per vertex, no normals, UVs or indices. A vertex is one corner of a
# star's triangle as a direction; stars.gdshader reads the tint and amplitude from CUSTOM0. star_mesh_chunks gives [mesh, box] per chunk; star_mesh_file is the whole sky as one mesh, for tools.
static func star_mesh_chunks(path: String, whole := false) -> Array:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null and file.get_32() == 0x32525453, "Invalid star mesh: " + path)
	var chunks := file.get_32()
	var count := file.get_32()
	var table := []
	for i in chunks:
		var first := file.get_32()
		var length := file.get_32()
		var low := Vector3(file.get_float(), file.get_float(), file.get_float())
		var high := Vector3(file.get_float(), file.get_float(), file.get_float())
		table.append([first, length, AABB(low, high - low)])
	var positions := file.get_buffer(count * 12)
	var colours := file.get_buffer(count * 4)
	assert(file.get_position() == file.get_length(), "Truncated star mesh: " + path)
	if whole:
		table = [[0, count, AABB()]]
	var result := []
	for row in table:
		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = positions.slice(row[0] * 12, (row[0] + row[1]) * 12).to_vector3_array()
		arrays[Mesh.ARRAY_CUSTOM0] = colours.slice(row[0] * 4, (row[0] + row[1]) * 4)
		var mesh := ArrayMesh.new()
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], {}, Mesh.ARRAY_CUSTOM_RGBA8_UNORM << Mesh.ARRAY_FORMAT_CUSTOM0_SHIFT)
		result.append([mesh, row[2]])
	return result

static func star_mesh_file(path: String) -> ArrayMesh:
	return star_mesh_chunks(path, true)[0][0]

# objects.dat (prepare_objects.py): deep-sky objects. Directions, atlas coordinates and RGBA8 per vertex, no index;
# objects.gdshader tells a star from a sprite by CUSTOM0.a.
static func object_mesh_file(path: String) -> ArrayMesh:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null and file.get_32() == 0x534A424F, "Invalid object mesh: " + path)
	var count := file.get_32()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_TEX_UV] = file.get_buffer(count * 8).to_vector2_array()
	arrays[Mesh.ARRAY_CUSTOM0] = file.get_buffer(count * 4)
	assert(file.get_position() == file.get_length(), "Truncated object mesh: " + path)
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], {}, Mesh.ARRAY_CUSTOM_RGBA8_UNORM << Mesh.ARRAY_FORMAT_CUSTOM0_SHIFT)
	return mesh

# cities.dat (prepare_cities.py): the same layout, each light's quad holding its belt u and v instead of a direction.
static func city_mesh_file(path: String) -> ArrayMesh:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null and file.get_32() == 0x59544943, "Invalid city mesh: " + path)
	var count := file.get_32()
	var indices := file.get_32()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_CUSTOM0] = file.get_buffer(count * 4)
	arrays[Mesh.ARRAY_INDEX] = file.get_buffer(indices * 4).to_int32_array()
	assert(file.get_position() == file.get_length(), "Truncated city mesh: " + path)
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], {}, Mesh.ARRAY_CUSTOM_RGBA8_UNORM << Mesh.ARRAY_FORMAT_CUSTOM0_SHIFT)
	return mesh

# Before anything loads space.gdshader: outside the editor a global that does not exist yet only logs a warning. project.godot's
# [shader_globals] declares both for the app; a stage or fixture that writes its own project.godot gets them here.
# has_setting and not global_shader_parameter_get_list, which logs an error outside the editor.
static var sky_globals_declared := false
static func declare_sky_globals() -> void:
	if sky_globals_declared:
		return
	sky_globals_declared = true
	if not ProjectSettings.has_setting("shader_globals/earth_gain"):
		RenderingServer.global_shader_parameter_add("earth_gain", RenderingServer.GLOBAL_VAR_TYPE_FLOAT, 1.0)
	if not ProjectSettings.has_setting("shader_globals/earth_spin"):
		RenderingServer.global_shader_parameter_add("earth_spin", RenderingServer.GLOBAL_VAR_TYPE_VEC2, Vector2.ZERO)

static func texture_file(path: String) -> ImageTexture:
	var image: Image = load(path)
	assert(image != null and image.is_compressed(), "Missing compressed ship texture: " + path)
	return ImageTexture.create_from_image(image)

func setup(prefix: String, environment: Environment) -> void:
	source_root = prefix
	metadata = JSON.parse_string(FileAccess.get_file_as_string(prefix + "starship.json"))
	var runtime_block: Variant = metadata.get("runtime", {})
	if runtime_block is Dictionary:
		for key in RUNTIME_DEFAULTS:
			if runtime_block.has(key):
				runtime[key] = float(runtime_block[key])
		for key in RUNTIME_VECTORS:
			if runtime_block.has(key) and runtime_block[key] is Array and runtime_block[key].size() == RUNTIME_VECTORS[key].size():
				runtime[key] = runtime_block[key]
	var hull_shader: Shader = load(prefix + "hull.gdshader")
	for part in metadata.parts:
		var part_name := str(part.name)
		var radiance := texture_file(prefix + part_name + "-lighting.res")
		var reflectance := texture_file(prefix + part_name + "-albedo.res")
		var material: ShaderMaterial
		if part_name == "deck":
			material = _deck_material(load(prefix + "deck.gdshader"), radiance, reflectance)
			deck_material = material
			deck_field_material = _deck_material(load(prefix + "deck_field.gdshader"), radiance, reflectance)
			deck_field_material.set_shader_parameter("screen_gain", float(runtime.screen_gain))
			deck_field_material.set_shader_parameter("field_gain", 0.0)
			materials.append(deck_field_material)
			movie_materials.append(deck_field_material)
		else:
			material = ShaderMaterial.new()
			material.shader = hull_shader
			material.set_shader_parameter("radiance", radiance)
			material.set_shader_parameter("reflectance", reflectance)
			material.set_shader_parameter("spill_gain", float(PART_SPILL.get(part_name, 0.5)))
			material.set_shader_parameter("rim_gain", float(PART_RIM.get(part_name, 0.0)))
		var node := MeshInstance3D.new()
		node.name = part_name.capitalize()
		node.mesh = mesh_file(prefix + part_name + ".bin")
		node.material_override = material
		node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(node)
		if part_name == "deck":
			deck_node = node
		if part_name == "emission":
			emission_materials.append(material)
		else:
			materials.append(material)
			if part_name != "deck":
				movie_materials.append(material)
	declare_sky_globals()
	if not visibility_changed.is_connected(_on_visibility_changed):
		visibility_changed.connect(_on_visibility_changed)
	sky_material = ShaderMaterial.new()
	sky_material.shader = load(prefix + "space.gdshader")
	sky_material.set_shader_parameter("surface", texture_file(prefix + "earth-surface.res"))
	sky_material.set_shader_parameter("masks", texture_file(prefix + "earth-masks.res"))
	sky_material.set_shader_parameter("clouds", texture_file(prefix + "earth-clouds.res"))
	sky_material.set_shader_parameter("detail", texture_file(prefix + "cloud-detail.res"))
	if FileAccess.file_exists(prefix + "galaxy.res"):
		sky_material.set_shader_parameter("galaxy", texture_file(prefix + "galaxy.res"))
		sky_material.set_shader_parameter("dust", texture_file(prefix + "dust.res"))
	sky_resource = Sky.new()
	sky_resource.process_mode = Sky.PROCESS_MODE_QUALITY
	sky_resource.radiance_size = Sky.RADIANCE_SIZE_32
	sky_resource.sky_material = sky_material
	_build_stars()
	_build_cities()
	_build_objects()
	_build_practical_glow()
	_build_field_prewarm()
	_build_surround()
	apply_environment(environment)
	last_light = -1.0
	set_light(0.55)
	refresh_transform()
	triangles = int(metrics().triangles)

func _deck_material(shader: Shader, radiance: Texture2D, reflectance: Texture2D) -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("radiance", radiance)
	material.set_shader_parameter("reflectance", reflectance)
	material.set_shader_parameter("spill_gain", float(PART_SPILL.deck))
	if FileAccess.file_exists(source_root + "deck-mirror.res"):
		material.set_shader_parameter("mirror", _shared_texture("deck-mirror.res"))
	if FileAccess.file_exists(source_root + "deck-wear.res"):
		material.set_shader_parameter("wear", _shared_texture("deck-wear.res"))
	var mirror: Variant = metadata.get("mirror", {})
	material.set_shader_parameter("mirror_u_sign", float(mirror.get("u_sign", 1.0)) if mirror is Dictionary else 1.0)
	material.set_shader_parameter("mirror_strength", float(runtime.mirror_strength))
	material.set_shader_parameter("mirror_f0", float(runtime.mirror_f0))
	material.set_shader_parameter("mirror_f90", float(runtime.mirror_f90))
	material.set_shader_parameter("mirror_fresnel_pow", float(runtime.mirror_fresnel_pow))
	material.set_shader_parameter("sheen_albedo_ref", float(runtime.sheen_albedo_ref))
	var sheen: Array = runtime.sheen
	material.set_shader_parameter("sheen", Vector3(float(sheen[0]), float(sheen[1]), float(sheen[2])))
	var wear: Array = runtime.wear_range
	material.set_shader_parameter("wear_range", Vector2(float(wear[0]), float(wear[1])))
	var screen_sheen: Array = runtime.screen_sheen
	material.set_shader_parameter("screen_sheen", Vector3(float(screen_sheen[0]), float(screen_sheen[1]), float(screen_sheen[2])))
	material.set_shader_parameter("bed_gloss", float(runtime.bed_gloss))
	return material

var _textures := {}
func _shared_texture(file_name: String) -> ImageTexture:
	if not _textures.has(file_name):
		_textures[file_name] = texture_file(source_root + file_name)
	return _textures[file_name]

func apply_environment(environment: Environment) -> void:
	environment.sky = sky_resource
	environment.background_mode = Environment.BG_SKY
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.tonemap_mode = Environment.TONE_MAPPER_AGX
	environment.tonemap_agx_contrast = 1.2
	environment.tonemap_exposure = 1.0
	environment.fog_enabled = false

# A global shader uniform writes one shared buffer. A material uniform or TIME in the shader would re-render the
# sky's radiance map every frame. The values stay wrapped in 0-1, so float precision stays near .002 of a belt texel.
func _process(_delta: float) -> void:
	# Rooms stay cached: a hidden Deck writes nothing, and the clock puts the Earth right when it shows again.
	if is_visible_in_tree():
		_write_spin()

func _write_spin() -> void:
	var ground := EARTH_DEG_PER_HOUR * Time.get_ticks_usec() / 3.6e9
	RenderingServer.global_shader_parameter_set("earth_spin", Vector2(fposmod(-ground / 360.0, 1.0), fposmod(-ground * CLOUD_SPEED / 360.0, 1.0)))

# A room coming back can draw before its next _process, and it takes the room light as it is: the ramp is for a change
# the viewer sees happen.
func _on_visibility_changed() -> void:
	if is_visible_in_tree() and is_processing():
		_write_spin()
		earth_settled = false

func refresh_transform() -> void:
	if sky_material != null and global_basis != saved_basis:
		saved_basis = global_basis
		sky_material.set_shader_parameter("world_to_room", global_basis.orthonormalized().inverse())

func set_light(level: float) -> void:
	room_light = clampf(level, 0.03, 1.0)
	if is_equal_approx(room_light, last_light):
		earth_settled = true
		return
	last_light = room_light
	var strength := room_light / 0.55
	# Emitters fall faster than the room (.075 at Focus) and hold above the default level, so the
	# lens core packed at 1.36 (pack_textures.gd) stays under the 1.6 linear limit at any room light.
	var emitter := pow(minf(strength, 1.0), 1.7)
	for material in materials:
		material.set_shader_parameter("baked_strength", strength)
	for material in emission_materials:
		material.set_shader_parameter("baked_strength", emitter)
	if glow_material != null:
		glow_material.set_shader_parameter("brightness", emitter)
	if amber_material != null:
		amber_material.emission = SLIT_COLOR * emitter
	if surround_material != null:
		surround_material.set_shader_parameter("strength", strength)
		surround_material.set_shader_parameter("strength_e", emitter)
	if sky_material != null:
		_ramp_earth(lerpf(EARTH_FOCUS, 1.0, clampf((room_light - FOCUS_LIGHT) / (DEFAULT_LIGHT - FOCUS_LIGHT), 0.0, 1.0)))

func _ramp_earth(target: float) -> void:
	if earth_ramp != null:
		earth_ramp.kill()
		earth_ramp = null
	var seconds := absf(target - earth_level) / (1.0 - EARTH_FOCUS) * EARTH_RAMP_SECONDS
	var first := not earth_settled
	earth_settled = true
	if first or seconds <= 0.0 or not is_inside_tree():
		_set_earth_level(target)
		return
	earth_ramp = create_tween()
	earth_ramp.tween_method(_set_earth_level, earth_level, target, seconds)

func _set_earth_level(level: float) -> void:
	earth_level = level
	RenderingServer.global_shader_parameter_set("earth_gain", level)

# Previews and tests read one settled frame, not a moment of the ramp.
func settle_earth() -> void:
	if earth_ramp != null:
		earth_ramp.custom_step(EARTH_RAMP_SECONDS + 1.0)
		earth_ramp = null

func _build_stars() -> void:
	if not FileAccess.file_exists(source_root + "stars.dat"):
		return
	star_material = ShaderMaterial.new()
	star_material.shader = load(source_root + "stars.gdshader")
	# The first chunk is the skirted stars, drawn whenever the sky is; the rest are children, each culled by its own direction box.
	var parent: Node3D = self
	for chunk in star_mesh_chunks(source_root + "stars.dat"):
		var node := MeshInstance3D.new()
		node.mesh = chunk[0]
		node.material_override = star_material
		node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		node.custom_aabb = chunk[1]
		# First of the transparent pass: anything else that blends without writing depth (a panel) stays over the sky.
		node.sorting_offset = -4.0 * STAR_BOX
		if star_node == null:
			star_node = node
			star_node.name = "Stars"
			star_node.custom_aabb = AABB(Vector3.ONE * -STAR_BOX, Vector3.ONE * 2.0 * STAR_BOX)
		parent.add_child(node)
		parent = star_node

# After the stars in the transparent pass, so an object's dust can hide the stars behind it.
func _build_objects() -> void:
	if not FileAccess.file_exists(source_root + "objects.dat"):
		return
	object_material = ShaderMaterial.new()
	object_material.shader = load(source_root + "objects.gdshader")
	object_material.set_shader_parameter("atlas", texture_file(source_root + "objects-atlas.res"))
	object_node = MeshInstance3D.new()
	object_node.name = "Objects"
	object_node.mesh = object_mesh_file(source_root + "objects.dat")
	object_node.material_override = object_material
	object_node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	object_node.custom_aabb = AABB(Vector3.ONE * -STAR_BOX, Vector3.ONE * 2.0 * STAR_BOX)
	object_node.sorting_offset = -1.5 * STAR_BOX
	add_child(object_node)

# The city lights share the sky's cloud map, so they cost no texture memory.
func _build_cities() -> void:
	if not FileAccess.file_exists(source_root + "cities.dat"):
		return
	city_material = ShaderMaterial.new()
	city_material.shader = load(source_root + "cities.gdshader")
	city_material.set_shader_parameter("clouds", sky_material.get_shader_parameter("clouds"))
	city_node = MeshInstance3D.new()
	city_node.name = "Cities"
	city_node.mesh = city_mesh_file(source_root + "cities.dat")
	city_node.material_override = city_material
	city_node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	city_node.custom_aabb = AABB(Vector3.ONE * -STAR_BOX, Vector3.ONE * 2.0 * STAR_BOX)
	city_node.sorting_offset = -2.0 * STAR_BOX
	add_child(city_node)

# Called by cinema_ambient.gd every frame it runs (cached here): gain > 0 swaps the
# deck to its movie-field variant, gain 0 swaps back.
func set_screen_field(texture: Texture2D, size: Vector2, gain: float) -> void:
	if deck_field_material == null:
		return
	if texture != field_texture:
		field_texture = texture
		deck_field_material.set_shader_parameter("field", texture)
		surround_material.set_shader_parameter("field", texture)
	if size != field_size and size.x > 0.0 and size.y > 0.0:
		field_size = size
		deck_field_material.set_shader_parameter("field_size", size)
		surround_material.set_shader_parameter("field_size", size)
	if gain != field_gain:
		field_gain = gain
		_apply_deck_material()

# Called with set_screen_field: replaces Cinema's two OmniLights in this room. The source follows
# the screen in _update_screen_uniforms, in room space, so recentering cannot move it.
func set_screen_spill(colors: PackedColorArray, picture: Vector2, gain: float) -> void:
	if picture != spill_picture and picture.x > 0.0:
		# The picture as Fit shows it, which can be shorter than the housing's aperture.
		spill_picture = picture
		surround_material.set_shader_parameter("picture_half", picture * 0.5)
		if deck_field_material != null:
			deck_field_material.set_shader_parameter("picture_half", picture * 0.5)
	if gain == spill_gain and colors == spill_colors:
		return
	spill_gain = gain
	spill_colors = colors.duplicate()
	_apply_spill()

func _apply_spill() -> void:
	if spill_colors.size() != 6:
		return
	# A soft limit on bright frames at high settings, so a white frame in Vivid or Reactive at full
	# brightness lifts the cabin without clipping it; a dim film at the same settings is untouched.
	var peak := 0.0
	for index in 3:
		peak = maxf(peak, spill_colors[index].v)
	var limited := spill_gain * peak
	var gain := spill_gain / (1.0 + MOVIE_LIMIT * limited * limited)
	var on := gain > 0.0 and not profile_movie_off
	for material in movie_materials:
		material.set_shader_parameter("movie_on", on)
		if not on:
			continue
		material.set_shader_parameter("movie_left", _color3(spill_colors[0]) * gain * MOVIE_ENERGY)
		material.set_shader_parameter("movie_right", _color3(spill_colors[1]) * gain * MOVIE_ENERGY)
		material.set_shader_parameter("movie_top", _color3(spill_colors[2]) * gain * MOVIE_ENERGY)
	surround_material.set_shader_parameter("field_gain", gain)
	if deck_field_material != null:
		deck_field_material.set_shader_parameter("field_gain", gain)
		deck_field_material.set_shader_parameter("edge_top", _color3(spill_colors[2]))
		deck_field_material.set_shader_parameter("edge_right", _color3(spill_colors[3]))
		deck_field_material.set_shader_parameter("edge_bottom", _color3(spill_colors[4]))
		deck_field_material.set_shader_parameter("edge_left", _color3(spill_colors[5]))
		deck_field_material.set_shader_parameter("edge_mean", 0.25 * (_color3(spill_colors[2]) + _color3(spill_colors[3]) + _color3(spill_colors[4]) + _color3(spill_colors[5])))

func _color3(color: Color) -> Vector3:
	return Vector3(color.r, color.g, color.b)

func _apply_deck_material() -> void:
	if deck_node == null:
		return
	var wanted: Material = deck_material
	if profile_deck_hull and deck_hull_material != null:
		wanted = deck_hull_material
	elif field_gain > 0.0 and not profile_field_off:
		wanted = deck_field_material
	if deck_node.material_override != wanted:
		deck_node.material_override = wanted

# ---------------------------------------------------------------- lamp halos
func _ensure_materials() -> void:
	if surround_material == null:
		surround_material = ShaderMaterial.new()
		surround_material.shader = SURROUND_SHADER
	if glow_material == null:
		glow_material = ShaderMaterial.new()
		glow_material.shader = GLOW_SHADER
	if amber_material == null:
		amber_material = StandardMaterial3D.new()
		amber_material.albedo_color = Color(0.18, 0.07, 0.015)
		amber_material.specular_mode = BaseMaterial3D.SPECULAR_DISABLED
		amber_material.emission_enabled = true
		amber_material.emission_energy_multiplier = 1.38
		amber_material.emission = SLIT_COLOR
	if shadow_material == null:
		shadow_material = StandardMaterial3D.new()
		shadow_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		shadow_material.blend_mode = BaseMaterial3D.BLEND_MODE_MUL
		shadow_material.vertex_color_use_as_albedo = true
		shadow_material.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED
		shadow_material.disable_fog = true

func _glow_color(tint: Color, gain: float, sigma: float) -> Color:
	var c := tint * gain * GLOW_COLOR_SCALE
	return Color(c.r, c.g, c.b, sigma * 10.0)

# One quad of four vertices, front face toward `normal` (Godot: clockwise in view).
func _glow_quad(st: SurfaceTool, base: int, center: Vector3, along: Vector3, across: Vector3,
		lo: Vector2, hi: Vector2, core: Vector2, color: Color, normal: Vector3) -> int:
	var corners := [Vector2(lo.x, lo.y), Vector2(hi.x, lo.y), Vector2(hi.x, hi.y), Vector2(lo.x, hi.y)]
	for corner in corners:
		st.set_normal(normal)
		st.set_color(color)
		st.set_uv(corner)
		st.set_uv2(core)
		st.add_vertex(center + along * corner.x + across * corner.y)
	var front := (along.cross(across)).dot(normal) > 0.0
	var order := [0, 2, 1, 0, 3, 2] if front else [0, 1, 2, 0, 2, 3]
	for index in order:
		st.add_index(base + index)
	return base + 4

func _build_practical_glow() -> void:
	var glows: Variant = metadata.get("glows", [])
	if not glows is Array or glows.is_empty():
		return
	_ensure_materials()
	var deck_top := float(metadata.get("deck_top", 0.48))
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var base := 0
	for glow in glows:
		var c := Vector3(glow.c[0], glow.c[1], glow.c[2])
		var n := Vector3(glow.n[0], glow.n[1], glow.n[2]).normalized()
		var u := Vector3(glow.u[0], glow.u[1], glow.u[2]).normalized()
		var half := Vector2(float(glow.size[0]), float(glow.size[1])) * 0.5
		if str(glow.kind) == "blue":
			# A pool on the deck: from the curb face blue_pool (.12 m default) into the aisle,
			# L + .10 long, 6 mm above the plate tops (clear of the .484 bars).
			var foot := Vector3(c.x, deck_top + 0.006, c.z)
			var into := Vector3(n.x, 0.0, n.z).normalized()
			var color := _glow_color(BLUE_TINT, float(runtime.glow_blue), BLUE_SIGMA)
			base = _glow_quad(st, base, foot, u, into, Vector2(-half.x - 0.05, 0.0), Vector2(half.x + 0.05, float(runtime.blue_pool)),
				Vector2(half.x, 0.0), color, Vector3.UP)
		else:
			# In the lens plane, 4 mm off the mounting plane: under the lens front (+5 mm),
			# over the slot top (+3 mm), so only the halo outside the lens shows.
			var across := n.cross(u).normalized()
			var color := _glow_color(AMBER_TINT, float(runtime.glow_amber), AMBER_SIGMA)
			base = _glow_quad(st, base, c + n * 0.004, u, across, -half - Vector2.ONE * GLOW_MARGIN,
				half + Vector2.ONE * GLOW_MARGIN, half, color, n)
	practical_glow = MeshInstance3D.new()
	practical_glow.name = "PracticalGlow"
	practical_glow.mesh = st.commit()
	practical_glow.material_override = glow_material
	practical_glow.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(practical_glow)

# Compiles the field variant's pipeline at load: a 1 cm quad hidden under the slab top.
func _build_field_prewarm() -> void:
	if deck_field_material == null:
		return
	var prewarm := MeshInstance3D.new()
	prewarm.name = "DeckFieldPrewarm"
	var plane := PlaneMesh.new()
	plane.size = Vector2(0.01, 0.01)
	prewarm.mesh = plane
	prewarm.position = Vector3(0, 0.30, 0)
	prewarm.material_override = deck_field_material
	prewarm.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(prewarm)

# ---------------------------------------------------------------- screen housing
func _build_surround() -> void:
	_ensure_materials()
	screen_surround = Node3D.new()
	screen_surround.name = "ScreenSurround"
	add_child(screen_surround)
	# Every piece is outside the picture aperture. The browser/video remains
	# the single surface owned by Cinema, with its normal input and Fit rules.
	for piece_name in ["Top", "Left", "Right", "Base", "GlowLeft", "GlowRight"]:
		var piece := MeshInstance3D.new()
		piece.name = piece_name
		piece.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		screen_surround.add_child(piece)
	housing_width = -1.0
	follow_screen(screen_center, screen_width)

func follow_screen(center: Vector3, width: float) -> void:
	screen_center = center
	screen_width = width
	if screen_surround == null:
		return
	screen_surround.position = center
	if not is_equal_approx(width, housing_width):
		housing_width = width
		_rebuild_housing(width)
	_update_screen_uniforms()

func _housing_aperture(width: float) -> Vector2:
	return Vector2(width * 0.5 + 0.012, width * 0.5625 * 0.5 + 0.012)

func _update_screen_uniforms() -> void:
	var half := Vector2(screen_width * 0.5, screen_width * 0.5625 * 0.5)
	var a := _housing_aperture(screen_width)
	for material in materials:
		material.set_shader_parameter("screen_z", screen_center.z)
	for material in movie_materials:
		material.set_shader_parameter("movie_source", Vector3(screen_center.x, screen_center.y - MOVIE_SOURCE_DROP, screen_center.z + MOVIE_SOURCE_AHEAD))
		material.set_shader_parameter("movie_side", 1.0 / (screen_width * 1.2))
	for material in [deck_material, deck_field_material]:
		if material == null:
			continue
		material.set_shader_parameter("screen_center", Vector2(screen_center.x, screen_center.y))
		material.set_shader_parameter("screen_half", half)
		material.set_shader_parameter("housing_min", Vector2(screen_center.x - a.x - 0.35, 0.45))
		material.set_shader_parameter("housing_max", Vector2(screen_center.x + a.x + 0.35, screen_center.y + a.y + 0.16 + 0.08))

# Warm spill around the slits, precomputed per vertex.
func _spill(point: Vector3) -> float:
	var best := 1e9
	for slit in housing_slits:
		var dx := maxf(maxf(slit.position.x - point.x, point.x - slit.end.x), 0.0)
		var dy := maxf(maxf(slit.position.y - point.y, point.y - slit.end.y), 0.0)
		best = minf(best, dx * dx + dy * dy)
	return exp(-best / SPILL_K)

# A flat convex polygon facing `hint` (its normal is taken from the points). COLOR.r marks
# chamfers (grazing rim weight), COLOR.g the precomputed slit spill and COLOR.b the
# picture-side lip that catches the picture's light.
func _face(st: SurfaceTool, points: Array, hint: Vector3, rim: float, lip := 0.0) -> void:
	var p0: Vector3 = points[0]
	var normal: Vector3 = (points[1] - p0).cross(points[2] - p0).normalized()
	if normal.dot(hint) < 0.0:
		normal = -normal
	for i in range(1, points.size() - 1):
		var tri := [points[0], points[i], points[i + 1]]
		if (tri[1] - tri[0]).cross(tri[2] - tri[0]).dot(normal) > 0.0:
			tri = [tri[0], tri[2], tri[1]]
		for p in tri:
			st.set_normal(normal)
			st.set_color(Color(rim, _spill(p), lip, 1.0))
			st.add_vertex(p)

func _begin() -> SurfaceTool:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	return st

func _rect_loop(a: Vector2, offset: Array, z: float) -> Array:
	# Corners TL, TR, BR, BL of the aperture grown by per-side offsets [top, right, bottom, left].
	return [Vector3(-a.x - offset[3], a.y + offset[0], z), Vector3(a.x + offset[1], a.y + offset[0], z),
		Vector3(a.x + offset[1], -a.y - offset[2], z), Vector3(-a.x - offset[3], -a.y - offset[2], z)]

func _rebuild_housing(width: float) -> void:
	var hh := width * 0.5625 * 0.5
	var cy := screen_center.y
	var a := _housing_aperture(width)
	var bottom := clampf(cy - hh - 0.012 - 0.482, 0.02, 0.16)
	var deck := 0.4505 - cy
	var slit_x := a.x + 0.275
	var slit_y := 0.36 * hh * 2.0
	housing_slits.clear()
	for side: float in [-1.0, 1.0]:
		for level: float in [-1.0, 1.0]:
			housing_slits.append(Rect2(Vector2(side * slit_x - 0.009, level * slit_y - 0.05), Vector2(0.018, 0.10)))
	var pieces := {"Top": _begin(), "Right": _begin(), "Base": _begin(), "Left": _begin()}
	var amber := {"Left": _begin(), "Right": _begin()}
	# Frame ring: bars span z -.27..+.03 with mitred corners, an inner 45 deg chamfer from
	# (a, z -.005) to (a + .045, z +.03) and a 15 mm outer chamfer. The chamfer's first
	# quarter (about 1 cm, 2-3 px at the seat) is the lit lip beside the picture.
	var widths := [0.16, 0.20, bottom, 0.20]
	var inner := []
	var lip := []
	var outer := []
	var zero := [0.0, 0.0, 0.0, 0.0]
	for w in widths:
		inner.append(minf(0.045, 0.4 * w))
		lip.append(minf(0.045, 0.4 * w) * 0.25)
		outer.append(w - minf(0.015, 0.3 * w))
	var loops := [_rect_loop(a, zero, -0.27), _rect_loop(a, zero, -0.005), _rect_loop(a, lip, -0.005 + 0.035 * 0.25),
		_rect_loop(a, inner, 0.03), _rect_loop(a, outer, 0.03), _rect_loop(a, widths, 0.015), _rect_loop(a, widths, -0.27)]
	var inward := [Vector3(0, -1, 0), Vector3(-1, 0, 0), Vector3(0, 1, 0), Vector3(1, 0, 0)]
	var band_hint := [0.0, 1.0, 1.0, 1.0, 1.0, 0.0]
	var band_in := [1.0, 1.0, 1.0, 0.0, -1.0, -1.0]
	var band_rim := [0.0, 1.0, 0.1, 0.0, 0.5, 0.0]
	var band_lip := [0.0, 1.0, 0.1, 0.0, 0.0, 0.0]
	var side_piece := ["Top", "Right", "Base", "Left"]
	for band in 6:
		var p: Array = loops[band]
		var q: Array = loops[band + 1]
		for side in 4:
			var i := side
			var j := (side + 1) % 4
			var hint: Vector3 = inward[side] * band_in[band] + Vector3(0, 0, band_hint[band])
			_face(pieces[side_piece[side]], [p[i], p[j], q[j], q[i]], hint, band_rim[band], band_lip[band])
	# Posts beside the side bars (15 mm groove), deck to frame top + .04, a 35 mm top-outer
	# chamfer (a .10 chamfer on the .12 post left a 2 cm flat and read as a spire), each with
	# two recessed amber slits at +/-0.36 h.
	var top := a.y + 0.20
	var chamfer_y := top - 0.035
	for side: float in [-1.0, 1.0]:
		var key := "Left" if side < 0.0 else "Right"
		var st: SurfaceTool = pieces[key]
		var xi := side * (a.x + 0.215)
		var xo := side * (a.x + 0.335)
		var xc := xo - side * 0.035
		var z0 := -0.31
		var z1 := 0.03
		_face(st, [Vector3(xi, deck, z0), Vector3(xi, deck, z1), Vector3(xi, top, z1), Vector3(xi, top, z0)], Vector3(-side, 0, 0), 0.0)
		_face(st, [Vector3(xo, deck, z0), Vector3(xo, chamfer_y, z0), Vector3(xo, chamfer_y, z1), Vector3(xo, deck, z1)], Vector3(side, 0, 0), 0.0)
		_face(st, [Vector3(xo, chamfer_y, z0), Vector3(xc, top, z0), Vector3(xc, top, z1), Vector3(xo, chamfer_y, z1)], Vector3(side, 1, 0), 1.0)
		_face(st, [Vector3(xi, top, z0), Vector3(xi, top, z1), Vector3(xc, top, z1), Vector3(xc, top, z0)], Vector3.UP, 0.0)
		_face(st, [Vector3(xi, chamfer_y, z1), Vector3(xo, chamfer_y, z1), Vector3(xc, top, z1), Vector3(xi, top, z1)], Vector3.BACK, 0.0)
		# Front face on a grid that resolves the spill and leaves the slit openings.
		var columns := [a.x + 0.215, slit_x - 0.03, slit_x - 0.009, slit_x + 0.009, slit_x + 0.03, a.x + 0.335]
		var rows := [deck, chamfer_y]
		for level: float in [-1.0, 1.0]:
			for offset: float in [-0.24, -0.16, -0.09, -0.05, 0.05, 0.09, 0.16, 0.24]:
				var y: float = level * slit_y + offset
				if y > deck + 0.01 and y < chamfer_y - 0.01:
					rows.append(y)
		rows.sort()
		for r in rows.size() - 1:
			var y0: float = rows[r]
			var y1: float = rows[r + 1]
			for c in columns.size() - 1:
				var x0: float = side * columns[c]
				var x1: float = side * columns[c + 1]
				var hole := false
				if c == 2:
					for level: float in [-1.0, 1.0]:
						if absf(y0 - (level * slit_y - 0.05)) < 1e-4 and absf(y1 - (level * slit_y + 0.05)) < 1e-4:
							hole = true
				if not hole:
					_face(st, [Vector3(x0, y0, z1), Vector3(x1, y0, z1), Vector3(x1, y1, z1), Vector3(x0, y1, z1)], Vector3.BACK, 0.0)
		for level: float in [-1.0, 1.0]:
			var sx0 := side * slit_x - 0.009
			var sx1 := side * slit_x + 0.009
			var sy0: float = level * slit_y - 0.05
			var sy1: float = level * slit_y + 0.05
			var face := 0.026
			_face(amber[key], [Vector3(sx0, sy0, face), Vector3(sx1, sy0, face), Vector3(sx1, sy1, face), Vector3(sx0, sy1, face)], Vector3.BACK, 0.0)
			_face(st, [Vector3(sx0, sy0, face), Vector3(sx0, sy1, face), Vector3(sx0, sy1, z1), Vector3(sx0, sy0, z1)], Vector3.RIGHT, 0.0)
			_face(st, [Vector3(sx1, sy0, face), Vector3(sx1, sy1, face), Vector3(sx1, sy1, z1), Vector3(sx1, sy0, z1)], Vector3.LEFT, 0.0)
			_face(st, [Vector3(sx0, sy1, face), Vector3(sx1, sy1, face), Vector3(sx1, sy1, z1), Vector3(sx0, sy1, z1)], Vector3.DOWN, 0.0)
			_face(st, [Vector3(sx0, sy0, face), Vector3(sx1, sy0, face), Vector3(sx1, sy0, z1), Vector3(sx0, sy0, z1)], Vector3.UP, 0.0)
		# Groove floor between the side bar and the post.
		var gx0 := side * (a.x + 0.20)
		var gx1 := side * (a.x + 0.215)
		_face(st, [Vector3(gx0, -a.y - bottom, -0.04), Vector3(gx1, -a.y - bottom, -0.04), Vector3(gx1, a.y + 0.16, -0.04), Vector3(gx0, a.y + 0.16, -0.04)], Vector3.BACK, 0.0)
	# Base: plinth under the bottom bar (front face recessed to z -.03, a 25 mm groove at
	# mid-height). At 5.4 m the plinth collapses and only the feet remain.
	var base: SurfaceTool = pieces.Base
	var bar_bottom := -a.y - bottom
	var plinth := bar_bottom - deck >= 0.06
	var plinth_x := a.x + 0.15
	if plinth:
		var mid := (deck + bar_bottom) * 0.5
		var g0 := mid - 0.0125
		var g1 := mid + 0.0125
		for span in [[deck, g0], [g1, bar_bottom]]:
			_face(base, [Vector3(-plinth_x, span[0], -0.03), Vector3(plinth_x, span[0], -0.03), Vector3(plinth_x, span[1], -0.03), Vector3(-plinth_x, span[1], -0.03)], Vector3.BACK, 0.0)
		_face(base, [Vector3(-plinth_x, g0, -0.045), Vector3(plinth_x, g0, -0.045), Vector3(plinth_x, g1, -0.045), Vector3(-plinth_x, g1, -0.045)], Vector3.BACK, 0.0)
		_face(base, [Vector3(-plinth_x, g0, -0.045), Vector3(plinth_x, g0, -0.045), Vector3(plinth_x, g0, -0.03), Vector3(-plinth_x, g0, -0.03)], Vector3.UP, 0.0)
		_face(base, [Vector3(-plinth_x, g1, -0.045), Vector3(plinth_x, g1, -0.045), Vector3(plinth_x, g1, -0.03), Vector3(-plinth_x, g1, -0.03)], Vector3.DOWN, 0.0)
		for side: float in [-1.0, 1.0]:
			var x := side * plinth_x
			_face(base, [Vector3(x, deck, -0.27), Vector3(x, deck, -0.03), Vector3(x, bar_bottom, -0.03), Vector3(x, bar_bottom, -0.27)], Vector3(side, 0, 0), 0.0)
	for side: float in [-1.0, 1.0]:
		# Splayed wedge feet at the post bottoms. They belong to the Left/Right meshes, so
		# no piece's bounding box reaches into the lower corners of the 5.4 m aperture.
		# Front face 1 cm behind the post front, so the two never share a plane.
		base = pieces["Left" if side < 0.0 else "Right"]
		var x_in := side * (a.x + 0.175)
		var x_top := side * (a.x + 0.375)
		var x_deck := side * (a.x + 0.555)
		var y1 := deck + 0.22
		var z0 := -0.37
		var z1 := 0.02
		_face(base, [Vector3(x_in, deck, z1), Vector3(x_deck, deck, z1), Vector3(x_top, y1, z1), Vector3(x_in, y1, z1)], Vector3.BACK, 0.0)
		_face(base, [Vector3(x_deck, deck, z0), Vector3(x_deck, deck, z1), Vector3(x_top, y1, z1), Vector3(x_top, y1, z0)], Vector3(side * 0.22, 0.18, 0), 0.0)
		_face(base, [Vector3(x_in, y1, z0), Vector3(x_in, y1, z1), Vector3(x_top, y1, z1), Vector3(x_top, y1, z0)], Vector3.UP, 0.0)
		_face(base, [Vector3(x_in, deck, z0), Vector3(x_in, deck, z1), Vector3(x_in, y1, z1), Vector3(x_in, y1, z0)], Vector3(-side, 0, 0), 0.0)
	for key in pieces:
		var piece: MeshInstance3D = screen_surround.get_node(key)
		var mesh: ArrayMesh = pieces[key].commit()
		mesh.surface_set_material(0, surround_material)
		if amber.has(key):
			amber[key].commit(mesh)
			mesh.surface_set_material(1, amber_material)
		piece.mesh = mesh
	# Halo cards over the slits, 0.5 mm in front of the post face.
	for side: float in [-1.0, 1.0]:
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		var next := 0
		var color := _glow_color(AMBER_TINT, float(runtime.glow_amber) * float(runtime.slit_glow), SLIT_SIGMA)
		var core := Vector2(0.009, 0.05)
		for level: float in [-1.0, 1.0]:
			next = _glow_quad(st, next, Vector3(side * slit_x, level * slit_y, 0.0305), Vector3.RIGHT, Vector3.UP,
				-core - Vector2.ONE * GLOW_MARGIN, core + Vector2.ONE * GLOW_MARGIN, core, color, Vector3.BACK)
		var card: MeshInstance3D = screen_surround.get_node("GlowLeft" if side < 0.0 else "GlowRight")
		card.mesh = st.commit()
		card.material_override = glow_material
	_rebuild_contact_shadow(plinth, plinth_x, deck)

# A soft multiply under the plinth front, on top of every deck surface under it (.488).
func _rebuild_contact_shadow(plinth: bool, half_width: float, deck: float) -> void:
	var existing := screen_surround.get_node_or_null("ContactShadow")
	if existing != null:
		screen_surround.remove_child(existing)
		existing.free()
	if not plinth:
		return
	var y := 0.488 - screen_center.y
	var sigma := 0.15
	var xs := [-half_width, -half_width + 0.1, -half_width + 0.2, -half_width + 0.3, half_width - 0.3, half_width - 0.2, half_width - 0.1, half_width]
	var zs := [-0.03, 0.02, 0.07, 0.12, 0.17, 0.22, 0.30, 0.38, 0.47]
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for zi in zs.size():
		for xi in xs.size():
			var dz: float = zs[zi] + 0.03
			var dx: float = maxf(absf(xs[xi]) - (half_width - 2.0 * sigma), 0.0)
			var g := exp(-(dz * dz + dx * dx) / (2.0 * sigma * sigma))
			# The multiply sees vertex colours sRGB-decoded (a linear .55 darkened like .26),
			# so store the sRGB encoding of the linear shade.
			var shade := 1.0 - 0.45 * g
			st.set_color(Color(shade, shade, shade, 1.0).linear_to_srgb())
			st.set_normal(Vector3.UP)
			st.add_vertex(Vector3(xs[xi], y, zs[zi]))
	var stride := xs.size()
	for zi in zs.size() - 1:
		for xi in stride - 1:
			var i0: int = zi * stride + xi
			# Facing up (clockwise seen from above).
			st.add_index(i0)
			st.add_index(i0 + 1)
			st.add_index(i0 + stride + 1)
			st.add_index(i0)
			st.add_index(i0 + stride + 1)
			st.add_index(i0 + stride)
	var shadow := MeshInstance3D.new()
	shadow.name = "ContactShadow"
	shadow.mesh = st.commit()
	shadow.material_override = shadow_material
	shadow.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	screen_surround.add_child(shadow)

# ---------------------------------------------------------------- profiler hooks
# cinema.gd _profile_room() runs each variant once per room pose.
func profile_variants() -> Array:
	return PROFILE_VARIANTS.duplicate()

func profile_variant(variant: String, enabled: bool) -> void:
	match variant:
		"deck as hull":
			if enabled and deck_hull_material == null and deck_material != null:
				deck_hull_material = ShaderMaterial.new()
				deck_hull_material.shader = load(source_root + "hull.gdshader")
				for key in ["radiance", "reflectance", "spill_gain", "baked_strength"]:
					deck_hull_material.set_shader_parameter(key, deck_material.get_shader_parameter(key))
				deck_hull_material.set_shader_parameter("screen_z", screen_center.z)
				materials.append(deck_hull_material)
				movie_materials.append(deck_hull_material)
				_update_screen_uniforms()
				_apply_spill()
			profile_deck_hull = enabled
			_apply_deck_material()
		"field off":
			profile_field_off = enabled
			_apply_deck_material()
		"movie light off":
			profile_movie_off = enabled
			_apply_spill()
		"PracticalGlow hidden":
			if practical_glow != null:
				practical_glow.visible = not enabled
		"stars hidden":
			if star_node != null:
				star_node.visible = not enabled
		"cities hidden":
			if city_node != null:
				city_node.visible = not enabled
		"objects hidden":
			if object_node != null:
				object_node.visible = not enabled

func metrics() -> Dictionary:
	var meshes := 0
	var count := 0
	for node in find_children("*", "MeshInstance3D", true, false):
		var mesh: Mesh = node.mesh
		if mesh == null:
			continue
		meshes += 1
		var array_mesh := mesh as ArrayMesh
		if array_mesh != null:
			for surface in array_mesh.get_surface_count():
				var indices: int = array_mesh.surface_get_array_index_len(surface)
				count += (indices if indices > 0 else array_mesh.surface_get_array_len(surface)) / 3
		else:
			count += mesh.get_faces().size() / 3
	triangles = count
	return {"kind": "modeled_3d", "meshes": meshes,
		"triangles": count, "lights": 0, "material_maps": metadata.get("parts", []).size() * 2 + 2 + (1 if deck_material != null else 0),
		"missing_maps": [], "panorama": false, "room_light": room_light, "glows": metadata.get("glows", []).size(),
		"deck_variant": "field" if deck_node != null and deck_node.material_override == deck_field_material else "base",
		"screen_center": [screen_center.x, screen_center.y, screen_center.z], "screen_width": screen_width,
		"space_background": "analytic planet, real Milky Way map, real star mesh", "lighting": "baked hull plus analytic movie light"}
