extends SceneTree

# Run with --headless --xr-mode off --script test_input.gd -- --preview.
# Synthetic tracker + real Godot GUI; no browser, network or live headset input.
var failures := 0
var activated := 0
var scene: Node3D
var tracker: XRControllerTracker
var controller: XRController3D

func _initialize() -> void:
	call_deferred("run")

func check(condition: bool, label: String) -> void:
	print(("PASS " if condition else "FAIL ") + label)
	if not condition:
		failures += 1

func aim_at(pixel: Vector2) -> void:
	var size: Vector2 = scene.dock.mesh.size
	var uv: Vector2 = pixel / scene._ui_size()
	var target: Vector3 = scene.dock.to_global(Vector3((uv.x - 0.5) * size.x, (0.5 - uv.y) * size.y, 0))
	var start := Vector3(0, 1.65, 0)
	tracker.set_pose("aim", Transform3D(Basis.looking_at(target - start), start), Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_HIGH)

func trigger(value: float, digital: bool = false) -> void:
	tracker.set_input("trigger", value)
	tracker.set_input("trigger_click", digital)
	scene._poll_trigger(controller)

func run() -> void:
	OS.set_environment("FRAME_CINEMA_IPC", "")
	var test_root := OS.get_environment("FRAME_CINEMA_TEST_OUT")
	if test_root.is_empty():
		test_root = OS.get_user_data_dir()
	DirAccess.make_dir_recursive_absolute(test_root)
	scene = load("res://cinema.gd").new()
	scene.preferences_path = test_root.path_join("input-test-settings-%d.cfg" % Time.get_ticks_usec())
	root.add_child(scene)
	scene.set_process(false)
	check(scene.library_open and scene.services.size() == 5, "launch opens native library with five services")
	check(scene.ui_viewport.size.x == 3200 and scene._ui_size().x == 1600, "UI doubles texture density without doubling logical hit targets")
	check(scene.get_viewport().msaa_3d == Viewport.MSAA_2X, "scene enables two-sample edge antialiasing")
	scene.library_open = false
	scene._render_ui("room")
	tracker = XRControllerTracker.new()
	tracker.name = "right_hand"
	XRServer.add_tracker(tracker)
	controller = scene._build_controller("right")
	await process_frame
	await process_frame
	var target: Vector2 = scene.screen_button.get_global_rect().get_center()
	check(Rect2(Vector2.ZERO, scene._ui_size()).has_point(target), "screen-size button fits viewport")
	var controls_fit := true
	for node in scene.ui_viewport.find_children("*", "Button", true, false):
		controls_fit = controls_fit and Rect2(Vector2.ZERO, scene._ui_size()).encloses(node.get_global_rect())
	check(controls_fit, "all navigation and settings buttons fit inside the dock")
	scene.screen_button.pressed.connect(func(): activated += 1)
	var room_placement: Transform3D = scene.dock.global_transform
	aim_at(target)
	trigger(0.8)
	check(scene.pointer_down, "analog trigger starts GUI press")
	trigger(0.45)
	check(scene.pointer_down, "hysteresis retains press")
	trigger(0.0)
	check(activated == 1 and is_equal_approx(scene.screen_width, 5.4), "release activates actual screen-size button once")
	trigger(0.8, true)
	trigger(0.9, true)
	trigger(0.0)
	check(activated == 2, "digital and analog signals do not double-click")
	# No polling or process_frame: a light tap must survive between draws.
	aim_at(target)
	var before_tap := activated
	tracker.set_input("trigger", 0.4)
	check(scene.pointer_down, "light trigger squeeze presses immediately through the input signal")
	tracker.set_input("trigger", 0.25)
	check(scene.pointer_down, "trigger hysteresis rejects partial-release chatter")
	tracker.set_input("trigger", 0.0)
	check(activated == before_tap + 1 and not scene.pointer_down, "brief press and release between rendered frames activates exactly once")
	check(scene.dock.global_transform.is_equal_approx(room_placement), "cycling every screen size leaves Room at the same world position and fixed aim still clicks")
	activated = 2
	aim_at(target)
	trigger(0.8)
	aim_at(Vector2(-100, -100))
	trigger(0.0)
	check(not scene.pointer_down and activated == 2, "release outside cancels and clears capture")
	aim_at(target)
	trigger(0.8)
	tracker.invalidate_pose("aim")
	scene._poll_trigger(controller)
	check(not scene.pointer_down and scene.click_owner == null and activated == 2, "tracking loss cancels GUI capture")
	aim_at(target)
	scene._poll_trigger(controller)
	check(not scene.pointer_down and scene.click_owner == null, "tracking recovery while trigger stays held cannot start another press")
	trigger(0.0)
	trigger(0.8)
	check(scene.pointer_down, "release after tracking recovery rearms the next trigger press")
	aim_at(Vector2(-100, -100))
	trigger(0.0)
	tracker.invalidate_pose("aim")
	scene._poll_trigger(controller)
	aim_at(target)
	trigger(0.8)
	check(not scene.pointer_down and scene.click_owner == null, "a press first observed after tracking recovery waits for release")
	trigger(0.0)
	# Browser forwarding goes only to this test's unique scratch directory.
	var scratch := test_root.path_join("input-test-%d" % Time.get_ticks_usec())
	DirAccess.make_dir_recursive_absolute(scratch.path_join("input"))
	scene.ipc = scratch
	scene._browser_command(1)
	scene._browser_command(1)
	var navigation := DirAccess.get_files_at(scratch.path_join("input"))
	check(navigation.size() == 2 and navigation[0].ends_with(".nav") and navigation[1].ends_with(".nav"), "two rapid Back actions remain separate queued commands")
	for file in navigation:
		DirAccess.remove_absolute(scratch.path_join("input").path_join(file))
	aim_at(Vector2(-100, -100))
	trigger(0.0)
	trigger(0.8)
	trigger(0.0)
	var kinds: Array[int] = []
	var files := DirAccess.get_files_at(scratch.path_join("input"))
	files.sort()
	for file in files:
		var path := scratch.path_join("input").path_join(file)
		kinds.append(int(FileAccess.get_file_as_string(path).get_slice(" ", 0)))
		DirAccess.remove_absolute(path)
	check(kinds == [1, 2], "browser receives ordered down and up packets")
	scene._forward_pointer(null, 3)
	check(FileAccess.get_file_as_string(scratch.path_join("pointer.txt")).begins_with("3 "), "tracking cancellation replaces browser pointer heartbeat")
	scene._forward_pointer(controller, 6, 3.25)
	var dock_packet := FileAccess.get_file_as_string(scratch.path_join("pointer.txt")).split(" ")
	check(int(dock_packet[0]) == 6 and is_equal_approx(float(dock_packet[8]), 3.25), "dock hover forwards nearest hit without a browser click")
	scene._forward_pointer(controller, 7)
	check(FileAccess.get_file_as_string(scratch.path_join("pointer.txt")).begins_with("7 "), "focus loss sends a noninteractive pose heartbeat")
	# Include the largest screen, a low hand and a seated backward shift. The
	# old 6 m ray stopped short of its upper opposite corner.
	var previous_visibility: bool = scene.dock.visible
	scene.dock.visible = false
	var corners_reachable := true
	var farthest := 0.0
	for side in [-1.0, 1.0]:
		var hand := Vector3(side * 0.45, 0.65, 0.75)
		for corner_x in [-2.7, 2.7]:
			for corner_y in [2.1 - 5.4 * 9.0 / 32.0, 2.1 + 5.4 * 9.0 / 32.0]:
				var corner := Vector3(corner_x, corner_y, -4.5)
				var distance: float = hand.distance_to(corner)
				farthest = maxf(farthest, distance)
				tracker.set_pose("aim", Transform3D(Basis.looking_at(corner-hand),hand),Vector3.ZERO,Vector3.ZERO,XRPose.XR_TRACKING_CONFIDENCE_HIGH)
				scene._process(0.01)
				var hover_packet := FileAccess.get_file_as_string(scratch.path_join("pointer.txt")).split(" ")
				corners_reachable = corners_reachable and float(hover_packet[8]) >= distance
	check(farthest > 6.0 and corners_reachable, "continuous rays reach every wide-screen corner from either low hand after moving back")
	scene._forward_pointer(controller, 1)
	var press_files := DirAccess.get_files_at(scratch.path_join("input"))
	var press_packet := FileAccess.get_file_as_string(scratch.path_join("input").path_join(press_files[-1])).split(" ")
	check(float(press_packet[8]) >= farthest, "trigger press uses the same full-screen reach as hover")
	for file in press_files:
		DirAccess.remove_absolute(scratch.path_join("input").path_join(file))
	scene.dock.visible = previous_visibility
	scene.browser_keyboard = true
	var start := Vector3(0, 1.65, 0)
	var keyboard_centre := Vector3(0, 1.05, -1.7)
	tracker.set_pose("aim", Transform3D(Basis.looking_at(keyboard_centre-start),start),Vector3.ZERO,Vector3.ZERO,XRPose.XR_TRACKING_CONFIDENCE_HIGH)
	check(scene._keyboard_hit(start,(keyboard_centre-start).normalized()) and scene._controller_dock_hit(controller)==null, "nearer keyboard blocks clicks on controls behind it")
	scene.browser_keyboard = false
	var other_tracker := XRControllerTracker.new()
	other_tracker.name = "left_hand"
	XRServer.add_tracker(other_tracker)
	var other: XRController3D = scene._build_controller("left")
	other_tracker.set_pose("aim", Transform3D.IDENTITY, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_HIGH)
	tracker.invalidate_pose("aim")
	scene.active_pointer = controller
	scene._select_tracked_pointer()
	check(scene.active_pointer == other, "pointer falls back to the other tracked hand")
	scene.active_pointer = controller
	scene.click_owner = controller
	scene._select_tracked_pointer()
	check(scene.active_pointer == controller, "hand fallback preserves an in-progress click owner")
	scene.click_owner = null
	XRServer.remove_tracker(other_tracker)
	DirAccess.remove_absolute(scratch.path_join("pointer.txt"))
	for width in [3.2, 4.2, 5.4]:
		scene.screen_width = width
		scene._position_dock()
		var dock_top: float = (scene.dock.position.y + scene.dock.mesh.size.y / 2 - 1.65) / 3.6
		check(dock_top < (0.45 - width * 9 / 32) / 4.5, "controls stay below screen at %.1f m" % width)
	scene._open_service("hbomax")
	await process_frame
	var request: Variant = JSON.parse_string(FileAccess.get_file_as_string(scratch.path_join("request.json")))
	check(request.service == "hbomax" and not scene.library_open, "service selection requests the right profile and enters viewing")
	scene._focus_screen()
	await process_frame
	await process_frame
	check(scene.dock.visible and scene.focused_view and scene.ui.page == "focus" and scene.dock.mesh.size.x < 1.2, "focus replaces the full dock with a compact visible exit")
	scene._controller_pressed("by_button", controller)
	await process_frame
	check(scene.dock.visible and not scene.focused_view and scene.ui.page == "player" and is_equal_approx(scene.room_brightness, scene.light_level), "right B restores controls and room light through the real button handler")
	scene._focus_screen()
	await process_frame
	await process_frame
	var exit_button: Button = scene.ui_viewport.find_children("*", "Button", true, false)[0]
	check(exit_button.text == "Show controls · B", "focus exit names both the action and controller shortcut")
	scene._dock_click(exit_button.get_global_rect().get_center(), true)
	scene._dock_click(exit_button.get_global_rect().get_center(), false)
	await process_frame
	check(not scene.focused_view and scene.ui.page == "player", "pointing and clicking the focus exit restores the full dock")
	scene._focus_screen()
	await process_frame
	scene._show_controls()
	scene._focus_screen()
	await process_frame
	check(scene.focused_view and scene.ui.page == "focus" and scene.room_brightness <= 0.12, "queued Focus transitions keep page, state and dim light consistent")
	scene._controller_pressed("by_button", controller)
	await process_frame
	check(not scene.focused_view and scene.ui.page == "player", "one B exits after rapid queued Focus transitions")
	var viewing_request: int = scene.source_request
	for page in ["room", "more"]:
		scene._render_ui(page)
		await process_frame
		scene._controller_pressed("by_button", controller)
		await process_frame
		check(scene.ui.page == "player" and not scene.focused_view and scene.source_request == viewing_request and is_equal_approx(scene.room_brightness, scene.light_level), "B closes %s to viewing without dimming or restarting the service" % page)
	scene._render_ui("room")
	scene.browser_keyboard = true
	for attempt in range(2):
		scene._controller_pressed("by_button", controller)
		var hide_command := FileAccess.get_file_as_string(scratch.path_join("input/%020d.nav" % scene.command_sequence)).split(" ")
		check(hide_command.size() == 3 and hide_command[1] == "5" and scene.ui.page == "room" and not scene.focused_view, "B with keyboard visible only queues explicit dismissal, including stale visibility attempt %d" % attempt)
	scene.browser_keyboard = false
	scene._controller_pressed("by_button", controller)
	await process_frame
	check(scene.ui.page == "player", "after keyboard dismissal the next B closes Room")
	scene._controller_pressed("by_button", controller)
	await process_frame
	check(scene.ui.page == "focus" and scene.focused_view, "B still enters Focus from the viewing dock")
	scene.browser_keyboard = true
	scene._controller_pressed("by_button", controller)
	await process_frame
	check(scene.ui.page == "focus" and scene.focused_view and scene.room_brightness <= 0.12, "dismissing a keyboard in Focus preserves the viewing mode and light")
	scene.browser_keyboard = false
	scene._show_library()
	await process_frame
	request = JSON.parse_string(FileAccess.get_file_as_string(scratch.path_join("request.json")))
	check(request.action == "library" and scene.library_open and scene.dock.visible, "returning to library requests playback shutdown")
	var library_request: int = scene.source_request
	scene._show_room()
	await process_frame
	scene._controller_pressed("by_button", controller)
	await process_frame
	check(scene.ui.page == "library" and scene.library_open and scene.source_request == library_request, "B returns from library Room without another source request")
	await process_frame
	scene._dock_click(Vector2(790, 400), true)
	scene._dock_click(Vector2(790, 400), false)
	await process_frame
	request = JSON.parse_string(FileAccess.get_file_as_string(scratch.path_join("request.json")))
	check(request.get("service", "") == "hbomax" and not scene.library_open, "native service card remains clickable through its text labels")
	scene._media_command("forward_10")
	var media_files := DirAccess.get_files_at(scratch.path_join("media"))
	var media: Variant = JSON.parse_string(FileAccess.get_file_as_string(scratch.path_join("media").path_join(media_files[0])))
	check(media.op == "forward_10" and media.created > 0, "media actions use bounded fixed commands without browser script input")
	scene._media_feedback({"last_command": {"id": scene.media_request, "ok": false}})
	check(scene.media_request == 0 and not scene.media_notice.is_empty(), "provider command refusal produces visible recovery feedback")
	scene.media_request = 12345
	scene.media_requested_at = Time.get_ticks_msec() - 7000
	scene._media_feedback({})
	check(scene.media_request == 0 and scene.media_notice.begins_with("No response"), "missing media acknowledgement times out with an actionable message")
	scene.media_request = 99
	scene.media_requested_at = Time.get_ticks_msec()
	scene._media_feedback({"last_command": {"id": null}})
	check(scene.media_request == 99, "null media acknowledgement cannot abort the status update")
	scene.media_request_navigation = true
	scene._media_feedback({"last_command": {"id": 99, "ok": false, "reason": "no_history"}})
	check(scene.media_request == 0 and scene.media_notice.begins_with("No earlier page"), "empty browser history offers Services instead of player instructions")
	scene.media_request_navigation = false
	for page in ["library", "player", "room", "more", "focus"]:
		scene.ui.show_page(page)
		await process_frame
		await process_frame
		var fits := true
		for node in scene.ui_viewport.find_children("*", "Button", true, false):
			fits = fits and Rect2(Vector2.ZERO, scene._ui_size()).encloses(node.get_global_rect())
		check(fits, "all %s controls fit their actual viewport" % page)
	scene._render_ui("room")
	await process_frame
	await process_frame
	var landscape: Button
	for node in scene.ui_viewport.find_children("*", "Button", true, false):
		if node.tooltip_text == scene.NAMES[1]:
			landscape = node
	var photo_target: Vector2 = landscape.get_global_rect().position + Vector2(200, 130)
	scene._dock_click(photo_target, true)
	scene._dock_click(photo_target, false)
	await process_frame
	check(scene.environment_index == 1, "landscape remains selectable through its photo, caption and selection outline")
	var inspection: Node = load("res://observer_view.gd").new()
	inspection.scene = scene
	root.add_child(inspection)
	inspection.set_process(false)
	scene.library_open = false
	scene._render_ui("player")
	scene._focus_screen()
	await process_frame
	tracker.invalidate_pose("aim")
	await inspection._apply_control({"show_controls": true})
	check(scene.dock.visible and not scene.focused_view and scene.ui.page == "player" and inspection.control_error.is_empty(), "off-head inspection can restore focused viewing controls")
	scene._focus_screen()
	await process_frame
	aim_at(Vector2(125, 145))
	await inspection._apply_control({"show_controls": true})
	check(scene.focused_view and not inspection.control_error.is_empty(), "inspection refuses input while a controller is tracked")
	tracker.invalidate_pose("aim")
	process_frame.connect(func(): aim_at(Vector2(125, 145)), CONNECT_ONE_SHOT)
	await inspection._apply_control({"show_controls": true, "control": [2696, 230]})
	check(not scene.focused_view and not scene.pointer_down and inspection.control_error.contains("resumed"), "inspection rechecks tracking after rebuilding the Focus dock")
	tracker.invalidate_pose("aim")
	create_timer(0.02).timeout.connect(func(): aim_at(Vector2(125, 145)), CONNECT_ONE_SHOT)
	await inspection._apply_control({"control": [2696, 230]})
	check(not scene.focused_view and not scene.pointer_down and inspection.control_error.contains("cancelled"), "inspection cancels its held click when physical tracking resumes")
	tracker.invalidate_pose("aim")
	scene._render_ui("room")
	await process_frame
	await process_frame
	var physical_center: Vector2 = scene.screen_button.get_global_rect().get_center() * Vector2(scene.ui_viewport.size) / scene._ui_size()
	var previous_width: float = scene.screen_width
	await inspection._apply_control({"control": [physical_center.x, physical_center.y]})
	check(scene.screen_width != previous_width and inspection.control_error.is_empty(), "inspection screenshot coordinates select the correct supersampled control")
	await inspection._apply_control({"show_controls": true, "control": [-100, -100]})
	check(not inspection.control_error.is_empty(), "inspection rejects points outside the native UI")
	var inspection_request := FileAccess.open(scratch.path_join("observe-request.json"), FileAccess.WRITE)
	scene._focus_screen()
	await process_frame
	inspection_request.store_string(JSON.stringify({"id": "expired-action", "created": 1, "control_only": true, "show_controls": true}))
	inspection_request.close()
	await inspection._process(1.0)
	var expired: Variant = JSON.parse_string(FileAccess.get_file_as_string(scratch.path_join("observe-result.json")))
	check(scene.focused_view and not expired.get("control_error", "").is_empty(), "an expired inspection action cannot replay after restart")
	inspection_request = FileAccess.open(scratch.path_join("observe-request.json"), FileAccess.WRITE)
	inspection_request.store_string(JSON.stringify({"id": "synthetic-ack", "created": Time.get_unix_time_from_system(), "control_only": true, "show_controls": true}))
	inspection_request.close()
	await inspection._process(1.0)
	var ack: Variant = JSON.parse_string(FileAccess.get_file_as_string(scratch.path_join("observe-result.json")))
	check(ack.get("control_only", false) and ack.get("id") == "synthetic-ack", "control acknowledgement is written without capturing browser pixels")
	DirAccess.remove_absolute(scratch.path_join("observe-request.json"))
	DirAccess.remove_absolute(scratch.path_join("observe-result.json"))
	inspection.free()
	var ready_panel := FileAccess.open(scratch.path_join("panel-status.json"), FileAccess.WRITE)
	ready_panel.store_string(JSON.stringify({"heartbeat": Time.get_ticks_usec(), "window_attached": true}))
	ready_panel.close()
	scene._render_ui("more")
	var status_file := FileAccess.open(scratch.path_join("status.json"), FileAccess.WRITE)
	status_file.store_string(JSON.stringify({"updated": Time.get_unix_time_from_system(), "source": "local", "library": false, "request_id": scene.source_request, "panel_running": true}))
	status_file.close()
	for fullscreen in [true, false]:
		var media_status := FileAccess.open(scratch.path_join("media-status.json"), FileAccess.WRITE)
		media_status.store_string(JSON.stringify({"updated": Time.get_unix_time_from_system(), "available": true, "page_ready": true, "video": true, "fullscreen": fullscreen}))
		media_status.close()
		scene._update_status()
		check(scene.fullscreen_button.disabled != fullscreen, "fullscreen recovery button follows actual fullscreen state %s" % str(fullscreen))
	# Actual startup has a null request ID before the first service is chosen.
	scene._render_ui("player")
	status_file = FileAccess.open(scratch.path_join("status.json"), FileAccess.WRITE)
	status_file.store_string(JSON.stringify({"updated": Time.get_unix_time_from_system(), "source": "local", "library": false, "request_id": null, "panel_running": true}))
	status_file.close()
	var playing := FileAccess.open(scratch.path_join("media-status.json"), FileAccess.WRITE)
	playing.store_string(JSON.stringify({"updated": Time.get_unix_time_from_system(), "available": true, "page_ready": true, "video": true, "can_control": true, "can_seek": true, "paused": false, "height": 720}))
	playing.close()
	scene.source_pending = false
	scene._update_status()
	check(not scene.play_button.disabled and scene.play_button.text == "Pause", "null startup request ID does not abort fresh media status")
	scene.media_notice = ""
	for keyboard_case in [
		{"keyboard_visible": true, "keyboard_target_ready": true, "window_attached": true, "expected": "Keyboard ready"},
		{"keyboard_visible": true, "keyboard_target_ready": false, "window_attached": true, "expected": "Select a field"},
		{"keyboard_visible": false, "keyboard_error": 11, "window_attached": true, "expected": "Keyboard unavailable"},
		{"keyboard_visible": false, "window_attached": false, "expected": "Waiting for screen"}]:
		var panel_status := FileAccess.open(scratch.path_join("panel-status.json"), FileAccess.WRITE)
		keyboard_case.heartbeat = Time.get_ticks_usec()
		panel_status.store_string(JSON.stringify(keyboard_case))
		panel_status.close()
		scene._read_panel_status()
		scene._update_status()
		check(scene.status_label.text.begins_with(keyboard_case.expected), "dock preserves distinct keyboard or screen status: " + str(keyboard_case.expected))
	ready_panel = FileAccess.open(scratch.path_join("panel-status.json"), FileAccess.WRITE)
	ready_panel.store_string(JSON.stringify({"heartbeat": Time.get_ticks_usec(), "window_attached": true}))
	ready_panel.close()
	scene._read_panel_status()
	for playback_case in [
		{"video": true, "title_player": false, "width": 1280, "height": 720, "can_control": true, "paused": false, "expected": "Stick:"},
		{"video": true, "title_player": true, "width": 1280, "height": 534, "can_control": true, "paused": false, "expected": "Playing  ·  1280 × 534"},
		{"video": true, "title_player": true, "width": 854, "height": 480, "can_control": false, "paused": true, "expected": "Paused  ·  854 × 480"}]:
		playback_case.updated = Time.get_unix_time_from_system()
		playback_case.available = true
		playback_case.page_ready = true
		playing = FileAccess.open(scratch.path_join("media-status.json"), FileAccess.WRITE)
		playing.store_string(JSON.stringify(playback_case))
		playing.close()
		scene._update_status()
		check(scene.status_label.text.begins_with(playback_case.expected), "dock separates preview, cropped frame and editing states: " + str(playback_case.expected))
	playing = FileAccess.open(scratch.path_join("media-status.json"), FileAccess.WRITE)
	playing.store_string(JSON.stringify({"updated": Time.get_unix_time_from_system(), "available": true, "page_ready": true, "video": true, "can_control": true, "paused": false}))
	playing.close()
	scene.render_models = Node3D.new()
	scene.add_child(scene.render_models)
	var container := Node3D.new()
	scene.render_models.add_child(container)
	container.add_child(Node3D.new())
	scene.play_button.text = "stale"
	scene.report_tick = 2.0
	scene._process(0.01)
	check(scene.play_button.text == "Pause" and not scene.play_button.disabled, "transform-only controller containers cannot interrupt periodic playback status")
	# A failed replacement must restore the old source's identity and expose
	# recovery; otherwise a still-running Netflix panel is labelled Disney+.
	scene.selected_service = "disneyplus"
	scene.source_pending = true
	status_file = FileAccess.open(scratch.path_join("status.json"), FileAccess.WRITE)
	status_file.store_string(JSON.stringify({"updated": Time.get_unix_time_from_system(), "source": "local", "request_id": scene.source_request, "panel_running": false, "cleanup_pending": true, "service": "netflix", "library": false}))
	status_file.close()
	scene._update_status()
	await process_frame
	await process_frame
	scene._update_status()
	check(scene.selected_service == "netflix" and not scene.source_pending and scene.status_label.text.begins_with("Still closing") and scene.play_button.disabled, "unfinished cleanup restores the real service, disables playback and exposes retry feedback")
	await load("res://test_recovery.gd").new().run(scene, scratch, check)
	load("res://test_playback_health.gd").new().run(check)
	await load("res://test_rooms.gd").new().run(scene, check)
	scene.render_models.free()
	scene.render_models = null
	DirAccess.remove_absolute(scratch.path_join("pointer.txt"))
	DirAccess.remove_absolute(scratch.path_join("scene.json"))
	DirAccess.remove_absolute(scratch.path_join("media-status.json"))
	DirAccess.remove_absolute(scratch.path_join("status.json"))
	for file in media_files:
		DirAccess.remove_absolute(scratch.path_join("media").path_join(file))
	DirAccess.remove_absolute(scratch.path_join("media"))
	DirAccess.remove_absolute(scratch.path_join("request.json"))
	DirAccess.remove_absolute(scratch.path_join("input"))
	DirAccess.remove_absolute(scratch)
	scene.ipc = ""
	DirAccess.remove_absolute(ProjectSettings.globalize_path(scene.preferences_path))
	XRServer.remove_tracker(tracker)
	scene.queue_free()
	await process_frame
	print("Input regression failures: ", failures)
	quit(1 if failures else 0)
