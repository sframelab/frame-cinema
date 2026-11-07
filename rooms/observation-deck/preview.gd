extends SceneTree

# Actual Godot meshes/materials, isolated from XR, browser and user preferences.
# Shots (all at MSAA 2x, like the headset default):
# - 12 legacy shots at 1600x1000, fov 78, 4.2 m screen (continuity with v1-v3);
# - reference-framed "_ref" shots at 1672x941, vertical fov 54.5, 3.2 m screen;
# - a mask pass per shot (lens pixels only) as mask_<shot>.png;
# - the left-eye/right-eye stereo pair twice, with and without the deck reflection
#   (stereo_left_*_nospec), so a comparison can isolate the reflection's depth;
# - a headset set: 2160x2160, focal 748 px (the Frame's OpenXR view), render scale 1.0 and 0.62 (bilinear),
#   16 frames each with yaw stepped 0.01 deg, written to STARSHIP_PREVIEW_HEADSET_OUT, and one frame per
#   direction at the default and at full room light through a linear tone map, for the lens-peak check.
# The ambient and focus shots run the real cinema_ambient.gd with a stub host.
# Environment: STARSHIP_PREVIEW_OUT (required), STARSHIP_PREVIEW_HEADSET_OUT,
# STARSHIP_PREVIEW_NO_SPEC=1, STARSHIP_PREVIEW_PARAMS (JSON or a JSON file path:
# {"sky"|"stars"|"deck"|"hull"|"global": {param: value}}), STARSHIP_PREVIEW_SHOTS (comma list),
# STARSHIP_PREVIEW_NO_HEADSET=1, STARSHIP_PREVIEW_AMBIENT_MODE (default 2, Cinema),
# STARSHIP_PREVIEW_FAR (camera far, default the headset's 120000, to compare depth precision),
# STARSHIP_PREVIEW_PICTURE (a still for the screen, in place of a staged screen-picture.png),
# STARSHIP_PREVIEW_LIBRARY=1 (only the Steam library shots, for release/art/compose_art.py).

const SEAT := Vector3(0, 1.65, 0)
const SCREEN := Vector3(0, 2.1, -4.5)
const LEGACY_SIZE := Vector2i(1600, 1000)
const REF_SIZE := Vector2i(1672, 941)
const HEADSET_SIZE := 2160
const HEADSET_FOCAL := 748.0

class RoomStub extends RefCounted:
	var contents: Node3D

class AmbientHost extends Node3D:
	var screen_width := 4.2
	var ambient_mode := 2
	var ambient_brightness := 0.5
	var environment_index := 8
	var picture_top := 0.0
	var ui := {"page": "cinema"}
	var room: RoomStub = RoomStub.new()
	var xr_active := false
	var preview := true
	var library_open := false
	var source_pending := false
	var browser_keyboard := false
	var panel_fresh := true
	var panel_aligned := true
	var placement_session := ""
	var ipc := ""
	var fit_picture := false
	var fit_media := {}
	var profiling := false
	func _screen_center() -> Vector3: return Vector3(0, 2.1, -4.5)
	func _display_screen_width() -> float: return screen_width
	func _alpine_room() -> bool: return false
	func _dark_room() -> bool: return false
	func _effective_ambient_mode() -> int: return ambient_mode
	func _lake_reflection_wanted() -> bool: return false
	func _placement_session_state() -> int: return OpenXRInterface.SESSION_STATE_FOCUSED

var view: SubViewport
var environment: Environment
var room: Node3D
var eye: Camera3D
var screen: MeshInstance3D
var quad: QuadMesh
var host: AmbientHost
var ambient: Node3D
var palette: Array[Color] = []
var overrides := {}
var no_spec := false
var only := {}
var output := ""
var headset_output := ""
var frames := []

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	output = OS.get_environment("STARSHIP_PREVIEW_OUT")
	assert(not output.is_empty())
	DirAccess.make_dir_recursive_absolute(output)
	headset_output = OS.get_environment("STARSHIP_PREVIEW_HEADSET_OUT")
	if headset_output.is_empty():
		headset_output = output.path_join("headset")
	no_spec = OS.get_environment("STARSHIP_PREVIEW_NO_SPEC") == "1"
	overrides = _read_overrides(OS.get_environment("STARSHIP_PREVIEW_PARAMS"))
	for name in OS.get_environment("STARSHIP_PREVIEW_SHOTS").split(",", false):
		only[name.strip_edges()] = true
	view = SubViewport.new()
	view.size = LEGACY_SIZE
	view.own_world_3d = true
	view.msaa_3d = Viewport.MSAA_2X
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	var world := WorldEnvironment.new()
	world.environment = Environment.new()
	environment = world.environment
	view.add_child(world)
	room = load("res://starship/starship_room.gd").new()
	view.add_child(room)
	room.setup("res://starship/", environment)
	# Renders and gates stay on the first view, so they are repeatable: the Earth holds still at spin 0.
	room.set_process(false)
	eye = Camera3D.new()
	eye.near = 0.04
	# The headset's far for this room (cinema.gd). Stars never clip against it: they are drawn with w = 0.
	eye.far = float(OS.get_environment("STARSHIP_PREVIEW_FAR")) if OS.has_environment("STARSHIP_PREVIEW_FAR") else 120000.0
	view.add_child(eye)
	eye.current = true
	screen = MeshInstance3D.new()
	screen.name = "PreviewOnlyVideoPlaceholder"
	quad = QuadMesh.new()
	quad.size = Vector2(4.2, 4.2 * 0.5625)
	screen.mesh = quad
	var picture := StandardMaterial3D.new()
	picture.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	picture.albedo_color = Color(0.008, 0.012, 0.02)
	# A stand-in picture (any screen-picture.png you put in the stage) instead of a film.
	var still_path := OS.get_environment("STARSHIP_PREVIEW_PICTURE")
	if still_path.is_empty() and FileAccess.file_exists("res://screen-picture.png"):
		still_path = ProjectSettings.globalize_path("res://screen-picture.png")
	var still := Image.load_from_file(still_path) if not still_path.is_empty() else null
	if still != null:
		picture.albedo_color = Color.WHITE
		picture.albedo_texture = ImageTexture.create_from_image(still)
		palette = _edge_palette(still)
	else:
		for i in 256:
			palette.append(Color(0.05, 0.07, 0.12))
	screen.material_override = picture
	screen.position = SCREEN
	room.add_child(screen)
	_build_ambient()
	var shots := []
	for s in [["front", 0.0, 0.0, Vector3.ZERO, 0.55, 4.2, false],
			["left", 90.0, 0.0, Vector3.ZERO, 0.55, 4.2, false],
			["right", -90.0, 0.0, Vector3.ZERO, 0.55, 4.2, false],
			["behind", 180.0, 0.0, Vector3.ZERO, 0.55, 4.2, false],
			["up", 0.0, 85.0, Vector3.ZERO, 0.55, 4.2, false],
			["down", 0.0, -75.0, Vector3.ZERO, 0.55, 4.2, false],
			["lean", 0.0, 0.0, Vector3(0.35, 0.10, 0.25), 0.55, 4.2, false],
			["focus", 0.0, 0.0, Vector3.ZERO, 0.12, 4.2, true],
			["small", 0.0, 0.0, Vector3.ZERO, 0.55, 3.2, false],
			["large", 0.0, 0.0, Vector3.ZERO, 0.55, 5.4, false],
			["ambient", 0.0, 0.0, Vector3.ZERO, 0.55, 4.2, true],
			["recenter", 0.0, 0.0, Vector3.ZERO, 0.55, 4.2, false]]:
		shots.append({"name": s[0], "yaw": s[1], "pitch": s[2], "offset": s[3], "light": s[4], "width": s[5],
			"ambient": s[6], "size": LEGACY_SIZE, "fov": 78.0, "set": "legacy"})
	for s in [["front_ref", 0.0, 1.5, Vector3.ZERO, false, 0.0],
			["left_ref", 90.0, 0.0, Vector3.ZERO, false, 0.0],
			["right_ref", -90.0, 0.0, Vector3.ZERO, false, 0.0],
			["behind_ref", 180.0, 0.0, Vector3.ZERO, false, 0.0],
			["up_ref", 0.0, 80.0, Vector3.ZERO, false, 0.0],
			["down_ref", 0.0, -58.0, Vector3.ZERO, false, 0.0],
			["front_ref_ambient", 0.0, 1.5, Vector3.ZERO, true, 0.0],
			["stereo_left_L", 60.0, 0.0, Vector3.ZERO, false, -0.032],
			["stereo_left_R", 60.0, 0.0, Vector3.ZERO, false, 0.032],
			["stereo_left_L_nospec", 60.0, 0.0, Vector3.ZERO, false, -0.032],
			["stereo_left_R_nospec", 60.0, 0.0, Vector3.ZERO, false, 0.032],
			["lean_ref", 0.0, 1.5, Vector3(0.35, 0.10, 0.25), false, 0.0]]:
		shots.append({"name": s[0], "yaw": s[1], "pitch": s[2], "offset": s[3], "light": 0.55, "width": 3.2,
			"ambient": s[4], "eye_shift": s[5], "size": REF_SIZE, "fov": 54.5, "set": "ref", "no_spec": str(s[0]).ends_with("_nospec")})
	if OS.get_environment("STARSHIP_PREVIEW_LIBRARY") == "1":
		# Steam library art (2026-11): the hero from 1.3 m behind the seat, so the Earth's night side fills the left
		# windows and the stars the right; the header and the capsule from nearer, the capsule looking up at the canopy.
		shots = []
		for s in [["library_hero", Vector2i(3840, 1240), 44.0, 0.0, 4.0, Vector3(0.0, 0.1, 1.3)],
				["library_header", Vector2i(1840, 860), 50.0, 8.0, 4.0, Vector3(0.0, 0.0, 0.8)],
				["library_capsule", Vector2i(1200, 1800), 74.0, 0.0, 10.0, Vector3(0.0, 0.0, 0.9)]]:
			shots.append({"name": s[0], "yaw": s[3], "pitch": s[4], "offset": s[5], "light": 0.55, "width": 4.2,
				"ambient": true, "size": s[1], "fov": s[2], "set": "library"})
	for shot in shots:
		if not only.is_empty() and not only.has(shot.name):
			continue
		await _shot(shot)
	if OS.get_environment("STARSHIP_PREVIEW_NO_HEADSET") != "1" and (only.is_empty() or only.has("headset")):
		await _headset_set()
	var report := FileAccess.open(output.path_join("render-report.json"), FileAccess.WRITE)
	report.store_string(JSON.stringify({"engine": Engine.get_version_info(), "renderer": RenderingServer.get_current_rendering_method(),
		"msaa": "2x", "no_spec": no_spec, "overrides": overrides, "ambient_mode": host.ambient_mode, "ambient_brightness": host.ambient_brightness,
		"room": room.metrics(), "frames": frames,
		"scope": "Windows Vulkan Mobile captures of actual 3D; no headset timing or acceptance"}, "  "))
	view.queue_free()
	await process_frame
	print("STARSHIP_PREVIEW_OK")
	quit()

# ---------------------------------------------------------------- shots
func _place(shot: Dictionary) -> void:
	room.transform = Transform3D.IDENTITY
	eye.rotation_degrees = Vector3(shot.pitch, shot.yaw, 0)
	eye.position = SEAT + shot.offset
	if shot.has("eye_shift"):
		eye.position += eye.basis.x * float(shot.eye_shift)
	room.set_light(shot.light)
	room.settle_earth()
	var width: float = shot.width
	room.follow_screen(SCREEN, width)
	quad.size = Vector2(width, width * 0.5625)
	host.screen_width = width
	if shot.name == "recenter":
		var placement := Transform3D(Basis(Vector3.UP, 0.8), Vector3(1.5, 0.12, 2.4))
		room.transform = placement
		eye.transform = placement * eye.transform
	room.refresh_transform()
	_set_ambient(shot.ambient, shot.light)
	_apply_overrides()

func _shot(shot: Dictionary) -> void:
	view.size = shot.size
	eye.fov = shot.fov
	_place(shot)
	# Per-shot reflection off (the _nospec stereo pair); restored after the mask pass.
	var deck_off: ShaderMaterial = _deck_material() if shot.get("no_spec", false) else null
	var deck_strength: Variant = null
	if deck_off != null:
		deck_strength = deck_off.get_shader_parameter("mirror_strength")
		deck_off.set_shader_parameter("mirror_strength", 0.0)
	var picture := await _capture(8)
	assert(picture.save_png(output.path_join(shot.name + ".png")) == OK)
	if shot.name == "front":
		var thumb: Image = picture.duplicate()
		thumb.resize(768, 480, Image.INTERPOLATE_LANCZOS)
		thumb.save_png(output.path_join("starship-thumb.png"))
	var record := {"view": shot.name, "set": shot.set, "size": [shot.size.x, shot.size.y], "fov": shot.fov,
		"yaw": shot.yaw, "pitch": shot.pitch, "light": shot.light, "screen_width": shot.width, "ambient": shot.ambient,
		"eye": [eye.global_position.x, eye.global_position.y, eye.global_position.z],
		"draw_calls": view.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE, Viewport.RENDER_INFO_DRAW_CALLS_IN_FRAME),
		"primitives": view.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE, Viewport.RENDER_INFO_PRIMITIVES_IN_FRAME)}
	# Mask pass: lens pixels only (> 8 luma in the saved PNG).
	var restore := _mask_mode()
	var mask := await _capture(6)
	_restore(restore)
	assert(mask.save_png(output.path_join("mask_" + shot.name + ".png")) == OK)
	if deck_off != null:
		deck_off.set_shader_parameter("mirror_strength", deck_strength)
		record["no_spec"] = true
	frames.append(record)
	print("STARSHIP_SHOT ", shot.name, " draw_calls=", record.draw_calls)

func _headset_set() -> void:
	DirAccess.make_dir_recursive_absolute(headset_output)
	view.size = Vector2i(HEADSET_SIZE, HEADSET_SIZE)
	eye.fov = rad_to_deg(2.0 * atan(HEADSET_SIZE * 0.5 / HEADSET_FOCAL))
	view.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
	for scale in [1.0, 0.62]:
		view.scaling_3d_scale = scale
		for direction in [["front", 0.0, 0.0], ["up70", 0.0, 70.0], ["left90", 90.0, 0.0]]:
			var tag := "%s_s%03d" % [direction[0], int(round(scale * 100))]
			var calls := 0
			for i in 16:
				var shot := {"name": "headset_" + tag, "yaw": direction[1] + 0.01 * i, "pitch": direction[2], "offset": Vector3.ZERO,
					"light": 0.55, "width": 4.2, "ambient": false}
				_place(shot)
				var picture := await _capture(4 if i else 8)
				assert(picture.save_png(headset_output.path_join("%s_%02d.png" % [tag, i])) == OK)
				if i == 0:
					calls = view.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE, Viewport.RENDER_INFO_DRAW_CALLS_IN_FRAME)
					picture.save_png(output.path_join("headset_" + tag + ".png"))
			frames.append({"view": "headset_" + tag, "set": "headset", "size": [HEADSET_SIZE, HEADSET_SIZE], "fov": eye.fov,
				"focal_px": HEADSET_FOCAL, "scaling_3d_scale": scale, "frames": 16, "yaw_step_deg": 0.01, "draw_calls": calls})
			print("STARSHIP_HEADSET ", tag, " draw_calls=", calls)
	view.scaling_3d_scale = 1.0
	view.scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
	await _lens_peak_set()
	await _star_gate_set()

# Stars and the faint field alone on black, for the real-sky checks: no room, no Earth, no Milky Way. earth_gain stays at 1, because the stars follow its square root: at 0 they
# would be gone and the gate would fail for no reason. So the Earth goes by a copy of the sky shader that leaves out its light, which also leaves the field in view, the part the gate must count.
func _star_gate_set() -> void:
	view.scaling_3d_scale = 1.0
	var sky: ShaderMaterial = room.get("sky_material")
	var exposure: Variant = sky.get_shader_parameter("galaxy_exposure")
	sky.set_shader_parameter("galaxy_exposure", 0.0)
	RenderingServer.global_shader_parameter_set("earth_gain", 1.0)
	var sky_shader: Shader = sky.shader
	var no_earth := Shader.new()
	no_earth.code = sky_shader.code.replace("COLOR = color + earth * earth_gain;", "COLOR = color;")
	assert(no_earth.code != sky_shader.code)
	sky.shader = no_earth
	var hidden := []
	for child in room.get_children():
		if child is Node3D and child.visible and child.name != "Stars":
			child.visible = false
			hidden.append(child)
	for direction in [["up70", 0.0, 70.0], ["left90", 90.0, 0.0], ["right90", -90.0, 0.0], ["aft_left", 135.0, 35.0], ["aft_right", -135.0, 35.0]]:
		eye.rotation_degrees = Vector3(direction[2], direction[1], 0)
		eye.position = SEAT
		var picture := await _capture(6)
		assert(picture.save_png(headset_output.path_join("stargate_" + direction[0] + ".png")) == OK)
	for child in hidden:
		child.visible = true
	sky.shader = sky_shader
	sky.set_shader_parameter("galaxy_exposure", exposure)
	RenderingServer.global_shader_parameter_set("earth_gain", room.get("earth_level"))

# Scene-buffer levels on the lamps: a linear tone map at exposure 0.5 writes 2.0 linear as 255, and the lens
# pass marks which pixels are lamps. they can be checked against the 1.6 linear emitter limit.
func _lens_peak_set() -> void:
	view.scaling_3d_scale = 1.0
	for light in [0.55, 1.0]:
		for direction in [["front", 0.0, 0.0], ["left90", 90.0, 0.0], ["right90", -90.0, 0.0], ["up70", 0.0, 70.0], ["down35", 0.0, -35.0], ["behind", 180.0, 0.0]]:
			var tag := "%s_L%03d" % [direction[0], int(round(light * 100))]
			_place({"name": "lens_peak", "yaw": direction[1], "pitch": direction[2], "offset": Vector3.ZERO, "light": light, "width": 4.2, "ambient": false})
			environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
			environment.tonemap_exposure = 0.5
			var picture := await _capture(6)
			room.apply_environment(environment)
			assert(picture.save_png(headset_output.path_join("lenspeak_" + tag + ".png")) == OK)
			var restore := _mask_mode()
			var mask := await _capture(6)
			_restore(restore)
			assert(mask.save_png(headset_output.path_join("lensmask_" + tag + ".png")) == OK)
	room.set_light(0.55)

func _capture(wait: int) -> Image:
	for i in wait:
		await process_frame
	await RenderingServer.frame_post_draw
	return view.get_texture().get_image()

# ---------------------------------------------------------------- real ambient
func _build_ambient() -> void:
	host = AmbientHost.new()
	host.name = "PreviewAmbientHost"
	host.room.contents = room
	var mode := OS.get_environment("STARSHIP_PREVIEW_AMBIENT_MODE")
	if not mode.is_empty():
		host.ambient_mode = int(mode)
	view.add_child(host)
	ambient = load("res://cinema_ambient.gd").new()
	ambient.host = host
	host.add_child(ambient)

func _set_ambient(enabled: bool, light: float) -> void:
	host.visible = enabled
	var mode := host.ambient_mode if enabled else 0
	if enabled:
		for i in mini(palette.size(), ambient.target.size()):
			ambient.target[i] = palette[i]
	for i in 60:
		ambient.advance(0.1, mode, host.ambient_brightness)
	if not enabled:
		for light_node in ambient.lights:
			light_node.light_energy = 0.0

# 256 edge colours of the still, in the sampler's order: top, right, bottom, left
# (bottom and left run backwards), 5% deep, linear light.
func _edge_palette(image: Image) -> Array[Color]:
	var result: Array[Color] = []
	var small: Image = image.duplicate()
	small.resize(640, 360, Image.INTERPOLATE_BILINEAR)
	var w: int = small.get_width()
	var h: int = small.get_height()
	var dx: int = maxi(1, int(ceil(w * 0.05)))
	var dy: int = maxi(1, int(ceil(h * 0.05)))
	for zone: int in 256:
		var side: int = zone / 64
		var segment: int = zone % 64
		var forward: int = segment if side < 2 else 63 - segment
		var horizontal: bool = side % 2 == 0
		var length: int = w if horizontal else h
		var low: int = int(floor(forward * length / 64.0))
		var high: int = maxi(low + 1, int(ceil((forward + 1) * length / 64.0)))
		var depth: int = dy if horizontal else dx
		var total := Color(0, 0, 0, 0)
		var count := 0
		for a: int in range(low, high):
			for d: int in depth:
				var x: int = a
				var y: int = a
				if horizontal:
					y = d if side == 0 else h - 1 - d
				else:
					x = w - 1 - d if side == 1 else d
				total += small.get_pixel(x, y).srgb_to_linear()
				count += 1
		result.append(total / maxf(count, 1))
	return result

# ---------------------------------------------------------------- materials
func _part_nodes() -> Array:
	var result := []
	for child in room.get_children():
		if child is MeshInstance3D and child.material_override is ShaderMaterial and child != screen and not str(child.name).contains("Prewarm"):
			result.append(child)
	return result

func _deck_material() -> ShaderMaterial:
	for node in _part_nodes():
		if node.name == "Deck" and _has_uniform(node.material_override, "mirror_strength"):
			return node.material_override
	return null

func _has_uniform(material: ShaderMaterial, name: String) -> bool:
	return _uniform_type(material, name) != TYPE_NIL

func _uniform_type(material: ShaderMaterial, name: String) -> int:
	if material == null or material.shader == null:
		return TYPE_NIL
	for uniform in material.shader.get_shader_uniform_list():
		if uniform.name == name:
			return int(uniform.type)
	return TYPE_NIL

func _apply_overrides() -> void:
	var deck: ShaderMaterial = null
	var hull := []
	for node in _part_nodes():
		if not _has_uniform(node.material_override, "baked_strength"):
			continue
		if node.name == "Deck":
			deck = node.material_override
		else:
			hull.append(node.material_override)
	if no_spec and deck != null:
		for name in ["mirror_strength", "field_gain"]:
			if _has_uniform(deck, name):
				deck.set_shader_parameter(name, 0.0)
	var groups := {"sky": [room.get("sky_material")], "stars": [room.get("star_material")], "deck": [deck], "hull": hull}
	for key in overrides:
		if key == "global":
			for param in overrides[key]:
				RenderingServer.global_shader_parameter_set(param, overrides[key][param])
			continue
		if not groups.has(key):
			print("STARSHIP_PREVIEW_PARAM_GROUP_UNKNOWN ", key)
			continue
		for material in groups[key]:
			if material == null:
				continue
			for param in overrides[key]:
				var kind := _uniform_type(material, param)
				if kind == TYPE_NIL:
					print("STARSHIP_PREVIEW_PARAM_UNKNOWN ", key, ".", param)
					continue
				material.set_shader_parameter(param, _convert(overrides[key][param], kind))

func _convert(value: Variant, kind: int) -> Variant:
	if value is Array:
		match kind:
			TYPE_VECTOR2: return Vector2(value[0], value[1])
			TYPE_VECTOR3: return Vector3(value[0], value[1], value[2])
			TYPE_VECTOR4: return Vector4(value[0], value[1], value[2], value[3])
			TYPE_COLOR: return Color(value[0], value[1], value[2], value[3] if value.size() > 3 else 1.0)
	match kind:
		TYPE_INT: return int(value)
		TYPE_BOOL: return bool(value)
		TYPE_FLOAT: return float(value)
	return value

func _read_overrides(text: String) -> Dictionary:
	if text.is_empty():
		return {}
	if not text.strip_edges().begins_with("{"):
		text = FileAccess.get_file_as_string(text)
	var parsed: Variant = JSON.parse_string(text)
	assert(parsed is Dictionary, "STARSHIP_PREVIEW_PARAMS must be a JSON object")
	return parsed

# Every part's baked_strength 0 except emission; sky, glow cards, picture, ambient
# and the housing's non-lamp surfaces off. What remains above 8 luma is lens.
func _mask_mode() -> Array:
	var saved := []
	# The movie light and the deck's field do not follow baked_strength. First, since it swaps
	# the deck back to its base variant, the material the next loop must dim.
	saved.append([ambient, "send_field", ambient.field_gain])
	ambient._send_field(0.0)
	for node in _part_nodes():
		var material: ShaderMaterial = node.material_override
		if node.name != "Emission" and _has_uniform(material, "baked_strength"):
			saved.append([material, "baked_strength", material.get_shader_parameter("baked_strength")])
			material.set_shader_parameter("baked_strength", 0.0)
	saved.append([environment, "background_mode", environment.background_mode])
	saved.append([environment, "background_color", environment.background_color])
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	for node in [screen, host]:
		saved.append([node, "visible", node.visible])
		node.visible = false
	for name in ["PracticalGlow", "GlowLeft", "GlowRight", "Stars", "Cities", "Objects"]:
		var glow := room.find_child(name, true, false)
		if glow != null:
			saved.append([glow, "visible", glow.visible])
			glow.visible = false
	var surround: Node = room.get("screen_surround")
	var amber: Material = room.get("amber_material")
	if surround != null:
		for piece in surround.find_children("*", "MeshInstance3D", true, false):
			var materials := []
			if piece.material_override != null:
				materials.append(piece.material_override)
			for i in piece.get_surface_override_material_count():
				if piece.get_surface_override_material(i) != null:
					materials.append(piece.get_surface_override_material(i))
			if piece.mesh != null:
				for i in piece.mesh.get_surface_count():
					if piece.mesh.surface_get_material(i) != null:
						materials.append(piece.mesh.surface_get_material(i))
			for material in materials:
				if material == amber:
					continue
				if material is ShaderMaterial:
					for param in ["strength", "brightness"]:
						if _has_uniform(material, param):
							saved.append([material, "shader:" + param, material.get_shader_parameter(param)])
							material.set_shader_parameter(param, 0.0)
				elif material is StandardMaterial3D:
					saved.append([material, "albedo_color", material.albedo_color])
					saved.append([material, "emission", material.emission])
					material.albedo_color = Color.BLACK
					material.emission = Color.BLACK
	return saved

func _restore(saved: Array) -> void:
	saved.reverse()
	for entry in saved:
		var target: Object = entry[0]
		var key: String = entry[1]
		if key.begins_with("shader:"):
			target.set_shader_parameter(key.substr(7), entry[2])
		elif key == "baked_strength":
			target.set_shader_parameter(key, entry[2])
		elif key == "send_field":
			target._send_field(entry[2])
		else:
			target.set(key, entry[2])
