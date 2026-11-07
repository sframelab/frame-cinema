extends Node3D

const ENVIRONMENTS := preload("res://cinema_rooms.gd").IDS
const NAMES := preload("res://cinema_rooms.gd").NAMES
const BROWSER_REACH_METRES := 10.0
var environment_index := 3
var light_level := 0.55
var ambient_mode := 2
var ambient_brightness := 0.5
var ambient: Node3D
var ambient_button: Button
var ambient_brightness_button: Button
var origin: XROrigin3D
var camera: Camera3D
var world: WorldEnvironment
var room: Node3D
var room_brightness := 0.55
var ui_viewport: SubViewport
var dock: MeshInstance3D
var seat: Node3D
var status_label: Label
var environment_button: Button
var light_button: Button
var preview := false
var xr_active := false
var smoke := false
var elapsed := 0.0
var report_tick := 0.0
var ipc := ""
var pointer_down := false
var screen_width := 4.2
var fit_picture := false
var stereo_mode := 0
var stereo_controller := preload("res://stereo/stereo_control.gd").new()
var picture_fit: RefCounted = preload("res://picture_fit.gd").new()
var last_fit_reason := ""
var last_fit_identity := ""
var picture_top := 0.0 # Native acknowledged texture bounds, used by the halo.
var fit_media: Dictionary = {}
var fit_poll := 0.0
var screen_button: Button
var placed := false
var placement_pending := true
var recenter_request := 0
var placement_session := ""
var placement_generation := 1
var placement_sequence := 0
var placement_tick := 0.0
var placement_dirty := true
var recenter_cause := "startup"
var recenter_deadline_msec := 0
var seated_reference := false
var reference_mode_ready := false
var local_reference_resets := 0
var placement_reference := Transform3D.IDENTITY
var pose_sync: Object
var pose_time_ns := 0
var reference_overflows := 0
var reference_preserved := 0
var reference_unknown := 0
var command_sequence := 0
var right_pointer: XRController3D
var scroll_tick := 0.0
var controllers: Array[XRController3D] = []
var active_pointer: XRController3D
var click_owner: XRController3D
var click_target := ""
var trigger_states := {}
var trigger_rearm := {}
var mouse_inside := false
var mouse_position := Vector2(-1, -1)
var dock_cursor: Panel
var input_counts := {"buttons": 0, "trigger_down": 0, "dock_down": 0, "browser_down": 0}
var button_actions := {}
var render_models: Node3D
var model_fallbacks := {}
var pointer_rays := {}
var browser_keyboard := false
var source_mode := "auto"
var panel_message := ""
var controller_foreground: Dictionary = {}
var runtime_hand_models: Dictionary = {}
var panel_attention := false
var recovery_attention := false
var preferences_path := "user://settings.cfg"
var panel_heartbeat := ""
var panel_seen := 0
var panel_fresh := false
var panel_aligned := false
var compositor_pointer := false
var panel_poll_tick := 0.0
var ui: RefCounted
var services: Array = []
var selected_service := "netflix"
var library_open := true
var focused_view := false
var source_request := 0
var source_pending := false
var source_requested_at := 0
var source_error := ""
var service_wait_since := -1
var service_wait_reason := ""
var shell_tick := 0.0
var media_state := {}
var playback_health: RefCounted = preload("res://playback_health.gd").new()
var playback_message := ""
var media_buttons: Array[Button] = []
var play_button: Button
var fullscreen_button: Button
var media_request := 0
var media_request_navigation := false
var inspection_input := false
var media_requested_at := 0
var media_notice := ""
var media_notice_until := 0
var frame_pacing: RefCounted = preload("res://frame_pacing.gd").new()
var viewing_idle: RefCounted = preload("res://viewing_idle.gd").new()
var idle_poll_msec := 0
var automatic_focus_entries := 0
var idle_panel_scroll := -1

func _note_activity() -> void:
	viewing_idle.touch(Time.get_ticks_msec() * 0.001)

func _tick_viewing_idle() -> void:
	var now_msec := Time.get_ticks_msec()
	if now_msec < idle_poll_msec: return
	idle_poll_msec = now_msec + 33
	var now := now_msec * 0.001
	var native: Object = Engine.get_singleton("FrameNativeUI") if Engine.has_singleton("FrameNativeUI") else null
	var activity: Dictionary = native.poll_controller_activity() if native else {"available":false}
	_apply_viewing_idle(activity, now)
	if native: native.set_controllers_idle(viewing_idle.hidden)

func _apply_viewing_idle(activity: Dictionary, now: float) -> void:
	viewing_idle.observe(activity.get("hands", []), now)
	var suspended: bool = not activity.get("available", false) or browser_keyboard or pointer_down or (xr_active and _placement_session_state() not in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED])
	var eligible: bool = ui.page == "player" and not library_open and not source_pending and not recovery_attention and panel_fresh and panel_aligned and media_state.get("available", false) and media_state.get("title_player", false) and media_state.get("video", false) and not media_state.get("paused", true) and not media_state.get("ended", false) and _fresh_status(media_state, 3.0)
	if viewing_idle.advance(now, eligible, suspended):
		automatic_focus_entries += 1
		_focus_screen()

func _ready() -> void:
	preview = OS.get_cmdline_user_args().has("--preview")
	smoke = OS.get_cmdline_user_args().has("--smoke")
	ipc = OS.get_environment("FRAME_CINEMA_IPC")
	if not ipc.is_empty(): frame_pacing.log_path = ipc.path_join("pacing-events.log")
	placement_session = OS.get_environment("FRAME_CINEMA_SESSION")
	services = JSON.parse_string(FileAccess.get_file_as_string("res://services.json"))
	var settings := ConfigFile.new()
	if settings.load(preferences_path) == OK:
		environment_index = clampi(int(settings.get_value("scene", "environment", 3)), 0, ENVIRONMENTS.size() - 1)
		if not preload("res://cinema_rooms.gd").available(environment_index):
			environment_index = preload("res://cinema_rooms.gd").default_index()
		light_level = clampf(float(settings.get_value("scene", "light", 0.55)), 0.15, 1.0)
		screen_width = clampf(float(settings.get_value("scene", "screen_width", 4.2)), 3.2, 5.4)
		fit_picture = bool(settings.get_value("scene", "fit_picture", false))
		stereo_mode = clampi(int(settings.get_value("scene", "stereo_mode", 0)), 0, 3)
		ambient_mode = clampi(int(settings.get_value("ambient", "mode", 2)), 0, 4)
		ambient_brightness = clampf(float(settings.get_value("ambient", "brightness", 0.5)), 0.0, 1.0)
		# 0.5.1: edge smoothing and foveation are fixed (MSAA 2x, off); not user options.
		alpine_height = clampi(int(settings.get_value("scene", "alpine_layout", 0)), 0, ALPINE_BOTTOM_DEG.size() - 1)
	if not preload("res://cinema_rooms.gd").available(environment_index):
		environment_index = preload("res://cinema_rooms.gd").default_index()
	var xr := XRServer.find_interface("OpenXR")
	if Engine.has_singleton("FramePoseSync"):
		pose_sync = Engine.get_singleton("FramePoseSync")
	if not preview and xr:
		xr_active = xr.is_initialized() or xr.initialize()
	# Adopt the actual space on the first predicted-pose frame: the API's
	# constructor mode is only a placeholder before setup_play_space runs.
	reference_mode_ready = not xr_active
	get_viewport().use_xr = xr_active
	_apply_antialiasing()
	_apply_foveation()
	# Foveation is off: clear any mode saved by a 0.4.49-0.5.0 build so start.sh
	# launches without it from now on.
	_write_foveation_override(false)
	# Mobile's 10-bit scene buffer needs dithering before tonemapping as well
	# as at final output; viewport-only debanding leaves halo color steps.
	RenderingServer.material_set_use_debanding(true)
	get_viewport().use_debanding = true
	RenderingServer.viewport_set_measure_render_time(get_viewport().get_viewport_rid(), true)
	if xr_active and xr.has_signal("pose_recentered"):
		xr.connect("pose_recentered", _reference_space_reset)
	if xr_active:
		# Godot 4.7.2 recreates its swapchain when this multiplier changes.
		# Raise Frame's 1728 default to native 2160; preserve higher runtime choices.
		var recommended: Vector2 = xr.get_render_target_size()
		if recommended.x > 0 and recommended.x < 2160:
			xr.render_target_size_multiplier *= 2160.0 / recommended.x
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		if xr.has_signal("session_begun"):
			xr.connect("session_begun", _prefer_refresh_rate)
		_prefer_refresh_rate.call_deferred()
		_write_overlay_debug.call_deferred()
	world = WorldEnvironment.new()
	world.environment = Environment.new()
	add_child(world)
	origin = XROrigin3D.new()
	add_child(origin)
	placement_reference = origin.global_transform * XRServer.get_reference_frame()
	if xr_active:
		camera = XRCamera3D.new()
	else:
		camera = Camera3D.new()
		camera.position.y = 1.65
	origin.add_child(camera)
	camera.far = 1800.0
	camera.current = true
	seat = Node3D.new()
	add_child(seat)
	room = preload("res://cinema_rooms.gd").new()
	seat.add_child(room)
	_build_dock()
	_load_environment()
	room.prewarm()
	ambient = preload("res://cinema_ambient.gd").new()
	ambient.host = self
	seat.add_child(ambient)
	if xr_active:
		# Keep controller models legible when the room dims. This light only
		# affects their dedicated layer, never the room or the video surface.
		var controller_fill := DirectionalLight3D.new()
		controller_fill.rotation_degrees = Vector3(-40, -20, 0)
		controller_fill.light_color = Color(0.82, 0.87, 0.95)
		controller_fill.light_energy = 0.85
		controller_fill.light_cull_mask = 2
		origin.add_child(controller_fill)
		render_models = OpenXRRenderModelManager.new()
		origin.add_child(render_models)
		for side in ["left", "right"]:
			_build_controller(side)
			var grip := XRController3D.new()
			grip.tracker = side + "_hand"
			grip.pose = "grip"
			grip.show_when_tracked = true
			origin.add_child(grip)
			var model: MeshInstance3D = load("res://controller_model.gd").load_installed(side)
			if model:
				model.layers = 2
				grip.add_child(model)
				model_fallbacks["/user/hand/" + side] = model
		active_pointer = right_pointer
	_write_report()
	# The observer takes pictures of the scene and presses its controls on request. Developers only.
	if OS.get_environment("FRAME_CINEMA_DEVELOPER") == "1":
		var observer: Node = load("res://observer_view.gd").new()
		observer.scene = self
		add_child(observer)
	if OS.get_environment("FRAME_CINEMA_UNIFIED_UI") == "1":
		var native_ui_node: Node = load("res://native-ui/native_ui.gd").new()
		native_ui_node.scene = self
		add_child(native_ui_node)
	# Private native-controller preview only; normal startup remains the library.
	if OS.get_environment("FRAME_CINEMA_NATIVE_PREVIEW") == "1" and OS.get_environment("FRAME_CINEMA_UNIFIED_UI") != "1":
		_open_service.call_deferred("netflix")

func _build_controller(side: String) -> XRController3D:
	var controller := XRController3D.new()
	controller.tracker = side + "_hand"
	controller.pose = "aim"
	controller.show_when_tracked = true
	origin.add_child(controller)
	controllers.append(controller)
	if side == "right":
		right_pointer = controller
	controller.button_pressed.connect(_controller_pressed.bind(controller))
	controller.button_released.connect(_controller_released.bind(controller))
	controller.input_float_changed.connect(_controller_float_changed.bind(controller))
	var ray := MeshInstance3D.new()
	var ray_mesh := CylinderMesh.new()
	ray_mesh.top_radius = 0.002
	ray_mesh.bottom_radius = 0.002
	ray_mesh.height = 6.0
	ray.mesh = ray_mesh
	ray.rotation_degrees.x = 90
	ray.position.z = -3.0
	var ray_material := StandardMaterial3D.new()
	ray_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	ray_material.albedo_color = Color(0.7, 0.8, 0.9)
	ray.material_override = ray_material
	controller.add_child(ray)
	pointer_rays[controller.tracker] = ray
	return controller

func _build_dock() -> void:
	ui = load("res://cinema_ui.gd").new()
	ui.build(self)

func _render_ui(page: String) -> void:
	_hover_dock(null)
	if page in ["room", "more"]:
		# Room is a modal console while the movie remains visible. Dismiss the
		# editor keyboard in command order, including any queued open request.
		_browser_command(5)
	focused_view = page == "focus"
	_apply_room_light()
	ui.show_page(page)
	dock.visible = true
	_update_status()

func _service_name() -> String:
	for entry in services:
		if entry.id == selected_service:
			return entry.name
	return "Cinema"

func _environment_name() -> String:
	return NAMES[environment_index] if environment_index >= 0 else "Environment unavailable"

func _open_service(identifier: String) -> void:
	_note_activity()
	if not services.any(func(entry): return entry.id == identifier):
		return
	selected_service = identifier
	media_state = {}
	media_request = 0
	media_notice = ""
	library_open = false
	focused_view = false
	_apply_room_light()
	_render_ui.call_deferred("player")
	_select_source("local")

func _show_library() -> void:
	_note_activity()
	library_open = true
	focused_view = false
	_apply_room_light()
	browser_keyboard = false
	compositor_pointer = false
	media_state = {}
	media_request = 0
	media_notice = ""
	_render_ui.call_deferred("library")
	_source_request({"action": "library"})

func _show_room() -> void:
	_render_ui.call_deferred("room")

func _show_recovery() -> void:
	_render_ui.call_deferred("more")

func _close_room() -> void:
	_render_ui.call_deferred("library" if library_open else "player")

func _reopen_service() -> void:
	if library_open:
		return
	_select_source("local", true)
	_render_ui.call_deferred("player")

func _focus_screen() -> void:
	if library_open:
		return
	_browser_command(5)
	focused_view = true
	_apply_room_light()
	dock.visible = false
	_hover_dock(null)
	_render_ui.call_deferred("focus")

func _show_controls() -> void:
	_note_activity()
	focused_view = false
	_apply_room_light()
	_render_ui.call_deferred("library" if library_open else "player")

func _toggle_controls() -> void:
	if browser_keyboard:
		_browser_command(5)
		return
	if ui.page in ["room", "more"]:
		_close_room()
		return
	if library_open:
		dock.visible = true
		return
	if focused_view or not dock.visible:
		_show_controls()
	else:
		_focus_screen()

func _set_environment(index: int) -> void:
	if not preload("res://cinema_rooms.gd").available(index):
		return
	var previous_center := _screen_center()
	environment_index = clampi(index, 0, ENVIRONMENTS.size() - 1)
	if not _dark_room():
		stereo_controller.allowed = false
		stereo_controller.revision += 1
		_write_presentation()
	_load_environment()
	if not previous_center.is_equal_approx(_screen_center()):
		# Version the changed anchor without re-aiming or moving the room. The
		# native bridge rejects any changed screen pose with an old revision.
		recenter_request += 1
	placement_dirty = true
	_save()
	_render_ui.call_deferred(ui.page)

func _source_request(value: Dictionary) -> void:
	playback_health.reset()
	playback_message = ""
	if ipc.is_empty():
		return
	source_request = Time.get_ticks_usec()
	source_pending = true
	source_requested_at = Time.get_ticks_msec()
	source_error = ""
	service_wait_since = -1
	service_wait_reason = ""
	media_state = {}
	media_request = 0
	media_notice = ""
	panel_message = ""
	value["id"] = source_request
	var file := FileAccess.open(ipc.path_join("request.tmp"), FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(value))
		file.close()
		if DirAccess.rename_absolute(ipc.path_join("request.tmp"), ipc.path_join("request.json")) == OK:
			return
	source_pending = false
	source_error = "Could not send request · Relaunch from Steam"

func _media_enabled(operation: String) -> bool:
	if not media_state.get("available", false):
		return false
	if operation == "exit_fullscreen":
		return media_state.get("fullscreen", false)
	return media_state.get("can_control", false) and (not operation in ["back_10", "forward_10"] or media_state.get("can_seek", false))

func _media_command(operation: String) -> void:
	if ipc.is_empty() or library_open or not operation in ["toggle_play", "back_10", "forward_10", "exit_fullscreen"]:
		return
	command_sequence = maxi(command_sequence + 1, Time.get_ticks_usec())
	DirAccess.make_dir_recursive_absolute(ipc.path_join("media"))
	var name := "media/%020d" % command_sequence
	var file := FileAccess.open(ipc.path_join(name + ".tmp"), FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify({"id": command_sequence, "op": operation, "created": Time.get_unix_time_from_system()}))
		file.close()
		DirAccess.rename_absolute(ipc.path_join(name + ".tmp"), ipc.path_join(name + ".json"))
		media_request = command_sequence
		media_request_navigation = false
		media_requested_at = Time.get_ticks_msec()
		media_notice = ""

func _media_feedback(state: Dictionary) -> void:
	if media_request == 0:
		return
	var response: Variant = state.get("last_command", {})
	var response_id: Variant = response.get("id") if response is Dictionary else null
	if (response_id is int or response_id is float) and int(response_id) == media_request:
		media_request = 0
		if not response.get("ok", false):
			media_notice = "Navigation unavailable · try Reopen" if media_request_navigation else "Use the service's player controls"
			if response.get("reason") == "no_history":
				media_notice = "No earlier page · choose Services to return"
			media_notice_until = Time.get_ticks_msec() + 5000
	elif Time.get_ticks_msec() - media_requested_at > 6000:
		media_request = 0
		media_notice = "Navigation did not respond · try Reopen" if media_request_navigation else "No response · try the service's player controls"
		media_notice_until = Time.get_ticks_msec() + 5000

func _load_environment() -> void:
	if not preload("res://cinema_rooms.gd").available(environment_index):
		environment_index = preload("res://cinema_rooms.gd").default_index()
	# Keep the lower lake continuous to the horizon at Alpine's authored scale. The Observation Deck wants it for its
	# sky: Godot 4.7's multiview sky adds the eye offset where it should subtract it, which puts the sky at far / 2
	# (900 m at 1800, 60 km here). Its stars are at true infinity either way (stars.gdshader, w = 0).
	camera.far = 120000.0 if _alpine_room() or _starship_room() else 1800.0
	room_brightness = minf(light_level, 0.12) if focused_view else light_level
	room.configure(world.environment, environment_index, room_brightness)
	_follow_room_screen()
	if is_instance_valid(environment_button):
		environment_button.text = _environment_name()

func _apply_room_light() -> void:
	room_brightness = minf(light_level, 0.12) if focused_view else light_level
	if is_instance_valid(room) and room.room_index >= 0:
		room.set_light(room_brightness)

func _save() -> void:
	var settings := ConfigFile.new()
	settings.set_value("scene", "environment", environment_index)
	settings.set_value("scene", "light", light_level)
	settings.set_value("scene", "screen_width", screen_width)
	settings.set_value("scene", "fit_picture", fit_picture)
	settings.set_value("scene", "stereo_mode", stereo_mode)
	settings.set_value("ambient", "mode", ambient_mode)
	settings.set_value("ambient", "brightness", ambient_brightness)
	settings.set_value("scene", "edge_smoothing", antialiasing)
	settings.set_value("scene", "alpine_layout", alpine_height)
	settings.set_value("scene", "foveation_owner", foveation)
	settings.save(preferences_path)

func _cycle_environment() -> void:
	var options: Array[int] = preload("res://cinema_rooms.gd").available_indices()
	if options.is_empty():
		return
	_set_environment(options[(options.find(environment_index) + 1) % options.size()])

func _cycle_light() -> void:
	_set_room_light(0.2 if light_level > 0.3 else 1.0)

func _set_room_light(value: float) -> void:
	if _dark_room(): return
	light_level = clampf(value, 0.2, 1.0)
	_apply_room_light()
	ui.refresh_settings()
	_save()

func _set_screen_width(value: float) -> void:
	if value not in [3.2, 4.2, 5.4]: return
	frame_pacing.note("screen_width", {"from": screen_width, "to": value, "library": library_open, "page": ui.page})
	var previous_center := _screen_center()
	screen_width = value
	_follow_room_screen()
	if not previous_center.is_equal_approx(_screen_center()):
		recenter_request += 1
	_position_dock()
	placement_dirty = true
	ui.refresh_settings()
	_save()

func _set_ambient_mode(value: int) -> void:
	if _alpine_room(): return
	ambient_mode = clampi(value, 0, ambient.MODES.size() - 1)
	ui.refresh_settings()
	_save()

func _set_ambient_brightness(value: float) -> void:
	if _alpine_room(): return
	ambient_brightness = clampf(value, 0.25, 1.0)
	ui.refresh_settings()
	_save()

func _cycle_ambient() -> void:
	_set_ambient_mode((ambient_mode + 1) % ambient.MODES.size())

func _cycle_ambient_brightness() -> void:
	_set_ambient_brightness(0.25 if ambient_brightness >= 0.99 else minf(ambient_brightness + 0.25, 1.0))

func _recenter(cause: String = "menu") -> void:
	recenter_cause = cause
	frame_pacing.note("recenter:" + cause)
	placement_pending = true
	recenter_deadline_msec = Time.get_ticks_msec() + 2000 if placed else 0
	if not xr_active:
		_try_recenter()

func _reference_space_reset() -> void:
	if pose_sync and pose_sync.state().get("instance_created", false):
		return # The native event includes the delta and when it takes effect.
	# This signal has neither space type nor effective time. Without our
	# required native bridge it cannot safely identify a LOCAL reset.
	_unknown_reference_change()

func _adopt_reference_mode(mode: int) -> void:
	if reference_mode_ready: return
	if mode not in [XRInterface.XR_PLAY_AREA_SITTING, XRInterface.XR_PLAY_AREA_STAGE, XRInterface.XR_PLAY_AREA_ROOMSCALE]: return
	seated_reference = mode == XRInterface.XR_PLAY_AREA_SITTING
	origin.global_transform = Transform3D(Basis.IDENTITY, Vector3(0, 1.65 if seated_reference else 0.0, 0))
	placement_reference = origin.global_transform * XRServer.get_reference_frame()
	reference_mode_ready = true

func _unknown_reference_change() -> void:
	placement_generation += 1
	reference_unknown += 1
	recenter_cause = "reference alignment recovery"
	frame_pacing.note("unknown_reference_change")
	# Revalidate coordinates without choosing a new viewing direction.
	# An invalid runtime delta cannot promise physical anchor preservation.

func _apply_reference_delta(delta: Transform3D) -> void:
	origin.global_transform = placement_reference * delta * XRServer.get_reference_frame().affine_inverse()
	placement_reference = origin.global_transform * XRServer.get_reference_frame()
	reference_preserved += 1
	frame_pacing.note("reference_delta")

func _canonical_local_reset() -> void:
	# LOCAL defines a level head origin and forward direction. A new LOCAL
	# definition supersedes our earlier manual seat offset, even without a
	# valid old-to-new delta. Never re-aim from a later recovery head pose.
	origin.global_transform = Transform3D(Basis.IDENTITY, Vector3(0, 1.65, 0))
	placement_reference = origin.global_transform * XRServer.get_reference_frame()
	placement_generation += 1
	local_reference_resets += 1
	recenter_cause = "system reference reset"
	frame_pacing.note("local_reference_reset")
	_commit_seat(Transform3D.IDENTITY)

func _apply_due_reference_changes(changes: Array, lost: bool, space_type: int) -> void:
	# FramePoseSync deduplicates and returns only events whose changeTime is
	# effective at the current predicted display time. Commit a burst once.
	if seated_reference and space_type == 2:
		if lost or not changes.is_empty():
			_canonical_local_reset()
		return
	for change in changes:
		if not change.get("valid", false): lost = true
	if lost:
		_unknown_reference_change()
	elif space_type != 0:
		for change in changes:
			_apply_reference_delta(change.delta)

func _update_reference_space() -> void:
	if pose_sync and xr_active:
		var api: Object = pose_sync.get_openxr_api()
		var predicted: int = api.get_predicted_display_time()
		var state: Dictionary = pose_sync.state()
		var overflow: int = state.get("queue_overflows", 0)
		var lost := overflow != reference_overflows
		reference_overflows = overflow
		var xr := XRServer.find_interface("OpenXR")
		if predicted > 0: _adopt_reference_mode(xr.get_play_area_mode())
		if not reference_mode_ready: return
		var space_type: int = {XRInterface.XR_PLAY_AREA_SITTING: 2, XRInterface.XR_PLAY_AREA_STAGE: 3, XRInterface.XR_PLAY_AREA_ROOMSCALE: 1000426000}.get(xr.get_play_area_mode(), 0)
		var changes: Array = pose_sync.take_due_changes(predicted, space_type)
		_apply_due_reference_changes(changes, lost, space_type)
	var reference := origin.global_transform * XRServer.get_reference_frame()
	if not reference.is_equal_approx(placement_reference):
		placement_reference = reference
		_unknown_reference_change()

func _placement_session_state() -> int:
	var xr := XRServer.find_interface("OpenXR")
	return xr.get_session_state() if xr else 0

func _try_recenter() -> void:
	if xr_active and not reference_mode_ready: return
	if recenter_deadline_msec > 0 and Time.get_ticks_msec() > recenter_deadline_msec:
		placement_pending = false
		recenter_deadline_msec = 0
		return # Never replay an old button press in a later viewing direction.
	var head_transform := camera.global_transform
	if xr_active:
		var head: XRPositionalTracker = XRServer.get_tracker("head")
		var pose: XRPose = head.get_pose("default") if head else null
		if (_placement_session_state() != OpenXRInterface.SESSION_STATE_FOCUSED and not (OS.get_environment("FRAME_CINEMA_UNIFIED_UI") == "1" and _placement_session_state() == OpenXRInterface.SESSION_STATE_VISIBLE)) or pose == null or not pose.has_tracking_data or pose.tracking_confidence != XRPose.XR_TRACKING_CONFIDENCE_HIGH:
			return
		# The camera can still contain the previous reference-frame transform.
		# Use the exact adjusted tracker pose also sent to the native panel.
		head_transform = origin.global_transform * pose.get_adjusted_transform()
	var forward := -head_transform.basis.z
	forward.y = 0
	var yaw := atan2(-forward.x, -forward.z) if forward.length_squared() > 0.0001 else seat.global_rotation.y
	_commit_seat(Transform3D(Basis(Vector3.UP, yaw), head_transform.origin - Vector3.UP * 1.65))

func _commit_seat(transform: Transform3D) -> void:
	seat.global_transform = transform
	var yaw := seat.global_rotation.y
	if room:
		room.refresh_transform()
		_follow_room_screen()
	else:
		world.environment.sky_rotation = Vector3(0, yaw, 0)
	placed = true
	placement_pending = false
	recenter_deadline_msec = 0
	recenter_request = maxi(recenter_request + 1, Time.get_ticks_usec())
	placement_dirty = true

func _cycle_screen() -> void:
	_set_screen_width(4.2 if screen_width < 4.0 else (5.4 if screen_width < 5.0 else 3.2))

func _toggle_picture_fit() -> void:
	fit_picture = not fit_picture
	_save()
	_render_ui.call_deferred("room")

func _stereo_notice() -> String:
	if _effective_stereo_mode() == 0 or not focused_view or not stereo_controller.allowed or ipc.is_empty():
		return ""
	var path := ipc.path_join("stereo-status.json")
	if not FileAccess.file_exists(path): return ""
	var state: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not state is Dictionary or state.get("scene_session") != placement_session or state.get("source_session") != stereo_controller.source: return ""
	var stamp := float(state.get("updated", 0.0))
	if not is_finite(stamp) or absf(Time.get_unix_time_from_system() - stamp) > 1.0: return ""
	if state.get("failed") == true: return "3D unavailable · Showing 2D"
	if state.get("budget_limited") == true: return "3D paused for smooth playback · Try ambient light Off"
	return ""

func _set_stereo_mode(value: int) -> void:
	if not _dark_room() and value != 0: return
	stereo_mode = clampi(value, 0, 3)
	_save()
	_render_ui.call_deferred("more")

func _presentation_tick(delta: float) -> void:
	var armed := fit_picture and not library_open and not source_pending and not browser_keyboard
	var enabled := armed and focused_view
	fit_poll += delta
	if (armed or stereo_mode > 0 or _alpine_room()) and fit_poll >= 0.08:
		fit_poll = 0.0
		fit_media = {}
		var path := ipc.path_join("media-status.json")
		if not ipc.is_empty() and FileAccess.file_exists(path):
			fit_media = _status_dictionary(FileAccess.get_file_as_string(path))
	var sample: Dictionary = ambient.fit_sample
	var fresh: bool = ambient.available and _fit_telemetry_fresh(fit_media, sample)
	fit_media["fit_identity"] = str(fit_media.get("player_generation", "")) + ":" + str(sample.get("source_session", "")) + ":" + str(sample.get("window", 0)) + ":" + str(sample.get("viewport", []))
	# The pointer brings up the player's own controls over the bars: while the
	# controllers are in use, nothing in the bars counts as picture content.
	var overlay: bool = viewing_idle != null and not viewing_idle.hidden
	picture_fit.update(delta, enabled, fit_media, sample, fresh, overlay)
	if picture_fit.reason != last_fit_reason or picture_fit.identity != last_fit_identity:
		# Why the crop changed: the player's eligibility check, the sampler's
		# measured bounds and whether the title identity changed.
		frame_pacing.note("fit", {"reason": picture_fit.reason, "top": snappedf(picture_fit.target, 0.001), "releases": picture_fit.releases,
			"enabled": enabled, "overlay": overlay, "fresh": fresh, "check": str(fit_media.get("fit_check", "")),
			"sample_top": sample.get("fit_top", -1), "sample_safe": sample.get("fit_safe_top", -1), "dark": sample.get("fit_dark", false),
			"identity_changed": picture_fit.identity != last_fit_identity})
		last_fit_reason = picture_fit.reason
		last_fit_identity = picture_fit.identity
	if preview:
		picture_top = picture_fit.top
	stereo_controller.update(fit_media, placement_session, _dark_room() and focused_view and not library_open and not source_pending and not browser_keyboard, _effective_stereo_mode(), picture_top, Time.get_unix_time_from_system())

func _effective_stereo_mode() -> int:
	# Keep the user's chosen strength for their next Dark Room session, while
	# explicitly disabling inference and presentation in every other room.
	return stereo_mode if _dark_room() else 0

func _fit_telemetry_fresh(media: Dictionary, sample: Dictionary) -> bool:
	var window: Variant = sample.get("window")
	if not (window is int or window is float) or not is_finite(float(window)) or float(window) < 1 or float(window) != floorf(float(window)):
		return false
	return _fresh_status(media, 1.0) and _fresh_status(sample, 0.5) and media.get("scene_session") == placement_session and media.get("source_session") == sample.get("source_session") and media.get("fit_viewport") == sample.get("viewport") and not str(media.get("player_generation", "")).is_empty()

func _write_presentation() -> void:
	if ipc.is_empty() or placement_session.is_empty():
		return
	var show: bool = not library_open
	var interactive: bool = show and ui.page not in ["room", "more"] and not focused_view and not viewing_idle.hidden and picture_top < 0.0001
	var file := FileAccess.open(ipc.path_join("presentation.tmp"), FileAccess.WRITE)
	if file:
		file.store_string("FCPR1 %s %.6f %d %d %.7f" % [placement_session, Time.get_unix_time_from_system(), int(show), int(interactive), picture_fit.top])
		file.close()
		DirAccess.rename_absolute(ipc.path_join("presentation.tmp"), ipc.path_join("presentation.txt"))
	var stereo_file := FileAccess.open(ipc.path_join("stereo-control.tmp"), FileAccess.WRITE)
	if stereo_file:
		stereo_file.store_string(stereo_controller.packet(placement_session, _effective_stereo_mode(), Time.get_unix_time_from_system()))
		stereo_file.close()
		DirAccess.rename_absolute(ipc.path_join("stereo-control.tmp"), ipc.path_join("stereo-control.txt"))

func _ui_size() -> Vector2:
	return ui_viewport.get_visible_rect().size

# Alpine: the giant screen stands on the far shore. Its lower edge sits just
# under the horizon (the 0.4.43 layout, which reads far away), at the same
# angular size as the other rooms, so the centre rises. "Lower" drops the
# lower edge a further 3 degrees. The lake reflects it floating far out.
const ALPINE_BOTTOM_DEG := [3.0, 6.0]
const ALPINE_HEIGHT_NAMES := ["Far shore", "Lower"]
var alpine_height := 0

func _screen_center() -> Vector3:
	if not _alpine_room():
		return Vector3(0, 2.1, -4.5)
	# The upright screen's half-height grows with its distance from the eye:
	# solve y - t*sqrt(y^2 + D^2) = -D*tan(bottom) for the centre height y.
	var t := screen_width * 9.0 / 32.0 / Vector3(0, 0.45, -4.5).length()
	var target := -3600.0 * tan(deg_to_rad(ALPINE_BOTTOM_DEG[alpine_height]))
	var y := 3600.0 * tan(atan(t) - deg_to_rad(ALPINE_BOTTOM_DEG[alpine_height]))
	for i in 8:
		y = target + t * sqrt(y * y + 3600.0 * 3600.0)
	return Vector3(0, 1.65 + y, -3600)

func _set_alpine_height(value: int) -> void:
	if value < 0 or value >= ALPINE_BOTTOM_DEG.size(): return
	if value == alpine_height:
		ui.refresh_settings()
		return
	alpine_height = value
	if _alpine_room():
		_follow_room_screen()
		recenter_request += 1
		_position_dock()
		placement_dirty = true
	ui.refresh_settings()
	_save()

# Scene antialiasing. Only the 3D room is affected: the video and menus are
# compositor overlays. 4x MSAA cost Coast ~7-10 ms at 2160 px per eye (Turnip
# bins the multisampled targets in many small tiles); 2x costs about as much
# as FXAA there (0.4.45, on head). SMAA was removed: in XR on Godot 4.7.2 Mobile
# its output stayed head-locked.
enum { AA_MSAA4, AA_MSAA2, AA_FXAA }
const AA_NAMES := ["MSAA 4×", "MSAA 2×", "FXAA"]
var antialiasing := AA_MSAA2

func _apply_antialiasing() -> void:
	var viewport := get_viewport()
	viewport.msaa_3d = [Viewport.MSAA_4X, Viewport.MSAA_2X, Viewport.MSAA_DISABLED][antialiasing]
	viewport.screen_space_aa = [Viewport.SCREEN_SPACE_AA_DISABLED, Viewport.SCREEN_SPACE_AA_DISABLED, Viewport.SCREEN_SPACE_AA_FXAA][antialiasing]

# Foveated rendering, 3D room only (the browser video and menus are separate
# compositor overlays and stay at full resolution). Steam starts this app with
# Valve's FDM injection layers (VK_LAYER_VALVE_fdm_injection plus an implicit
# OpenXR API layer). With Godot's own XR_FB_foveation also active (0.4.45,
# 0.4.47) the density map was applied twice and the periphery warped on head
# turns. Two single-owner modes, chosen here and applied by start.sh at launch:
# - Eye · Godot: Godot's own density map (VRS_XR) steered by eye gaze
#   (XR_EXT_eye_gaze_interaction, action eye_gaze_pose). No XR_FB_foveation
#   swapchain: with it SteamVR's compositor treated frames as foveated and the
#   periphery still warped (0.4.51). start.sh keeps Valve's layers out.
# - Eye · SteamVR: Godot's foveation stays off; start.sh sets FDM_DEBUG so
#   Valve's layer foveates (eye-tracked) by itself.
# Fail safe: each launch writes Off first and re-arms after 5 s focused.
enum { FOVEATION_OFF, FOVEATION_GODOT, FOVEATION_STEAMVR }
const FOVEATION_NAMES := ["Off", "Eye · Godot", "Eye · SteamVR"]
const FOVEATION_LAUNCH_KEYS := ["off", "godot", "steamvr"]
const FOVEATION_OVERRIDE := "user://xr-foveation.cfg"
const FOVEATION_LAUNCH := "user://foveation-launch"
var foveation := FOVEATION_OFF

func _runtime_foveation() -> bool:
	return int(ProjectSettings.get_setting("xr/openxr/foveation_level", 0)) > 0

# The mode this process was actually started with (start.sh sets the env).
func _launched_foveation() -> int:
	if OS.get_environment("DISABLE_VULKAN_FDM_INJECTION_LAYER") == "1":
		return FOVEATION_GODOT
	if OS.get_environment("FDM_DEBUG").contains("enable"):
		return FOVEATION_STEAMVR
	return FOVEATION_OFF

func _apply_foveation() -> void:
	var xr := XRServer.find_interface("OpenXR")
	if not xr_active or xr == null:
		return
	var godot := foveation == FOVEATION_GODOT and _launched_foveation() == FOVEATION_GODOT
	get_viewport().vrs_mode = Viewport.VRS_XR if godot else Viewport.VRS_DISABLED
	# Full density inside ~22% of the view around the gaze, falling off outside.
	xr.vrs_min_radius = 22.0
	xr.vrs_strength = 1.0
	if xr.is_foveation_supported() and _runtime_foveation():
		xr.foveation_level = 0

func _write_foveation_override(armed: bool = true) -> void:
	# start.sh derives user://xr-foveation.cfg from this before the engine starts.
	var mode := foveation if armed else FOVEATION_OFF
	var launch := FileAccess.open(FOVEATION_LAUNCH, FileAccess.WRITE)
	if launch:
		launch.store_string(FOVEATION_LAUNCH_KEYS[mode] + "\n")
		launch.close()

var foveation_healthy_seconds := 0.0

func _confirm_foveation(delta: float) -> void:
	if _launched_foveation() == FOVEATION_OFF or foveation_healthy_seconds < 0.0:
		return
	if _placement_session_state() == OpenXRInterface.SESSION_STATE_FOCUSED:
		foveation_healthy_seconds += delta
	if foveation_healthy_seconds > 5.0:
		foveation_healthy_seconds = -1.0
		_write_foveation_override()

func _gaze_tracking() -> bool:
	var tracker := XRServer.get_tracker("/user/eyes_ext") as XRPositionalTracker
	var pose: XRPose = tracker.get_pose("eye_gaze_pose") if tracker else null
	return pose != null and pose.has_tracking_data

func _foveation_pending() -> bool:
	return foveation != _launched_foveation()

func _set_foveation(value: int) -> void:
	if value < 0 or value >= FOVEATION_NAMES.size(): return
	foveation = value
	_write_foveation_override()
	_apply_foveation()
	_render_ui.call_deferred("more")
	_save()

func _set_antialiasing(value: int) -> void:
	if value < 0 or value >= AA_NAMES.size(): return
	antialiasing = value
	_apply_antialiasing()
	_render_ui.call_deferred("more")
	_save()

# The lake reflects an equivalent screen scaled about the eye until its lower
# edge floats just above the water: the reflection then hugs the screen far out.
func _alpine_reflection_screen() -> Array:
	var eye := Vector3(0, 1.65, 0)
	var center := _screen_center()
	var width := _display_screen_width()
	var bottom := center.y - eye.y - width * 9.0 / 32.0
	var water := -1280.0 - eye.y
	if room != null and is_instance_valid(room.contents) and room.contents.get("metadata") is Dictionary:
		water = float(room.contents.metadata.get("water_height", -1280.0)) - eye.y
	var scale := maxf(1.0, water * 0.985 / bottom) if bottom < 0.0 else 1.0
	return [eye + (center - eye) * scale, width * scale]

func _alpine_room() -> bool:
	return environment_index == preload("res://cinema_rooms.gd").ALPINE

func _starship_room() -> bool:
	return environment_index == preload("res://cinema_rooms.gd").STARSHIP

func _display_screen_width() -> float:
	# Alpine's giant screen subtends exactly the angle of the same size in the
	# other rooms: scale by the ratio of seated-eye-to-centre distances.
	if not _alpine_room():
		return screen_width
	var eye := Vector3(0, 1.65, 0)
	return screen_width * (_screen_center() - eye).length() / (Vector3(0, 2.1, -4.5) - eye).length()

func _browser_reach() -> float:
	return 5600.0 if _alpine_room() else BROWSER_REACH_METRES

func _effective_ambient_mode() -> int:
	return 0 if _alpine_room() else ambient_mode

# 72 Hz leaves a 13.9 ms frame for the scenes; 90 Hz (11.1 ms) made SteamVR
# halve to 45 fps with judder. Applies only when the runtime offers 72 Hz.
const PREFERRED_REFRESH_HZ := 72.0
var display_refresh_hz := 0.0
var display_refresh_available: Array = []

func _prefer_refresh_rate() -> void:
	var xr := XRServer.find_interface("OpenXR")
	if xr == null or not xr.is_initialized() or not xr.has_method("get_available_display_refresh_rates"):
		return
	for rate in xr.get_available_display_refresh_rates():
		if absf(float(rate) - PREFERRED_REFRESH_HZ) < 0.5:
			xr.display_refresh_rate = float(rate)
			break
	display_refresh_available = xr.get_available_display_refresh_rates()
	display_refresh_hz = float(xr.display_refresh_rate)
	frame_pacing.refresh_hz = display_refresh_hz if display_refresh_hz > 0.0 else 90.0

# Alpine far-limit debug (Environment console): overlay distance and size
# for panel_host via IPC. Not saved; every launch starts at 600 m, 100%.
var debug_overlay_distance := 600.0
var debug_overlay_size := 1.0

func _set_debug_overlay(distance: float, size: float) -> void:
	debug_overlay_distance = distance
	debug_overlay_size = size
	_write_overlay_debug()
	_render_ui.call_deferred("room")

func _write_overlay_debug() -> void:
	if ipc.is_empty():
		return
	var file := FileAccess.open(ipc.path_join("overlay-debug.tmp"), FileAccess.WRITE)
	if file:
		file.store_string("%.1f %.3f %.3f" % [debug_overlay_distance, debug_overlay_size, _screen_center().y - 1.65 if _alpine_room() else 0.45 * 3600.0 / 104.0])
		file.close()
		DirAccess.rename_absolute(ipc.path_join("overlay-debug.tmp"), ipc.path_join("overlay-debug.txt"))

# Adaptive render scale: hold the 3D scene inside the frame budget so SteamVR
# does not halve the rate (judder on head turns). Only the scene's resolution
# changes; the video and menus are full-resolution compositor overlays.
const RENDER_SCALE_MIN := 0.62
var render_scale := 1.0
var render_scale_samples: Array[float] = []
var render_scale_hold := 0.0

func _govern_render_scale(delta: float) -> void:
	if not xr_active:
		return
	var gpu := _scene_gpu_ms()
	if gpu <= 0.0:
		return
	render_scale_samples.append(gpu)
	render_scale_hold -= delta
	if render_scale_samples.size() < 45 or render_scale_hold > 0.0:
		return
	render_scale_samples.sort()
	var median: float = render_scale_samples[render_scale_samples.size() / 2]
	render_scale_samples.clear()
	# Leave ~14% of the refresh interval for SteamVR's compositor and overlays.
	var budget := 1000.0 / maxf(display_refresh_hz if display_refresh_hz > 0.0 else 90.0, 60.0) * 0.86
	var next := render_scale
	if median > budget:
		next = render_scale * sqrt(budget / median) * 0.97
	elif median < budget * 0.72:
		next = render_scale * 1.05
	next = clampf(snappedf(next, 0.02), RENDER_SCALE_MIN, 1.0)
	if not is_equal_approx(next, render_scale):
		render_scale = next
		get_viewport().scaling_3d_mode = Viewport.SCALING_3D_MODE_BILINEAR
		get_viewport().scaling_3d_scale = render_scale
		render_scale_hold = 1.5

# Room profiler (debug): scene GPU cost with each part removed in turn.
var profiling := false

func _profile_sample() -> Dictionary:
	for i in 45:
		await get_tree().process_frame
	var samples: Array[float] = []
	for i in 90:
		await get_tree().process_frame
		samples.append(_scene_gpu_ms())
	samples.sort()
	return {"median": snappedf(samples[45], 0.01), "p90": snappedf(samples[81], 0.01)}

func _profile_room() -> void:
	if profiling or room == null or not is_instance_valid(room.contents) or ipc.is_empty():
		return
	profiling = true
	_render_ui.call_deferred("more")
	# The Observation Deck is profiled in four room poses about the seat (the head stays
	# put; the room turns so the canopy, deck or side faces it), each with its own
	# variant steps. Every other room keeps the single forward pose and report format.
	var poses := [["front", Basis.IDENTITY]]
	if environment_index == preload("res://cinema_rooms.gd").STARSHIP:
		poses = [["front", Basis.IDENTITY], ["up", Basis(Vector3.RIGHT, deg_to_rad(-70.0))],
			["down", Basis(Vector3.RIGHT, deg_to_rad(35.0))], ["left", Basis(Vector3.UP, deg_to_rad(-90.0))]]
	var room_transform: Transform3D = room.transform
	var pivot := Vector3(0, 1.65, 0)
	var results := {}
	var msaa := get_viewport().msaa_3d
	var chosen := antialiasing
	for pose in poses:
		if poses.size() > 1:
			var turn: Basis = pose[1]
			room.transform = Transform3D(turn, pivot - turn * pivot) * room_transform
			room.refresh_transform()
		var steps := {}
		var groups := {}
		for node in room.contents.find_children("*", "GeometryInstance3D", true, false):
			if not node.visible:
				continue
			var material: Variant = node.material_override
			var key := "default"
			if material is ShaderMaterial and material.shader:
				key = material.shader.resource_path.get_file()
			elif material != null:
				key = material.get_class()
			if not groups.has(key):
				groups[key] = []
			groups[key].append(node)
		steps["baseline"] = await _profile_sample()
		for key in groups:
			for node in groups[key]:
				node.visible = false
			steps["without " + key + " (%d)" % groups[key].size()] = await _profile_sample()
			for node in groups[key]:
				node.visible = true
		var background := world.environment.background_mode
		world.environment.background_mode = Environment.BG_COLOR
		steps["without sky"] = await _profile_sample()
		world.environment.background_mode = background
		if world.environment.glow_enabled:
			world.environment.glow_enabled = false
			steps["without environment glow"] = await _profile_sample()
			world.environment.glow_enabled = true
		for mode in AA_NAMES.size():
			if mode == chosen: continue
			antialiasing = mode
			_apply_antialiasing()
			steps["aa " + AA_NAMES[mode]] = await _profile_sample()
		get_viewport().msaa_3d = Viewport.MSAA_DISABLED
		get_viewport().screen_space_aa = Viewport.SCREEN_SPACE_AA_DISABLED
		steps["aa off"] = await _profile_sample()
		antialiasing = chosen
		_apply_antialiasing()
		# Only Godot's own foveation can be switched within a session.
		if _launched_foveation() == FOVEATION_GODOT:
			var chosen_foveation := foveation
			foveation = FOVEATION_OFF if chosen_foveation == FOVEATION_GODOT else FOVEATION_GODOT
			_apply_foveation()
			steps["foveation " + FOVEATION_NAMES[foveation]] = await _profile_sample()
			foveation = chosen_foveation
			_apply_foveation()
		if ambient.visible:
			# Hiding the node alone measures nothing: the next tick shows it again and the
			# lights and the room's movie light stay on. Only tick() can hold all of it off.
			ambient.profile_glow_off = true
			steps["without glow"] = await _profile_sample()
			ambient.profile_glow_off = false
		# Room-defined variants (Observation Deck: deck as hull, field off, movie light off,
		# halos hidden, stars hidden), each restored before the next.
		if room.contents.has_method("profile_variants"):
			for variant in room.contents.profile_variants():
				room.contents.profile_variant(variant, true)
				steps[variant] = await _profile_sample()
				room.contents.profile_variant(variant, false)
		steps["baseline again"] = await _profile_sample()
		results[pose[0]] = steps
	if poses.size() > 1:
		room.transform = room_transform
		room.refresh_transform()
	var report := {"room": ENVIRONMENTS[environment_index], "time": Time.get_unix_time_from_system(),
		"refresh_hz": display_refresh_hz, "msaa": msaa, "antialiasing": AA_NAMES[chosen], "foveation": FOVEATION_NAMES[_launched_foveation()]}
	if poses.size() == 1:
		report["steps"] = results["front"]
	else:
		var pose_info := {}
		for pose in poses:
			var turn: Basis = pose[1]
			pose_info[pose[0]] = {"pitch_deg": snappedf(rad_to_deg(turn.get_euler().x), 0.1), "yaw_deg": snappedf(rad_to_deg(turn.get_euler().y), 0.1)}
		report["poses"] = pose_info
		report["valve_fdm"] = _launched_foveation() == FOVEATION_STEAMVR
		report["launched_foveation"] = _launched_foveation()
		report["ambient"] = "Cinema, mid-grey palette (forced while profiling)"
		report["steps"] = results
	var file := FileAccess.open(ipc.path_join("profile-%s.json" % ENVIRONMENTS[environment_index]), FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(report, "  "))
		file.close()
	profiling = false
	_render_ui.call_deferred("more")

var written_center_height := -1.0e9

func _sync_alpine_height() -> void:
	var height := _screen_center().y - 1.65
	if absf(height - written_center_height) > 0.01:
		written_center_height = height
		_write_overlay_debug()

func _follow_room_screen() -> void:
	# Room-owned surrounds follow the same seat-local anchor as the native
	# video surface. Recenter only changes the shared parent transform.
	if room != null and is_instance_valid(room.contents) and room.contents.has_method("follow_screen"):
		room.contents.follow_screen(_screen_center(), _display_screen_width())

func _lake_reflection_wanted() -> bool:
	if room == null or not is_instance_valid(room.contents) or room.contents.get("reflects_screen") == false: return false
	return _alpine_room() and focused_view and not library_open and not source_pending and not browser_keyboard and panel_fresh and panel_aligned and ambient._scene_visible() and _fresh_status(fit_media, 0.5) and fit_media.get("scene_session") == placement_session and fit_media.get("fit_eligible") == true and fit_media.get("seeking") == false

func _dark_room() -> bool:
	return environment_index == preload("res://cinema_rooms.gd").DARK_ROOM

func _position_dock() -> void:
	dock.rotation = Vector3.ZERO
	if ui.page in ["room", "more"]:
		# A tilted seated console below the largest screen's lower sightline.
		# Its lower edge clears the ground; the same transform drives picking,
		# the XR composition layer and the inspection mesh.
		dock.mesh.size = _ui_size() * (2.15 / 1600.0)
		dock.position = Vector3(0, 0.67, -1.65)
		dock.rotation_degrees.x = -55.0
		if ui.composition_layer:
			ui.composition_layer.quad_size = dock.mesh.size
		return
	if library_open:
		dock.mesh.size = Vector2(4.2, 4.2 * _ui_size().y / 1600.0)
		dock.position = Vector3(0, 2.1, -4.5)
		if ui.composition_layer:
			ui.composition_layer.quad_size = dock.mesh.size
		return
	# Keep the same readable angular size at a nearer, higher seated position.
	# The top stays below the largest full browser; the bottom clears the floor.
	dock.mesh.size = _ui_size() * (3.0 / 1600.0)
	# Keep controls nearby below the picture, with enough clearance above the
	# snowy seat even when the distant picture is centered on a forward gaze.
	var largest := _display_screen_width() if _alpine_room() else 5.4
	var bottom_slope := (_screen_center().y - 1.65 - largest * 9.0 / 32.0) / -_screen_center().z
	dock.position = Vector3(0, 1.65 + bottom_slope * 2.5 - 0.09 - dock.mesh.size.y / 2.0, -2.5)
	if _alpine_room(): dock.position.y = maxf(dock.position.y,0.65)
	if ui.composition_layer:
		ui.composition_layer.quad_size = dock.mesh.size

func _browser_command(command: int) -> void:
	if ipc.is_empty():
		return
	if command in [1, 2]:
		playback_health.reset()
		playback_message = ""
	command_sequence = maxi(command_sequence + 1, Time.get_ticks_usec())
	DirAccess.make_dir_recursive_absolute(ipc.path_join("input"))
	var name := "input/%020d" % command_sequence
	var file := FileAccess.open(ipc.path_join(name + ".tmp"), FileAccess.WRITE)
	if file:
		file.store_string("%d %d %.6f" % [command_sequence, command, Time.get_unix_time_from_system() if inspection_input and command in [1, 2] else 0.0])
		file.close()
		DirAccess.rename_absolute(ipc.path_join(name + ".tmp"), ipc.path_join(name + ".nav"))
		if command in [1, 2] and media_state.get("available", false):
			media_request = command_sequence
			media_request_navigation = true
			media_requested_at = Time.get_ticks_msec()
			media_notice = ""

func _keyboard() -> void:
	if focused_view:
		_show_controls()
	if ui.page in ["room", "more"]:
		return
	_browser_command(4)

func _write_placement() -> void:
	if ipc.is_empty() or placement_session.is_empty():
		return
	_write_controller_focus()
	placement_sequence += 1
	var head: XRPositionalTracker = XRServer.get_tracker("head")
	var pose: XRPose = head.get_pose("default") if head else null
	var tracked := placed and not placement_pending and xr_active and reference_mode_ready and pose != null
	tracked = tracked and pose.has_tracking_data and pose.tracking_confidence == XRPose.XR_TRACKING_CONFIDENCE_HIGH if pose else false
	tracked = tracked and _placement_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED]
	var screen := seat.global_transform * Transform3D(Basis.IDENTITY, _screen_center())
	pose_time_ns = 0
	if pose_sync and xr_active:
		var api: Object = pose_sync.get_openxr_api()
		var timing: Dictionary = pose_sync.convert_pose_time(api.get_predicted_display_time())
		if timing.get("available", false):
			pose_time_ns = timing.target_ns
	var head_transform := origin.global_transform * pose.get_adjusted_transform() if pose else camera.global_transform
	var record := "FCPL2 %s %d %d %d %.6f %d %.6f %.6f %.6f %d" % [placement_session,
		placement_generation, recenter_request, placement_sequence, Time.get_unix_time_from_system(),
		1 if tracked else 0, _display_screen_width(), pose.linear_velocity.length() if pose else 0.0,
		pose.angular_velocity.length() if pose else 0.0, pose_time_ns]
	for transform in [head_transform, screen]:
		for row in range(3):
			record += " %.9f %.9f %.9f %.9f" % [transform.basis.x[row], transform.basis.y[row], transform.basis.z[row], transform.origin[row]]
	var file := FileAccess.open(ipc.path_join("placement.tmp"), FileAccess.WRITE)
	if file:
		file.store_string(record)
		file.close()
		DirAccess.rename_absolute(ipc.path_join("placement.tmp"), ipc.path_join("placement.txt"))

func _write_controller_focus() -> void:
	# Controller-only lease: VISIBLE remains valid for video placement, but
	# controllers belong only to the focused application.
	var file := FileAccess.open(ipc.path_join("controller-focus.tmp"), FileAccess.WRITE)
	if file:
		file.store_string("FCCF1 %s %d %.6f %d" % [placement_session, OS.get_process_id(), Time.get_unix_time_from_system(), 1 if xr_active and _input_available() and not viewing_idle.hidden else 0])
		file.close()
		DirAccess.rename_absolute(ipc.path_join("controller-focus.tmp"), ipc.path_join("controller-focus.txt"))

func _select_source(mode: String, restart: bool = false) -> void:
	source_mode = mode
	_source_request({"mode": mode, "service": selected_service, "restart": restart})

func _hit(from: Vector3, direction: Vector3) -> Variant:
	var local_from := dock.to_local(from)
	var local_direction := dock.global_basis.inverse() * direction
	if absf(local_direction.z) < 0.0001:
		return null
	var distance := -local_from.z / local_direction.z
	if distance <= 0:
		return null
	var position_on_plane := local_from + local_direction * distance
	var size: Vector2 = dock.mesh.size
	var uv := Vector2(position_on_plane.x / size.x + 0.5, 0.5 - position_on_plane.y / size.y)
	if uv.x < 0 or uv.y < 0 or uv.x > 1 or uv.y > 1:
		return null
	return uv * _ui_size()

func _keyboard_hit(from: Vector3, direction: Vector3) -> bool:
	if not browser_keyboard:
		return false
	var local_from := seat.to_local(from) - Vector3(0, 1.05, -1.7)
	var local_direction := seat.global_basis.inverse() * direction
	if absf(local_direction.z) < 0.0001:
		return false
	var distance := -local_from.z / local_direction.z
	var point := local_from + local_direction * distance
	return distance > 0 and absf(point.x) <= 1.0 and absf(point.y) <= 540.0 / 5600.0

func _controller_dock_hit(controller: XRController3D) -> Variant:
	if not dock.visible or not controller.get_has_tracking_data() or not _input_available():
		return null
	var direction := -controller.global_basis.z
	if _keyboard_hit(controller.global_position, direction):
		return null
	return _hit(controller.global_position, direction)

func _hover_dock(hit: Variant) -> void:
	if OS.get_environment("FRAME_CINEMA_UNIFIED_UI") == "1":
		return
	var inside := hit != null and dock.visible
	if inside != mouse_inside:
		if inside:
			ui_viewport.notify_mouse_entered()
		else:
			ui_viewport.notify_mouse_exited()
		mouse_inside = inside
	var next_position: Vector2 = hit if inside else Vector2(-1, -1)
	var motion := InputEventMouseMotion.new()
	motion.position = next_position
	motion.global_position = next_position
	motion.relative = next_position - mouse_position
	motion.button_mask = MOUSE_BUTTON_MASK_LEFT if pointer_down else 0
	mouse_position = next_position
	ui_viewport.push_input(motion, true)
	dock_cursor.visible = inside
	dock_cursor.position = next_position - dock_cursor.size / 2

func _dock_click(hit: Variant, pressed: bool) -> void:
	_hover_dock(hit)
	pointer_down = pressed
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = pressed
	click.button_mask = MOUSE_BUTTON_MASK_LEFT if pressed else 0
	click.position = mouse_position
	click.global_position = mouse_position
	ui_viewport.push_input(click, true)

func _controller_pressed(action: StringName, controller: XRController3D) -> void:
	if _input_available(): _note_activity()
	input_counts.buttons += 1
	button_actions[action] = int(button_actions.get(action, 0)) + 1
	if action == "trigger_click":
		_poll_trigger(controller)
		return
	# Native overlay actions own shortcuts when Steam owns the pointer.
	if OS.get_environment("FRAME_CINEMA_UNIFIED_UI") == "1":
		return
	if not _input_available():
		return
	if action == "ax_button":
		if controller.tracker == &"left_hand":
			_recenter("left A/X")
		else:
			_cycle_environment()
	elif action == "primary_click":
		_recenter("stick press")
	elif action == "by_button":
		if controller.tracker == &"left_hand":
			_browser_command(1)
		else:
			_toggle_controls()
	elif action == "grip_click":
		_keyboard()

func _controller_released(action: StringName, controller: XRController3D) -> void:
	if action == "trigger_click":
		_poll_trigger(controller)

func _controller_float_changed(action: StringName, _value: float, controller: XRController3D) -> void:
	if action == "trigger":
		# Preserve brief transitions even when both occur before the next draw.
		_poll_trigger(controller)

func _input_available() -> bool:
	if not xr_active:
		return true
	var xr := XRServer.find_interface("OpenXR")
	return xr.get_session_state() == OpenXRInterface.SESSION_STATE_FOCUSED

func _poll_trigger(controller: XRController3D) -> void:
	if OS.get_environment("FRAME_CINEMA_UNIFIED_UI") == "1":
		return
	var was_down: bool = trigger_states.get(controller.tracker, false)
	var threshold := 0.18 if was_down else 0.35
	var available := _input_available() and controller.get_has_tracking_data()
	var held := controller.is_button_pressed("trigger_click") or controller.get_float("trigger") >= 0.18
	if not available:
		trigger_rearm[controller.tracker] = true
	if available and not held:
		trigger_rearm.erase(controller.tracker)
	var down: bool = available and not trigger_rearm.get(controller.tracker, false) and (controller.is_button_pressed("trigger_click") or controller.get_float("trigger") >= threshold)
	if down == was_down:
		return
	trigger_states[controller.tracker] = down
	var hit: Variant = _controller_dock_hit(controller)
	if down:
		if click_owner != null:
			return
		active_pointer = controller
		click_owner = controller
		input_counts.trigger_down += 1
		if focused_view and not browser_keyboard:
			click_target = "wake"
			_show_controls()
			return
		if picture_top >= 0.0001 and hit == null:
			click_target = "wake"
			return
		click_target = "dock" if hit != null else "browser"
		if click_target == "dock":
			input_counts.dock_down += 1
			_dock_click(hit, true)
		else:
			input_counts.browser_down += 1
			_forward_pointer(controller, 1)
	elif click_owner == controller:
		# Release the original target even if the ray left it or tracking was lost.
		if click_target == "dock":
			_dock_click(hit, false)
		elif click_target != "wake":
			_forward_pointer(controller, 2)
		click_owner = null
		click_target = ""

func _pointer_kind(hit: Variant) -> int:
	# Idle controllers also hide panel_host's native beam: kind 7 cancels it.
	if not _input_available() or viewing_idle.hidden: return 7
	return 6 if hit != null else 0

func _forward_pointer(controller: XRController3D, kind: int, limit: float = -1.0) -> void:
	if limit < 0.0: limit = _browser_reach()
	if ipc.is_empty():
		return
	# A ray must use one spatial frame. Rebuilding a past head-relative ray from
	# a newer native HMD pose made a stationary hand jump when the head turned.
	var screen := seat.global_transform * Transform3D(Basis.IDENTITY, _screen_center())
	var relative := screen.affine_inverse() * controller.global_transform if controller else Transform3D.IDENTITY
	var direction := -relative.basis.z
	var sequence := Time.get_ticks_usec()
	var continuous := kind == 0 or kind == 3 or kind == 6 or kind == 7
	var name := "pointer" if continuous else "input/%020d" % sequence
	var file := FileAccess.open(ipc.path_join(name + ".tmp"), FileAccess.WRITE)
	if file:
		file.store_string("%d %d %f %f %f %f %f %f %f %d S2 %s %d %d" % [kind, sequence, relative.origin.x, relative.origin.y, relative.origin.z, direction.x, direction.y, direction.z, limit, int(Time.get_unix_time_from_system() * 1000000), placement_session, placement_generation, recenter_request])
		file.close()
		DirAccess.rename_absolute(ipc.path_join(name + ".tmp"), ipc.path_join(name + (".txt" if continuous else ".evt")))

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_E: _cycle_environment()
			KEY_L: _cycle_light()
			KEY_R: _recenter()
			KEY_1: _select_source("auto")
			KEY_2: _select_source("local")
			KEY_ESCAPE: _quit_recorded("escape_key")
	if not xr_active and event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		var hit: Variant = _hit(camera.project_ray_origin(event.position), camera.project_ray_normal(event.position))
		if hit != null or pointer_down:
			_dock_click(hit, event.pressed)
	if not xr_active and event is InputEventMouseMotion:
		_hover_dock(_hit(camera.project_ray_origin(event.position), camera.project_ray_normal(event.position)))
	if not xr_active and event is InputEventMouseMotion and event.button_mask & MOUSE_BUTTON_MASK_RIGHT:
		camera.rotation.y -= event.relative.x * 0.003
		camera.rotation.x = clampf(camera.rotation.x - event.relative.y * 0.003, -1.2, 1.2)

func _write_report() -> void:
	var controller_status := []
	for controller in controllers:
		var tracker := XRServer.get_tracker(controller.tracker)
		controller_status.append({"hand": controller.tracker, "active": controller.get_is_active(),
			"tracked": controller.get_has_tracking_data(), "profile": tracker.get_tracker_profile() if tracker else ""})
	var xr := XRServer.find_interface("OpenXR")
	var report := {"version": "0.5.19", "engine": Engine.get_version_info().string,
			"os": OS.get_name(), "xr_active": xr_active, "frames": Engine.get_frames_drawn(),
			"session_state": xr.get_session_state() if xr_active else 0,
			"controllers": controller_status, "input_counts": input_counts, "button_actions": button_actions,
			"runtime_models": render_models.get_child_count() if render_models else 0,
			"installed_models": model_fallbacks.size(),
			"controller_foreground": controller_foreground,
			"quality": {"antialiasing": AA_NAMES[antialiasing], "foveation": FOVEATION_NAMES[foveation], "foveation_runtime_enabled": _runtime_foveation(), "foveation_launched": FOVEATION_NAMES[_launched_foveation()], "gaze_tracking": _gaze_tracking(), "fdm_debug": OS.get_environment("FDM_DEBUG"), "vk_layers": OS.get_environment("VK_INSTANCE_LAYERS"), "foveation_eye_tracked_setting": bool(ProjectSettings.get_setting("xr/openxr/foveation_eye_tracked", false)), "eye_gaze_supported": xr.is_eye_gaze_interaction_supported() if xr_active else false, "foveation_supported": xr.is_foveation_supported() if xr_active else false, "foveation_runtime_level": xr.foveation_level if xr_active and xr.is_foveation_supported() else -1, "ui_texture": [ui_viewport.size.x, ui_viewport.size.y], "ui_logical": [_ui_size().x, _ui_size().y], "ui_composition_native": ui.composition_layer.is_natively_supported() if ui.composition_layer else false, "ui_composition_active": ui.composition_layer.layer_viewport != null if ui.composition_layer else false, "scene_msaa": get_viewport().msaa_3d, "eye_target": [xr.get_render_target_size().x, xr.get_render_target_size().y] if xr_active else [], "scaling_3d": get_viewport().scaling_3d_scale, "vrs_mode": get_viewport().vrs_mode},
			"service": selected_service, "library_open": library_open, "ui_page": ui.page, "focus_mode": focused_view,
			"viewing_idle": {"controllers_hidden":viewing_idle.hidden,"timeout_seconds":10,"automatic_focus_entries":automatic_focus_entries},
			"screen_width": screen_width, "physical_screen_width": _display_screen_width(), "display_refresh_hz": display_refresh_hz, "render_scale": render_scale, "display_refresh_available": display_refresh_available, "dock_visible": dock.visible,
			"stereo_mode": _effective_stereo_mode(), "stereo_preference": stereo_mode, "stereo_eligible": stereo_controller.allowed and _dark_room(), "fit_picture": fit_picture, "picture_top": picture_top, "picture_fit_reason": picture_fit.reason, "screen_center": [_screen_center().x, _screen_center().y, _screen_center().z],
			"placed": placed, "placement_pending": placement_pending,
			"placement_generation": placement_generation, "placement_revision": recenter_request,
			"recenter_cause": recenter_cause,
			"seated_reference": seated_reference, "reference_mode_ready": reference_mode_ready, "local_reference_resets": local_reference_resets,
			"play_area_mode": xr.get_play_area_mode() if xr_active else 0,
			"pose_sync": pose_sync.state() if pose_sync else {}, "pose_time_available": pose_time_ns > 0,
			"reference_preserved": reference_preserved, "reference_unknown": reference_unknown,
			"environment": ENVIRONMENTS[environment_index] if environment_index >= 0 else "unavailable", "room": room.metrics(), "ambient": ambient.metrics() if ambient else {},
			"water": _water_render_metrics(),
			"render_timing": {"gpu_ms": _scene_gpu_ms(), "main_gpu_ms": RenderingServer.viewport_get_measured_render_time_gpu(get_viewport().get_viewport_rid()), "reflection_gpu_ms": float(_water_render_metrics().get("reflection_gpu_ms", 0.0)), "cpu_ms": RenderingServer.viewport_get_measured_render_time_cpu(get_viewport().get_viewport_rid()), "fps": Engine.get_frames_per_second()},
			"frame_pacing": frame_pacing.metrics(),
			"netflix_playback_verified": false}
	if OS.get_environment("FRAME_CINEMA_NATIVE_PREVIEW") == "1":
		report["native_preview"] = true
		report["native_ui_revision"] = "sharp-2"
		report["native_ui"] = Engine.get_singleton("FrameNativeUI").state() if Engine.has_singleton("FrameNativeUI") else {}
		report["scene_owner"] = Engine.get_singleton("FrameSceneOwnerBroker").state() if Engine.has_singleton("FrameSceneOwnerBroker") else {}
	var file := FileAccess.open("user://scene-status.json", FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(report))
		file.close()
	if not ipc.is_empty():
		var live := FileAccess.open(ipc.path_join("scene.tmp"), FileAccess.WRITE)
		if live:
			live.store_string(JSON.stringify(report))
			live.close()
			DirAccess.rename_absolute(ipc.path_join("scene.tmp"), ipc.path_join("scene.json"))

func _select_tracked_pointer() -> void:
	if click_owner != null or (active_pointer != null and active_pointer.get_has_tracking_data()):
		return
	for controller in controllers:
		if controller.get_has_tracking_data():
			active_pointer = controller
			return

func _refresh_controller_models() -> void:
	_update_controller_visibility()

func _update_controller_visibility() -> void:
	var tracked := {}
	for side in ["left", "right"]:
		for controller in controllers:
			if str(controller.tracker) == side + "_hand": tracked[side] = controller.get_has_tracking_data()
	runtime_hand_models = preload("res://controller_foreground.gd").sync_models(render_models, model_fallbacks, tracked, controller_foreground, _input_available() and not viewing_idle.hidden)

func _water_render_metrics() -> Dictionary:
	if room != null and is_instance_valid(room.contents) and _alpine_room():
		return room.contents.metrics()
	if room != null and is_instance_valid(room.contents) and environment_index == 4:
		var water: Node = room.contents.get("water_renderer")
		if is_instance_valid(water): return water.metrics()
	return {}

func _scene_gpu_ms() -> float:
	return RenderingServer.viewport_get_measured_render_time_gpu(get_viewport().get_viewport_rid()) + float(_water_render_metrics().get("reflection_gpu_ms", 0.0))

func _tick_ambient(delta: float) -> void:
	ambient.tick(delta)
	if _alpine_room() and room != null and is_instance_valid(room.contents):
		room.contents.update_picture(self,delta)

func _quit_recorded(reason: String) -> void:
	# Content-free diagnostic: distinguish runtime handoff from a scene failure.
	if not ipc.is_empty():
		var file := FileAccess.open(ipc.path_join("exit-reason.tmp"),FileAccess.WRITE)
		if file:
			file.store_string(JSON.stringify({"session":placement_session,"reason":reason,"updated":Time.get_unix_time_from_system(),"environment":ENVIRONMENTS[environment_index]}))
			file.close()
			DirAccess.rename_absolute(ipc.path_join("exit-reason.tmp"),ipc.path_join("exit-reason.json"))
	get_tree().quit()

func _process(delta: float) -> void:
	_sync_alpine_height()
	_confirm_foveation(delta)
	if xr_active and _placement_session_state() in [OpenXRInterface.SESSION_STATE_EXITING, OpenXRInterface.SESSION_STATE_LOSS_PENDING]:
		# Another VR scene or a runtime shutdown ends this XR session. Let the
		# supervisor close owned panels instead of spinning an unusable scene.
		_quit_recorded("xr_runtime_exit" if _placement_session_state() == OpenXRInterface.SESSION_STATE_EXITING else "xr_session_loss")
		return
	_update_reference_space()
	_tick_viewing_idle()
	var timing_rid := get_viewport().get_viewport_rid()
	frame_pacing.record(xr_active and _placement_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED], Time.get_ticks_usec(), _scene_gpu_ms(), RenderingServer.viewport_get_measured_render_time_cpu(timing_rid))
	ui.tick_focus_hint(delta)
	ui.sync_composition()
	if ambient:
		_tick_ambient(delta)
		_presentation_tick(delta)
	elapsed += delta
	panel_poll_tick += delta
	if panel_poll_tick >= 0.05:
		panel_poll_tick = 0.0
		_read_panel_status()
		controller_foreground = preload("res://controller_foreground.gd").read(ipc, placement_session)
	if render_models:
		render_models.visible = _input_available()
	_update_controller_visibility()
	_select_tracked_pointer()
	for controller in controllers:
		_poll_trigger(controller)
		pointer_rays[controller.tracker].visible = not viewing_idle.hidden and not compositor_pointer and controller == active_pointer and controller.get_has_tracking_data() and _input_available()
	if active_pointer and active_pointer.get_has_tracking_data():
		var interactive := _input_available()
		var hit: Variant = _controller_dock_hit(active_pointer)
		_hover_dock(hit)
		var limit := _browser_reach()
		if hit != null:
			var uv: Vector2 = hit / _ui_size()
			var target := dock.to_global(Vector3((uv.x - 0.5) * dock.mesh.size.x, (0.5 - uv.y) * dock.mesh.size.y, 0))
			limit = active_pointer.global_position.distance_to(target)
		if not compositor_pointer:
			var ray: MeshInstance3D = pointer_rays[active_pointer.tracker]
			ray.mesh.height = maxf(limit, 0.01)
			ray.position.z = -limit / 2.0
		_forward_pointer(active_pointer, _pointer_kind(hit), limit)
		scroll_tick += delta
		if scroll_tick > 0.12:
			scroll_tick = 0.0
			var thumb := active_pointer.get_vector2("primary")
			if interactive and hit == null and absf(thumb.y) > 0.5:
				_forward_pointer(active_pointer, 4 if thumb.y > 0 else 5)
	else:
		_hover_dock(null)
		_forward_pointer(null, 3)
	if placement_pending and elapsed > 1.5:
		_try_recenter()
	placement_tick += delta
	if placement_dirty or placement_tick >= 0.04:
		placement_tick = 0.0
		placement_dirty = false
		_write_placement()
		_write_presentation()
	report_tick += delta
	if report_tick > 1.0:
		report_tick = 0.0
		_write_report()
		_refresh_controller_models()
		_update_status()
	if smoke and elapsed > 8:
		smoke = false
		_write_report()
		if preview:
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png("user://scene-preview.png")
		get_tree().quit()

func _read_panel_status() -> void:
	browser_keyboard = false
	compositor_pointer = false
	panel_fresh = false
	panel_aligned = false
	panel_message = ""
	panel_attention = false
	if not ipc.is_empty() and FileAccess.file_exists(ipc.path_join("panel-status.json")):
		var raw := FileAccess.get_file_as_string(ipc.path_join("panel-status.json"))
		if raw != panel_heartbeat:
			panel_heartbeat = raw
			panel_seen = Time.get_ticks_msec()
		var panel_status := _status_dictionary(raw)
		if panel_status is Dictionary:
			var heartbeat: Variant = panel_status.get("heartbeat")
			if not (heartbeat is int or heartbeat is float) or not panel_status.get("window_attached") is bool or Time.get_ticks_msec() - panel_seen >= 2000:
				return
			for key in ["keyboard_visible", "beam_ready", "keyboard_target_ready", "placement_ready"]:
				if panel_status.has(key) and not panel_status[key] is bool:
					return
			var keyboard_error: Variant = panel_status.get("keyboard_error", 0)
			if not (keyboard_error is int or keyboard_error is float):
				return
			panel_fresh = true
			var scroll_count := int(panel_status.get("native_scroll_sent", 0))
			if idle_panel_scroll >= 0 and scroll_count > idle_panel_scroll: _note_activity()
			idle_panel_scroll = scroll_count
			picture_top = clampf(float(panel_status.get("picture_top", 0.0)), 0.0, 0.2)
			if not panel_status.get("placement_ready", true):
				panel_message = "Aligning screen" if pose_sync and pose_sync.state().get("converter_ready", false) else "Aligning screen · Hold your head still briefly"
				panel_attention = true
				return
			panel_aligned = panel_status.get("window_attached", false)
			browser_keyboard = panel_status.get("keyboard_visible", false)
			compositor_pointer = panel_status.get("beam_ready", false)
			panel_message = "Keyboard ready · B or Done to close" if browser_keyboard else ""
			if browser_keyboard and not panel_status.get("keyboard_target_ready", true):
				panel_message = "Select a field to type"
				panel_attention = true
			if int(panel_status.get("keyboard_error", 0)) != 0:
				panel_message = "Keyboard unavailable · Try Keyboard again"
				panel_attention = true
			elif not panel_status.get("window_attached", false):
				panel_message = "Waiting for screen · More → Reopen"
				panel_attention = true

func _status_dictionary(raw: String) -> Dictionary:
	var parser := JSON.new()
	if parser.parse(raw) != OK or not parser.data is Dictionary:
		return {}
	return parser.data

func _fresh_status(value: Dictionary, lifetime: float) -> bool:
	var stamp: Variant = value.get("updated")
	if not (stamp is int or stamp is float):
		return false
	var age := Time.get_unix_time_from_system() - float(stamp)
	return age >= -1.0 and age < lifetime

func _wait_elapsed(reason: String) -> int:
	var now := Time.get_ticks_msec()
	if service_wait_reason != reason or service_wait_since == -1:
		service_wait_reason = reason
		service_wait_since = now
	return now - service_wait_since

func _valid_media_state(state: Dictionary) -> bool:
	if not state.get("available") is bool or not state.get("video") is bool:
		return false
	if state.available and not state.get("page_ready") is bool:
		return false
	for key in ["can_control", "can_seek", "paused", "title_player", "fullscreen", "ended", "seeking", "current_valid"]:
		if state.has(key) and not state[key] is bool:
			return false
	for key in ["width", "height", "current", "playback_rate", "error_code"]:
		if state.has(key) and (not (state[key] is int or state[key] is float) or not is_finite(float(state[key]))):
			return false
	if state.has("player_generation") and not state.player_generation is String:
		return false
	return true

func _quiet_recovery(message: String) -> String:
	recovery_attention = false
	return message

func _recovery_message(parsed: Dictionary, supervisor_fresh: bool) -> String:
	recovery_attention = true
	var now := Time.get_ticks_msec()
	var reconnect := "Reopen"
	if not source_error.is_empty():
		return source_error
	if source_pending:
		service_wait_since = -1
		if now - source_requested_at < 15000:
			return _quiet_recovery("Closing service…" if library_open else "Opening " + _service_name() + "…")
		if not supervisor_fresh:
			return "Cinema not responding · Relaunch from Steam"
		return "Closing stalled · Choose a service to retry" if library_open else "Opening stalled · More → " + reconnect
	if not supervisor_fresh:
		return _quiet_recovery("Waiting for Cinema…") if _wait_elapsed("supervisor") < 5000 else "Cinema not responding · Relaunch from Steam"
	if parsed.get("cleanup_pending", false):
		service_wait_since = -1
		return "Still closing · More → " + reconnect
	if library_open:
		service_wait_since = -1
		return _quiet_recovery("")
	if not parsed.get("panel_running", false):
		service_wait_since = -1
		return "Service closed · More → Reopen"
	if not panel_fresh:
		return _quiet_recovery("Waiting for screen…") if _wait_elapsed("screen") < 10000 else "Screen not responding · More → " + reconnect
	if media_state.is_empty() or not media_state.get("available", false):
		return _quiet_recovery("Connecting to service…") if _wait_elapsed("service") < 10000 else "Service not responding · More → Reopen"
	if not media_state.get("page_ready", false):
		return _quiet_recovery("Loading service…") if _wait_elapsed("loading") < 30000 else "Loading slowly · More → Reload"
	service_wait_since = -1
	recovery_attention = panel_attention
	return panel_message

func _update_status() -> void:
	if ipc.is_empty():
		return
	_read_panel_status()
	if ui.page in ["room", "more", "focus"] and browser_keyboard and _input_available():
		# An earlier dismissal may have arrived while Steam owned input.
		# Keep it dismissed after focus returns; never clear the editor text.
		_browser_command(5)
	var parsed := {}
	if FileAccess.file_exists(ipc.path_join("status.json")):
		parsed = _status_dictionary(FileAccess.get_file_as_string(ipc.path_join("status.json")))
	var supervisor_fresh: bool = _fresh_status(parsed, 5.0) and parsed.get("panel_running") is bool and parsed.get("library") is bool and parsed.get("source") in ["", "local"] and parsed.get("cleanup_pending", false) is bool
	var acknowledged: Variant = parsed.get("request_id")
	if supervisor_fresh and source_pending and (acknowledged is int or acknowledged is float) and int(acknowledged) == source_request:
		source_pending = false
		if parsed.get("cleanup_pending", false):
			# The requested switch did not happen. Retain the previous service's
			# identity and offer recovery instead of showing the wrong app name.
			selected_service = str(parsed.get("service", selected_service))
			library_open = parsed.get("library", false)
			_render_ui.call_deferred("library" if library_open else "player")
	media_state = {}
	var media_path: String = ipc.path_join("media-status.json")
	if supervisor_fresh and panel_fresh and source_error.is_empty() and not source_pending and not parsed.get("cleanup_pending", false) and parsed.get("panel_running", false) and parsed.get("source", "local") == "local" and FileAccess.file_exists(media_path):
		var state := _status_dictionary(FileAccess.get_file_as_string(media_path))
		if _fresh_status(state, 3.0) and _valid_media_state(state):
			media_state = state
	_media_feedback(media_state)
	playback_message = playback_health.observe(media_state, Time.get_ticks_msec())
	for button in media_buttons:
		if is_instance_valid(button):
			button.disabled = not _media_enabled(button.get_meta("media_operation", ""))
	if is_instance_valid(play_button):
		play_button.text = "Play" if media_state.get("paused", true) else "Pause"
		play_button.icon = ui.icon("play" if media_state.get("paused", true) else "pause")
	if is_instance_valid(fullscreen_button):
		fullscreen_button.disabled = not _media_enabled("exit_fullscreen")
	var recovery := _recovery_message(parsed, supervisor_fresh)
	if recovery.is_empty():
		recovery = playback_message
		recovery_attention = playback_health.needs_attention
	if recovery.is_empty():
		var stereo_notice := _stereo_notice()
		if not stereo_notice.is_empty():
			recovery = stereo_notice
			recovery_attention = true
	if ui.page == "player" and ui.has_method("update_loading"):
		ui.update_loading(recovery if not recovery.is_empty() and not recovery_attention and not library_open else "")
	if ui.page == "focus":
		ui.update_focus_notice(recovery if recovery_attention else "")
		return
	if ui.page == "more":
		status_label.text = recovery if not recovery.is_empty() else (media_notice if not media_notice.is_empty() and Time.get_ticks_msec() < media_notice_until else "Use the service's player for captions, audio language and profiles.")
	if ui.page == "room":
		status_label.text = recovery if recovery_attention else ""
		return
	if ui.page == "more":
		return
	if library_open:
		status_label.text = recovery
		return
	if not recovery.is_empty():
		status_label.text = recovery
	elif not media_notice.is_empty() and Time.get_ticks_msec() < media_notice_until:
		status_label.text = media_notice
	else:
		status_label.text = "Stick: scroll  ·  B: controls"
		if media_state.get("title_player", false) and int(media_state.get("width", 0)) > 0 and int(media_state.get("height", 0)) > 0:
			status_label.text = ("Paused" if media_state.get("paused", true) else "Playing") + "  ·  %d × %d  ·  B: controls" % [int(media_state.width), int(media_state.height)]
