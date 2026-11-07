extends Node

# On-demand bench view. Shares the running scene; reconstructs compositor panels
# from captured surfaces. It is intentionally not called a headset mirror.
const INSPECTION_LAYER := 1 << 19
var scene: Node3D
var busy := false
var last_request := ""
var poll_time := 0.0
var control_error := ""

func _process(delta: float) -> void:
	poll_time += delta
	if busy or poll_time < 0.25 or scene.ipc.is_empty():
		return
	poll_time = 0.0
	var path: String = scene.ipc.path_join("observe-request.json")
	if not FileAccess.file_exists(path):
		return
	var parser := JSON.new()
	if parser.parse(FileAccess.get_file_as_string(path)) != OK:
		return # A partial diagnostic request is ignored until its next poll.
	var request: Variant = parser.data
	if not request is Dictionary or not request.get("id") is String:
		return
	if request.id == last_request or request.id.length() > 80:
		return
	last_request = request.id
	busy = true
	if request.has("control") or request.get("show_controls", false):
		var age: float = Time.get_unix_time_from_system() - float(request.get("created", 0))
		if age < 0 or age > 10:
			_save_result({"id": last_request, "control_only": true, "control_error": "Inspection action expired; capture again"})
			busy = false
			return
	var prior_command: int = scene.media_request
	await _apply_control(request)
	if request.get("control_only", false):
		_save_result({"id": last_request, "control_only": true, "control_error": control_error,
			"source_request": scene.source_request,
			"command_request": scene.media_request if scene.media_request != prior_command else 0})
	else:
		await _capture()
	busy = false

func _apply_control(request: Dictionary) -> void:
	control_error = ""
	var controlling: bool = request.has("control") or request.get("show_controls", false)
	if controlling and scene.controllers.any(func(controller): return controller.get_has_tracking_data()):
		control_error = "Controller tracking is active; off-head input refused"
	if controlling and control_error.is_empty() and request.get("show_controls", false) and (scene.focused_view or not scene.dock.visible):
		scene._show_controls()
		await get_tree().process_frame
		await get_tree().process_frame
	if controlling and control_error.is_empty() and scene.controllers.any(func(controller): return controller.get_has_tracking_data()):
		control_error = "Controller tracking resumed; off-head input refused"
	if request.has("control") and request.control is Array and request.control.size() == 2:
		var pixel := Vector2(float(request.control[0]), float(request.control[1]))
		# Development input targets the actual GUI, never a synthetic physical pose.
		if control_error.is_empty() and scene.dock.visible and Rect2(Vector2.ZERO, Vector2(scene.ui_viewport.size)).has_point(pixel):
			scene.inspection_input = true
			# Exercise the same click dispatcher as the compositor. The legacy
			# hover path deliberately ignores input while native UI is enabled.
			if OS.get_environment("FRAME_CINEMA_UNIFIED_UI") == "1":
				for child in scene.get_children():
					if child.has_meta("native_input"):
						child.consume_events([{"kind": "click", "position": pixel * scene._ui_size() / Vector2(scene.ui_viewport.size)}])
						await get_tree().process_frame
						scene.inspection_input = false
						return
				scene.inspection_input = false
				control_error = "Native menu input is unavailable"
				return
			scene._dock_click(pixel * scene._ui_size() / Vector2(scene.ui_viewport.size), true)
			await get_tree().create_timer(0.06).timeout
			if scene.controllers.any(func(controller): return controller.get_has_tracking_data()):
				control_error = "Controller tracking resumed; off-head click cancelled"
				scene._dock_click(null, false)
			else:
				scene._dock_click(pixel * scene._ui_size() / Vector2(scene.ui_viewport.size), false)
			await get_tree().process_frame
			scene.inspection_input = false
		elif control_error.is_empty():
			control_error = "Control point is outside the visible controls"

func _surface(parent: Node, filename: String, width: float, position: Vector3) -> MeshInstance3D:
	var source: String = scene.ipc.path_join(filename)
	if not FileAccess.file_exists(source):
		return null
	var picture := Image.load_from_file(source)
	if picture == null or picture.is_empty():
		return null
	if filename == "observe-browser.png" and scene.picture_top > 0.0001:
		var margin := roundi(picture.get_height() * scene.picture_top)
		picture = picture.get_region(Rect2i(0, margin, picture.get_width(), picture.get_height() - margin * 2))
	var mesh := MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(width, width * picture.get_height() / float(picture.get_width()))
	mesh.mesh = quad
	mesh.layers = INSPECTION_LAYER
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = ImageTexture.create_from_image(picture)
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mesh.material_override = material
	parent.add_child(mesh)
	mesh.global_transform = scene.seat.global_transform * Transform3D(Basis.IDENTITY, position)
	return mesh

func _capture() -> void:
	var view := SubViewport.new()
	view.size = Vector2i(1600, 1200)
	view.use_xr = false
	view.msaa_3d = Viewport.MSAA_4X
	view.world_3d = scene.get_world_3d()
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(view)
	var eye := Camera3D.new()
	eye.fov = 78
	view.add_child(eye)
	eye.global_transform = scene.seat.global_transform * Transform3D(Basis.IDENTITY, Vector3(0, 1.65, 0))
	eye.rotate_object_local(Vector3.RIGHT, deg_to_rad(-8.0))
	eye.current = true
	# Inspection-only panel meshes must never appear in the real XR camera.
	var old_mask: int = scene.camera.cull_mask
	scene.camera.cull_mask = old_mask & ~INSPECTION_LAYER
	var browser: MeshInstance3D = null
	if not scene.library_open and scene.ui.page != "more":
		browser = _surface(view, "observe-browser.png", scene.screen_width, scene._screen_center())
	var keyboard: MeshInstance3D = null
	var panel: Variant = {}
	if FileAccess.file_exists(scene.ipc.path_join("panel-status.json")):
		panel = JSON.parse_string(FileAccess.get_file_as_string(scene.ipc.path_join("panel-status.json")))
	if panel is Dictionary and panel.get("keyboard_visible", false):
		keyboard = _surface(view, "observe-keyboard.png", 2.0, Vector3(0, 1.05, -1.7))
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	scene._write_report()
	var scene_error := view.get_texture().get_image().save_png(scene.ipc.path_join("observe-scene.png"))
	var dock_error: int = scene.ui_viewport.get_texture().get_image().save_png(scene.ipc.path_join("observe-controls.png"))
	if browser != null:
		browser.free()
	if keyboard != null:
		keyboard.free()
	view.free()
	scene.camera.cull_mask = old_mask
	var report := {"id": last_request, "mode": "bench reconstruction from live app surfaces",
		"control_error": control_error,
		"headset_compositor_capture": false, "camera": "fixed seated inspection camera",
		"scene_error": scene_error, "controls_error": dock_error,
		"panel_placement": "intended seated layout; physical tracking alignment not asserted",
		"width": 1600, "height": 1200, "frame": Engine.get_frames_drawn()}
	_save_result(report)

func _save_result(report: Dictionary) -> void:
	var output := FileAccess.open(scene.ipc.path_join("observe-result.tmp"), FileAccess.WRITE)
	if output:
		output.store_string(JSON.stringify(report))
		output.close()
		DirAccess.rename_absolute(scene.ipc.path_join("observe-result.tmp"), scene.ipc.path_join("observe-result.json"))
