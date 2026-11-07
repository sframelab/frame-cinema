extends Node3D

const MODES := ["Off", "Subtle", "Cinema", "Vivid", "Reactive"]
# Attack, decay and spread are our authored response profiles, not Hue internals.
const RESPONSE := [Vector3(0.5, 0.8, 0.9), Vector3(1.0, 1.6, 0.9), Vector3(0.32, 0.65, 1.3), Vector3(0.14, 0.35, 1.6), Vector3(0.045, 0.14, 1.9)]
const HUE_RESPONSE := [0.5, 0.55, 0.14, 0.075, 0.04]
const SEGMENTS := 64
const ZONES := SEGMENTS * 4
const MAX_PACKET_BYTES := 32768
const STRENGTH := [0.0, 0.45, 0.7, 1.0, 1.0]
const DESCRIPTIONS := ["No screen glow", "Gentle glow, very slow transitions", "Balanced glow, smooth transitions", "Fuller glow, quicker transitions", "Wide glow, fastest transitions"]
var host: Node3D
var halo: MeshInstance3D
var material: ShaderMaterial
var haze: MeshInstance3D
var haze_material: ShaderMaterial
var lights: Array[OmniLight3D] = []
var colors: Array[Color] = []
var target: Array[Color] = []
var available := false
var poll_elapsed := 0.0
var control_elapsed := 1.0
var accepted_source := ""
var sequence := 0.0
var layout := Vector2.ZERO
var layout_crop := -1.0
var fit_sample: Dictionary = {}
var plane_size := Vector2.ZERO
var uploaded_colors: Array[Color] = []
var color_image: Image
var color_texture: ImageTexture
var color_data := PackedFloat32Array()
var field_view: SubViewport
var field_material: ShaderMaterial
var diffusion_view: SubViewport
var diffusion_material: ShaderMaterial
var field_updates := 0
var contact_cache := {}
var contact_room := -1

func _ready() -> void:
	for index in range(ZONES):
		colors.append(Color.BLACK)
		target.append(Color.BLACK)
	color_image = Image.create(SEGMENTS, 4, false, Image.FORMAT_RGBAF)
	color_image.fill(Color.BLACK)
	color_texture = ImageTexture.create_from_image(color_image)
	color_data.resize(SEGMENTS * 4 * 4)
	diffusion_view = SubViewport.new()
	diffusion_view.size = Vector2i(384, 64)
	diffusion_view.disable_3d = true
	diffusion_view.use_hdr_2d = true
	diffusion_view.transparent_bg = true
	diffusion_view.render_target_update_mode = SubViewport.UPDATE_DISABLED
	add_child(diffusion_view)
	var diffusion := ColorRect.new()
	diffusion.size = Vector2(diffusion_view.size)
	diffusion_material = ShaderMaterial.new()
	diffusion_material.shader = preload("res://cinema_ambient_diffusion.gdshader")
	diffusion_material.set_shader_parameter("edge_colors", color_texture)
	diffusion.material = diffusion_material
	diffusion_view.add_child(diffusion)
	# Cache the continuous field once per palette, shared by both eyes and
	# both optical layers. Per-eye shading only reads the resulting texture.
	field_view = SubViewport.new()
	field_view.size = Vector2i(384, 256)
	field_view.disable_3d = true
	field_view.use_hdr_2d = true
	field_view.render_target_update_mode = SubViewport.UPDATE_DISABLED
	add_child(field_view)
	var field := ColorRect.new()
	field.size = Vector2(field_view.size)
	field_material = ShaderMaterial.new()
	field_material.shader = preload("res://cinema_ambient_field.gdshader")
	field_material.set_shader_parameter("edge_diffusion", diffusion_view.get_texture())
	field.material = field_material
	field_view.add_child(field)
	halo = MeshInstance3D.new()
	halo.position = Vector3(0, 2.1, -4.56)
	halo.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	material = ShaderMaterial.new()
	material.shader = preload("res://cinema_ambient.gdshader")
	material.set_shader_parameter("color_field", field_view.get_texture())
	halo.material_override = material
	halo.mesh = _ring(1)
	add_child(halo)
	haze = MeshInstance3D.new()
	haze.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	haze_material = ShaderMaterial.new()
	haze_material.shader = material.shader
	haze_material.set_shader_parameter("color_field", field_view.get_texture())
	haze.material_override = haze_material
	haze.mesh = _ring(12)
	haze_material.set_shader_parameter("recess", 0.65)
	add_child(haze)
	for index in range(2):
		var light := OmniLight3D.new()
		light.omni_range = 8.0
		light.omni_attenuation = 1.4
		light.shadow_enabled = false
		light.light_cull_mask = 1
		light.light_energy = 0
		add_child(light)
		lights.append(light)
	visible = false
	_layout(host._display_screen_width(), RESPONSE[host.ambient_mode].z)

func _layout(width: float, spread: float) -> void:
	var center: Vector3 = host._screen_center()
	var optical_scale: float = width / host.screen_width if host._alpine_room() else 1.0
	halo.scale = Vector3.ONE * optical_scale
	haze.scale = Vector3.ONE * optical_scale
	width /= optical_scale
	halo.position = center + Vector3(0, 0, -0.06 * optical_scale)
	haze.position = center + Vector3(0, 0, -0.28 * optical_scale)
	haze.visible = true
	var room: int = host.get("environment_index") if host.get("environment_index") != null else 5
	if room != contact_room:
		contact_room = room
		var path := "res://ambient-contact/room%d-contact.res" % room
		if not contact_cache.has(room) and ResourceLoader.exists(path):
			var loaded := load(path)
			if loaded is Texture2D: contact_cache[room] = loaded
		for optical in [material,haze_material]:
			# Coast's near rocks cross both glow planes. A height-map cutout
			# there floats above their viewed silhouette; fade optical haze
			# above the ledge instead, keeping the actual surface lights.
			optical.set_shader_parameter("ground_fade",Vector2(0.35,1.15) if room == 4 else Vector2(-100,-99))
			optical.set_shader_parameter("terrain_contact_enabled",room != 4 and room != 7 and contact_cache.has(room))
			if contact_cache.has(room): optical.set_shader_parameter("terrain_contact",contact_cache[room])
	# These positions and the offline maps are both relative to the shared
	# seat, so recentering cannot move the contact mask across the terrain.
	material.set_shader_parameter("screen_origin",halo.position)
	haze_material.set_shader_parameter("screen_origin",haze.position)
	for side in 2:
		lights[side].position = Vector3((-1 if side == 0 else 1) * width * 0.27, center.y - 0.45, center.z + 1.25)
	if layout == Vector2(width, spread) and is_equal_approx(layout_crop, host.picture_top):
		return
	layout = Vector2(width, spread)
	layout_crop = host.picture_top
	var size := Vector2(width, width * 9.0 / 16.0 * (1.0 - 2.0 * layout_crop))
	var optical_spread: float = spread * 0.65
	plane_size = size + Vector2.ONE * optical_spread * 3.2
	halo.custom_aabb = AABB(Vector3(-plane_size.x*.5,-plane_size.y*.5,-.01),Vector3(plane_size.x,plane_size.y,.02))
	material.set_shader_parameter("screen_size", size)
	material.set_shader_parameter("plane_size", plane_size)
	material.set_shader_parameter("spread", optical_spread)
	var haze_spread := spread * 1.05
	var haze_size := size + Vector2.ONE * haze_spread * 3.2
	haze.custom_aabb = AABB(Vector3(-haze_size.x*.5,-haze_size.y*.5,-.66),Vector3(haze_size.x,haze_size.y,.67))
	haze_material.set_shader_parameter("screen_size", size)
	haze_material.set_shader_parameter("plane_size", haze_size)
	haze_material.set_shader_parameter("spread", haze_spread)
	haze_material.set_shader_parameter("diffusion", 0.7)
	field_material.set_shader_parameter("screen_size", size)
	field_material.set_shader_parameter("field_size", haze_size)
	var margin := haze_spread * 1.6
	var sigma_max := 0.14 + 0.62 * margin
	for field_shader in [diffusion_material, field_material]:
		field_shader.set_shader_parameter("margin", margin)
		field_shader.set_shader_parameter("sigma_max", sigma_max)
	diffusion_material.set_shader_parameter("screen_size", size)
	for optical in [material, haze_material]:
		optical.set_shader_parameter("field_size", haze_size)
	_refresh_field()

func _refresh_field() -> void:
	diffusion_view.render_target_update_mode = SubViewport.UPDATE_ONCE
	field_view.render_target_update_mode = SubViewport.UPDATE_ONCE
	field_updates += 1

func _ring(contours: int) -> ArrayMesh:
	# Rounded constant-distance contours keep a smooth recessed field. The
	# vertex shader scales this cached topology during Fit/size transitions.
	# VERTEX stores radial direction/fraction; UV2 stores the rectangle corner.
	var vertices := PackedVector3Array()
	var uvs := PackedVector2Array()
	var corners := [Vector2(1, 1), Vector2(-1, 1), Vector2(-1, -1), Vector2(1, -1)]
	var per_contour := 4 * 17
	for ring in contours + 1:
		var fraction := float(ring) / float(contours)
		for corner in 4:
			for step in 17:
				var angle := (corner + float(step) / 16.0) * PI * 0.5
				vertices.append(Vector3(cos(angle), sin(angle), fraction))
				uvs.append(corners[corner])
	var indices := PackedInt32Array()
	for ring in contours:
		for side in per_contour:
			var current := ring * per_contour + side
			var next := ring * per_contour + (side + 1) % per_contour
			indices.append_array(PackedInt32Array([current, next, current + per_contour, next, next + per_contour, current + per_contour]))
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_TEX_UV2] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

static func expand_palette(palette: Array[Color]) -> Array[Color]:
	if palette.size() == ZONES:
		return palette.duplicate()
	var result: Array[Color] = []
	var old_segments := palette.size() / 4
	for side in 4:
		for zone in SEGMENTS:
			var position := clampf((zone + 0.5) * old_segments / float(SEGMENTS) - 0.5, 0.0, old_segments - 1.0)
			var first := int(position)
			result.append(palette[side * old_segments + first].lerp(palette[side * old_segments + mini(first + 1, old_segments - 1)], position - first))
	return result

func _update_edge_texture() -> void:
	if colors == uploaded_colors:
		return
	for index in ZONES:
		var offset := index * 4
		color_data[offset] = colors[index].r
		color_data[offset + 1] = colors[index].g
		color_data[offset + 2] = colors[index].b
		color_data[offset + 3] = 1.0
	color_image.set_data(SEGMENTS, 4, false, Image.FORMAT_RGBAF, color_data.to_byte_array())
	color_texture.update(color_image)
	_refresh_field()
	uploaded_colors = colors.duplicate()

func _edge_mean(side: int, low: float, high: float) -> Color:
	var total := Color(0, 0, 0, 0)
	for index in range(int(floor(low * SEGMENTS)), int(ceil(high * SEGMENTS))):
		var weight := maxf(0, minf(high, (index + 1.0) / SEGMENTS) - maxf(low, float(index) / SEGMENTS))
		total += colors[side * SEGMENTS + index] * weight
	return total / (high - low)

func _number(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value))

func accept(sample: Variant, source: String, now: float) -> bool:
	if source != accepted_source:
		accepted_source = source
		sequence = 0
		colors.fill(Color.BLACK)
		target.fill(Color.BLACK)
	if not sample is Dictionary or source.is_empty() or sample.get("session") != host.placement_session or sample.get("source_session") != source or not sample.get("available") is bool or sample.available != true:
		return false
	if not _number(sample.get("updated")) or now - float(sample.updated) < -0.01 or now - float(sample.updated) > 0.5:
		return false
	if not _number(sample.get("sequence")) or float(sample.sequence) < maxf(1, sequence) or float(sample.sequence) != floorf(float(sample.sequence)):
		return false
	var incoming: Variant = sample.get("colors")
	if not _number(sample.get("fit_top", 0.0)) or not _number(sample.get("fit_safe_top", 0.0)) or not sample.get("fit_known", false) is bool or not sample.get("fit_dark", false) is bool:
		return false
	if not incoming is Array or incoming.size() not in [12, 24, ZONES]:
		return false
	var next: Array[Color] = []
	for item in incoming:
		if not item is Array or item.size() != 3:
			return false
		for component in item:
			if not _number(component) or component < 0 or component > 1:
				return false
		next.append(Color(item[0], item[1], item[2], 1))
	target = expand_palette(next)
	fit_sample = {"fit_top": sample.get("fit_top", 0.0), "fit_safe_top": sample.get("fit_safe_top", 0.0), "fit_known": sample.get("fit_known", false), "fit_dark": sample.get("fit_dark", false), "sequence": sample.sequence, "source_session": source, "window": sample.get("window", 0), "viewport": sample.get("viewport", []), "updated": sample.updated}
	sequence = float(sample.sequence)
	return true

func _read() -> void:
	available = false
	if host.ipc.is_empty():
		return
	var status_path: String = host.ipc.path_join("status.json")
	var sample_path: String = host.ipc.path_join("ambient-status.json")
	if not FileAccess.file_exists(status_path) or not FileAccess.file_exists(sample_path):
		return
	var status: Variant = JSON.parse_string(FileAccess.get_file_as_string(status_path))
	var now := Time.get_unix_time_from_system()
	if not status is Dictionary or not _number(status.get("updated")) or absf(now - float(status.updated)) > 1.5 or status.get("panel_running") != true or not status.get("source_session") is String:
		return
	var file := FileAccess.open(sample_path, FileAccess.READ)
	if not file or file.get_length() > MAX_PACKET_BYTES:
		return
	available = accept(JSON.parse_string(file.get_as_text()), status.source_session, now)

func _scene_visible() -> bool:
	# Steam-native overlay controls take XR input focus while the room remains
	# visible. Lighting follows presentation, not ownership of controller input.
	return not host.xr_active or host._placement_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED]

func tick(delta: float) -> void:
	var mode: int = clampi(host.ambient_mode, 0, MODES.size() - 1)
	var enabled: bool = mode > 0 and not host.library_open and not host.source_pending and not host.browser_keyboard and (host.preview or (_scene_visible() and host.panel_fresh and host.panel_aligned))
	control_elapsed += delta
	if control_elapsed >= 0.25 and not host.ipc.is_empty() and not host.placement_session.is_empty():
		control_elapsed = 0
		var file := FileAccess.open(host.ipc.path_join("ambient-control.tmp"), FileAccess.WRITE)
		if file:
			var fit_enabled: bool = host.fit_picture and host.fit_media.get("fit_eligible") == true and not host.library_open and not host.source_pending and not host.browser_keyboard and host.panel_fresh and host.panel_aligned
			var reflection_enabled: bool = host._lake_reflection_wanted()
			file.store_string("FCAC1 %s %.6f %d %d" % [host.placement_session, Time.get_unix_time_from_system(), int(enabled or fit_enabled or reflection_enabled), int(reflection_enabled)])
			file.close()
			DirAccess.rename_absolute(host.ipc.path_join("ambient-control.tmp"), host.ipc.path_join("ambient-control.txt"))
	poll_elapsed += delta
	if poll_elapsed >= 0.033:
		poll_elapsed = 0
		_read()
	if not enabled or not available:
		target.fill(Color.BLACK)
	advance(delta, mode, host.ambient_brightness)
	if not enabled:
		# No detached glow when the screen is hidden, misaligned or the keyboard
		# has focus. Ordinary dark frames and stale capture still fade naturally.
		visible = false
		for light in lights:
			light.light_energy = 0
	if host.ui.page == "more":
		visible = false
		for light in lights:
			light.light_energy = 0

func advance(delta: float, mode: int, brightness: float) -> void:
	var response: Vector3 = RESPONSE[mode]
	var attack: float = response.x
	var decay: float = response.y
	var power := 0.0
	for index in range(ZONES):
		var rising: bool = target[index].get_luminance() > colors[index].get_luminance()
		var time_constant := attack if rising else decay
		var current_peak := maxf(colors[index].r, maxf(colors[index].g, colors[index].b))
		var target_peak := maxf(target[index].r, maxf(target[index].g, target[index].b))
		# Brightness fades retain the selected mode. Distinct colors follow the
		# picture sooner; convex RGB blending cannot overshoot either endpoint.
		if current_peak > 0.00000001 and target_peak > 0.00000001:
			var difference: Color = target[index] / target_peak - colors[index] / current_peak
			var hue_change := maxf(absf(difference.r), maxf(absf(difference.g), absf(difference.b)))
			var dimmer := minf(current_peak, target_peak)
			var brighter := maxf(current_peak, target_peak)
			var confidence := smoothstep(0.001, 0.015, dimmer) * smoothstep(0.18, 0.65, dimmer / brighter)
			time_constant = lerpf(time_constant, minf(time_constant, HUE_RESPONSE[mode]), confidence * smoothstep(0.12, 0.55, hue_change))
		var alpha := 1.0 - exp(-clampf(delta, 0, 0.1) / time_constant)
		colors[index] = colors[index].lerp(target[index], alpha)
		power = maxf(power, maxf(colors[index].r, maxf(colors[index].g, colors[index].b)))
	var gain: float = clampf(brightness, 0, 1) * STRENGTH[mode]
	visible = power * gain > 0.000001
	var width: float = host._display_screen_width()
	_layout(width, response.z)
	material.set_shader_parameter("brightness", gain * 0.85)
	if visible:
		_update_edge_texture()
	haze_material.set_shader_parameter("brightness", gain * 0.32)
	# Two broad sources approximate the lower screen's surface spill. Weight
	# the bottom edge and lower side, so sky/top credits cannot wash out the
	# foreground's color. These area averages are independent of zone count.
	for side in 2:
		var color := _edge_mean(2, 2.0/3.0 if side == 0 else 0.0, 1.0 if side == 0 else 1.0/3.0) * 0.45 + _edge_mean(2, 1.0/3.0, 2.0/3.0) * 0.20
		color += _edge_mean(3 if side == 0 else 1, 0.0 if side == 0 else 2.0/3.0, 1.0/3.0 if side == 0 else 1.0) * 0.20
		color += _edge_mean(3 if side == 0 else 1, 1.0/3.0, 2.0/3.0) * 0.10
		color += _edge_mean(0, 0.0 if side == 0 else 2.0/3.0, 1.0/3.0 if side == 0 else 1.0) * 0.05
		var peak := maxf(color.r, maxf(color.g, color.b))
		lights[side].light_color = (color / maxf(peak, 0.001)).linear_to_srgb()
		lights[side].light_energy = peak * gain * 10.0

func metrics() -> Dictionary:
	return {"mode": MODES[host.ambient_mode], "brightness": host.ambient_brightness, "response_seconds": [RESPONSE[host.ambient_mode].x, RESPONSE[host.ambient_mode].y], "hue_response_seconds": HUE_RESPONSE[host.ambient_mode], "zones": ZONES, "haze": true, "strength": STRENGTH[host.ambient_mode], "available": available, "visible": visible, "scenery_lights": lights.size()}
