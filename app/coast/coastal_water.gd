extends Node

# Reflection cameras share a private world with only coastal rocks. Empty
# coverage stays transparent; the water samples the sky along its own normals.
# XR matrices come from the separate pre-render extension after xrLocateViews.
const REFLECTION_LAYER := 16
var room: Node3D
var material: ShaderMaterial
var views: Array[SubViewport] = []
var mirrors: Array[Camera3D] = []
var sync: Object
var enabled := false
var previous_visible := false
var reflected_world: Environment
var reflected_root: Node3D
var reflected_rocks: Array[MeshInstance3D] = []
var source_rocks: Array[MeshInstance3D] = []
var fallback_camera: Camera3D

static func sequence(path: String, size: int, frames: int, format: Image.Format, mipmaps: bool) -> Texture2DArray:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null, path)
	var bytes := size * size * (1 if format == Image.FORMAT_R8 else 8)
	assert(file.get_length() == bytes * frames, path)
	var images: Array[Image] = []
	for index in frames:
		var image := Image.create_from_data(size, size, false, format, file.get_buffer(bytes))
		if mipmaps: image.generate_mipmaps()
		images.append(image)
	var texture := Texture2DArray.new()
	assert(texture.create_from_images(images) == OK)
	return texture

func setup(owner_room: Node3D, world: Environment, prefix: String) -> void:
	room = owner_room
	material = room.water_material
	material.shader = load(prefix + "spectral_water.gdshader")
	var metadata: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(prefix + "spectrum.json"))
	for kind in ["long_displacement", "long_normal", "short_normal"]:
		var name: String = {"long_displacement":"displacement-0.bin", "long_normal":"normals-0.bin", "short_normal":"normals-1.bin"}[kind]
		material.set_shader_parameter(kind, sequence(prefix + name, int(metadata.size), int(metadata.frames), Image.FORMAT_RGBAH, kind != "long_displacement"))
	var contact: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(prefix + "contact.json"))
	material.set_shader_parameter("contact_foam", sequence(prefix + "contact-foam.bin", int(contact.size), int(contact.frames), Image.FORMAT_R8, true))
	material.set_shader_parameter("frame_count", float(metadata.frames))
	material.set_shader_parameter("loop_duration", float(metadata.duration))
	material.set_shader_parameter("foam_enabled", true)
	for child in room.get_children():
		if child is MeshInstance3D:
			if child.material_override == material:
				child.layers = 1 # Controller-only fill light uses layer 2.
				child.extra_cull_margin = 2.0
			else:
				child.layers = 1
				source_rocks.append(child)
	reflected_world = world.duplicate()
	reflected_world.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	reflected_world.tonemap_exposure = 1.0
	for side in 2:
		var view := SubViewport.new()
		view.name = "WaterReflection%d" % side
		view.size = Vector2i(768, 768)
		view.use_hdr_2d = true
		# The water composites premultiplied reflected rocks over a separately
		# filtered sky lookup. No MSAA: ripples displace the lookup far more than
		# an edge step, and each mirror is its own (non-multiview) pass.
		view.transparent_bg = true
		view.msaa_3d = Viewport.MSAA_DISABLED
		view.render_target_update_mode = SubViewport.UPDATE_DISABLED
		view.own_world_3d = side == 0
		if side == 1: view.world_3d = views[0].find_world_3d()
		add_child(view)
		var mirror := Camera3D.new()
		mirror.cull_mask = REFLECTION_LAYER
		mirror.environment = reflected_world
		view.add_child(mirror)
		mirror.current = true
		views.append(view)
		mirrors.append(mirror)
		material.set_shader_parameter("planar_texture%d" % side, view.get_texture())
		RenderingServer.viewport_set_measure_render_time(view.get_viewport_rid(), true)
	# A separate world confines clip/discard to the low-resolution mirrors.
	# Main-eye rocks retain early depth rejection and normal MSAA behaviour.
	# Meshes and textures are shared; only instances/material state are copied.
	reflected_root = Node3D.new()
	views[0].add_child(reflected_root)
	var clip_shader: Shader = load(prefix + "reflection_rock.gdshader")
	for source in source_rocks:
		var copy := MeshInstance3D.new()
		copy.mesh = source.mesh
		# Rippled reflections take the baked LODs (the source rocks pin full detail).
		copy.lod_bias = 0.5
		copy.layers = REFLECTION_LAYER
		copy.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		var reflected: ShaderMaterial = source.material_override.duplicate()
		reflected.shader = clip_shader
		copy.material_override = reflected
		reflected_root.add_child(copy)
		reflected_rocks.append(copy)
	if Engine.has_singleton("FrameWaterSync"):
		sync = Engine.get_singleton("FrameWaterSync")
		sync.configure(mirrors[0].get_camera_rid(), mirrors[1].get_camera_rid(), material.get_rid(), views[0].get_viewport_rid(), views[1].get_viewport_rid())
	set_process(true)

func _process(_delta: float) -> void:
	var camera := fallback_camera if is_instance_valid(fallback_camera) else room.get_viewport().get_camera_3d()
	enabled = room.is_visible_in_tree() and is_instance_valid(camera)
	if enabled and camera is XRCamera3D and not camera.get_parent() is XROrigin3D:
		enabled = false
	if enabled != previous_visible:
		for view in views:
			view.render_target_update_mode = SubViewport.UPDATE_ALWAYS if enabled else SubViewport.UPDATE_DISABLED
		material.set_shader_parameter("use_planar", false)
		previous_visible = enabled
	var plane := room.global_transform
	plane.origin = room.to_global(Vector3(0, float(room.metadata.water_height), 0))
	var normal := plane.basis.y.normalized()
	var equation := Vector4(normal.x, normal.y, normal.z, -normal.dot(plane.origin))
	if enabled:
		for index in reflected_rocks.size():
			var copy := reflected_rocks[index]
			var source := source_rocks[index]
			copy.global_transform = source.global_transform
			var reflected: ShaderMaterial = copy.material_override
			reflected.set_shader_parameter("reflection_clip_plane", equation)
			reflected.set_shader_parameter("baked_strength", source.material_override.get_shader_parameter("baked_strength"))
	if sync != null and camera is XRCamera3D:
		var origin := camera.get_parent() as XROrigin3D
		if origin != null:
			sync.set_context(origin.global_transform, plane, camera.near, camera.far, enabled)
		else:
			sync.set_context(Transform3D.IDENTITY, plane, 0.05, 1800.0, false)
	else:
		# Clear retained native state before a desktop inspection camera or a
		# missing camera takes over; pre-render must not resurrect old targets.
		if sync != null: sync.set_context(Transform3D.IDENTITY, plane, 0.05, 1800.0, false)
		if enabled:
			for side in 2:
				update_desktop_eye(camera, side, plane)
			material.set_shader_parameter("use_planar", true)

func update_desktop_eye(camera: Camera3D, side: int, plane: Transform3D) -> void:
	# Non-XR inspection only. Native headset cameras are updated on the render
	# thread, never by this main-thread approximation.
	var normal := plane.basis.y.normalized()
	var eye := camera.global_transform
	var mirror := mirrors[side]
	var reflected := Transform3D(Basis(eye.basis.x.reflect(normal) * -1.0, eye.basis.y.reflect(normal), eye.basis.z.reflect(normal) * -1.0), eye.origin - normal * (2.0 * normal.dot(eye.origin - plane.origin)))
	# Camera3D fov is vertical in KEEP_HEIGHT. A square target fits the wider
	# source dimension; the extra margin retains reflection coverage on roll.
	var projection := camera.get_camera_projection()
	var left: float = (projection[2].x - 1.0) * camera.near / projection[0].x
	var right: float = (projection[2].x + 1.0) * camera.near / projection[0].x
	var bottom: float = -(projection[2].y + 1.0) * camera.near / projection[1].y
	var top: float = -(projection[2].y - 1.0) * camera.near / projection[1].y
	mirror.keep_aspect = Camera3D.KEEP_HEIGHT
	mirror.set_frustum(maxf(right-left, top-bottom) * 1.12, Vector2((right+left)*0.5, (top+bottom)*0.5), camera.near, camera.far)
	mirror.global_transform = reflected
	material.set_shader_parameter("reflection_projection%d" % side, mirror.get_camera_projection())
	material.set_shader_parameter("reflection_view%d" % side, reflected.affine_inverse())

func metrics() -> Dictionary:
	var gpu_ms := 0.0
	for view in views:
		gpu_ms += RenderingServer.viewport_get_measured_render_time_gpu(view.get_viewport_rid())
	return {"kind":"spectral_two_band", "reflections":views.size(), "enabled":enabled, "reflection_gpu_ms":gpu_ms, "sync":sync.state() if sync != null else {}}

func _exit_tree() -> void:
	# Stop render-thread writes before child cameras or the material are freed.
	if sync != null: sync.clear()
	if material != null:
		material.set_shader_parameter("use_planar", false)
		material.set_shader_parameter("planar_texture0", null)
		material.set_shader_parameter("planar_texture1", null)
	views.clear()
	mirrors.clear()
	reflected_rocks.clear()
	source_rocks.clear()
