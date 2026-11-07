extends RefCounted

# Real file IPC and UI transitions; only elapsed time is advanced synthetically.
var scene: Node3D
var scratch: String
var check: Callable
var refresh_healthy_panel := true

class ShiftedHealth extends "res://playback_health.gd":
	func observe(state: Dictionary, now: int) -> String:
		return super.observe(state, now + 60000)

func write_status(extra: Dictionary = {}) -> void:
	if refresh_healthy_panel:
		write_panel()
	var value := {"updated": Time.get_unix_time_from_system(), "source": "local", "library": false, "panel_running": true, "request_id": null}
	value.merge(extra, true)
	write_json("status.json", value)

func write_media(extra: Dictionary = {}) -> void:
	if refresh_healthy_panel:
		write_panel()
	var value := {"updated": Time.get_unix_time_from_system(), "available": true, "page_ready": true,
		"video": true, "title_player": true, "can_control": true, "can_seek": true, "paused": false, "width": 1920, "height": 1080}
	value.merge(extra, true)
	write_json("media-status.json", value)

func write_panel() -> void:
	write_json("panel-status.json", {"heartbeat": Time.get_ticks_usec(), "window_attached": true})

func write_json(name: String, value: Dictionary) -> void:
	var file := FileAccess.open(scratch.path_join(name), FileAccess.WRITE)
	file.store_string(JSON.stringify(value))
	file.close()

func run(target: Node3D, folder: String, assertion: Callable) -> void:
	scene = target
	scratch = folder
	check = assertion
	scene.source_pending = false
	scene.library_open = false
	scene.service_wait_since = -1
	scene.panel_message = ""
	scene.media_notice = ""
	write_panel()
	scene._render_ui("player")
	write_status()
	write_media()
	scene._update_status()
	check.call(not scene.play_button.disabled and scene.status_label.text.contains("1920 × 1080"), "healthy source exposes current playback and controls")
	scene._render_ui("focus")
	await scene.get_tree().process_frame
	await scene.get_tree().process_frame
	var return_button: Button = scene.ui_viewport.find_children("*", "Button", true, false)[0]
	var original_world := focus_button_world(return_button)
	check.call(scene._ui_size() == Vector2(400, 112) and not scene.status_label.is_visible_in_tree(), "healthy Focus remains a compact return capsule")
	scene._dock_click(return_button.get_global_rect().get_center(), true)
	write_media({"error_code": 3, "player_generation": "fixture:1", "paused": true})
	scene._update_status()
	await scene.get_tree().process_frame
	await scene.get_tree().process_frame
	check.call(scene.ui.page == "focus" and scene.focused_view and scene.room_brightness <= 0.12 and scene.status_label.is_visible_in_tree() and scene.status_label.text.begins_with("Playback error"), "a media error becomes visible in Focus without leaving the mode or brightening the room")
	check.call(is_instance_valid(return_button) and focus_button_world(return_button).is_equal_approx(original_world) and scene.pointer_down, "Focus notice preserves the actual return button, its world position and a held press")
	check.call(Rect2(Vector2.ZERO, scene._ui_size()).encloses(scene.status_label.get_global_rect()), "Focus recovery text fits the enlarged surface")
	scene._dock_click(return_button.get_global_rect().get_center(), false)
	await scene.get_tree().process_frame
	check.call(scene.ui.page == "player" and not scene.focused_view, "releasing the retained button after a notice appears still returns to controls")
	check.call(scene.status_label.text.begins_with("Playback error") and not scene.play_button.disabled and not scene.media_buttons[0].disabled, "reported video errors leave transport usable and expose manual Reload")
	scene._render_ui("focus")
	await scene.get_tree().process_frame
	await scene.get_tree().process_frame
	return_button = scene.ui_viewport.find_children("*", "Button", true, false)[0]
	original_world = focus_button_world(return_button)
	write_media()
	scene._update_status()
	await scene.get_tree().process_frame
	await scene.get_tree().process_frame
	check.call(scene._ui_size() == Vector2(400, 112) and not scene.status_label.is_visible_in_tree() and focus_button_world(return_button).is_equal_approx(original_world), "recovery retracts the Focus notice without moving or replacing the return button")
	var advancing := {"player_generation": "focus:clock", "current": 10.0, "current_valid": true, "playback_rate": 1.0, "ended": false, "seeking": false}
	var previous_health: RefCounted = scene.playback_health
	scene.playback_health = ShiftedHealth.new()
	write_media(advancing)
	scene._update_status()
	scene.playback_health.last_progress_at = Time.get_ticks_msec() + 60000 - 6000
	await scene.get_tree().process_frame
	write_media(advancing)
	scene._update_status()
	check.call(scene.playback_message.begins_with("Waiting for video") and not scene.status_label.is_visible_in_tree(), "brief buffering does not expand Focus or imply user action is needed")
	scene.playback_health.last_progress_at = Time.get_ticks_msec() + 60000 - 21000
	await scene.get_tree().process_frame
	write_media(advancing)
	scene._update_status()
	check.call(scene.status_label.is_visible_in_tree() and scene.status_label.text.begins_with("Playback not advancing"), "persistent stopped playback exposes Reload guidance in Focus")
	await scene.get_tree().process_frame
	advancing.current = 11.0
	write_media(advancing)
	scene._update_status()
	check.call(not scene.status_label.is_visible_in_tree() and not scene.playback_health.needs_attention, "advancing video clears both the Focus notice and attention state")
	scene.playback_health = previous_health
	write_status({"panel_running": false})
	scene._update_status()
	check.call(scene.status_label.is_visible_in_tree() and scene.status_label.text.begins_with("Service closed"), "a closed service explains Reopen even while Focus remains active")
	write_status({"updated": Time.get_unix_time_from_system() - 30})
	scene._update_status()
	scene.service_wait_since = Time.get_ticks_msec() - 6000
	scene._update_status()
	check.call(scene.status_label.text.contains("Relaunch from Steam") and scene.ui.page == "focus", "Focus distinguishes an unresponsive app from a service restart")
	write_status({"source": "pc"})
	scene._update_status()
	check.call(not scene.status_label.is_visible_in_tree(), "ordinary PC stream status does not expand Focus")
	write_status()
	write_media()
	write_json("panel-status.json", {"heartbeat": Time.get_ticks_usec(), "keyboard_visible": true, "keyboard_target_ready": true, "window_attached": true})
	scene._update_status()
	check.call(not scene.status_label.is_visible_in_tree(), "ordinary keyboard-ready guidance does not expand Focus")
	write_json("panel-status.json", {"heartbeat": Time.get_ticks_usec(), "keyboard_visible": true, "keyboard_target_ready": false, "window_attached": true})
	scene._update_status()
	check.call(scene.status_label.is_visible_in_tree() and scene.status_label.text == "Select a field to type", "Focus still explains an open keyboard without a text target")
	write_media({"error_code": 3, "player_generation": "fixture:1", "paused": true})
	scene._render_ui("more")
	check.call(scene.status_label.text.begins_with("Playback error"), "More preserves the video error while offering recovery")
	write_json("panel-status.json", {"heartbeat": Time.get_ticks_usec(), "keyboard_visible": true, "keyboard_target_ready": true, "window_attached": true})
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Keyboard ready"), "keyboard feedback takes priority over playback errors")
	write_status({"updated": Time.get_unix_time_from_system() - 30})
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Waiting for Cinema") and scene.media_state.is_empty(), "infrastructure failure clears old playback evidence")
	write_status()
	write_media()
	scene._render_ui("player")
	check.call(scene.status_label.text.begins_with("Playing") and scene.playback_message.is_empty(), "fresh healthy playback clears the media error")

	write_media({"updated": Time.get_unix_time_from_system() - 20})
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Connecting"), "lost browser telemetry removes stale playback and allows a recovery grace period")
	scene.service_wait_since = Time.get_ticks_msec() - 11000
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Service not responding"), "persistent missing telemetry offers service recovery")
	write_media({"available": false})
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Service not responding"), "fresh error telemetry cannot reenable stale player controls")
	write_media({"video": false, "title_player": false, "can_control": false, "width": 0, "height": 0})
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Stick:") and scene.service_wait_since == -1, "responsive browsing or sign-in clears the warning without requiring video")
	write_media({"page_ready": false, "video": false, "can_control": false})
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Loading service"), "responsive loading is distinct from a stalled browser")
	scene.service_wait_since = Time.get_ticks_msec() - 31000
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Loading slowly"), "prolonged page loading offers Reload without claiming the service crashed")
	write_media({"available": false})
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Connecting") and scene.service_wait_reason == "service", "a transient media failure cannot inherit a long page-loading timeout")
	scene.service_wait_since = Time.get_ticks_msec() - 11000
	DirAccess.remove_absolute(scratch.path_join("status.json"))
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Waiting for Cinema") and scene.service_wait_reason == "supervisor", "supervisor outage receives its own grace after a different failure")
	write_status()
	write_media()
	scene._update_status()
	check.call(not scene.play_button.disabled and scene.status_label.text.begins_with("Playing"), "a fresh title clears the loading warning and restores transport")
	write_media({"can_control": false})
	scene._update_status()
	scene._render_ui("player")
	check.call(scene.play_button.disabled, "rebuilding controls during editing cannot reenable playback shortcuts")
	write_media({"available": false, "fullscreen": true})
	scene._update_status()
	scene._render_ui("more")
	check.call(scene.fullscreen_button.disabled, "rebuilding More cannot expose a fullscreen action from unavailable telemetry")
	write_media()
	scene._render_ui("player")
	scene._update_status()

	DirAccess.remove_absolute(scratch.path_join("status.json"))
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Waiting for Cinema"), "missing supervisor data clears controls rather than preserving a false Playing state")
	scene.service_wait_since = Time.get_ticks_msec() - 6000
	scene._update_status()
	check.call(scene.status_label.text.contains("Relaunch from Steam"), "persistent supervisor failure offers app relaunch instead of an unusable browser retry")
	write_json("status.json", {})
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.contains("Relaunch from Steam"), "incomplete supervisor data cannot restore controls")
	write_json("status.json", {"updated": Time.get_unix_time_from_system(), "panel_running": true})
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.contains("Relaunch from Steam"), "fresh but incomplete supervisor record cannot claim service readiness")
	write_status({"panel_running": "true"})
	scene._update_status()
	check.call(scene.play_button.disabled, "incorrect supervisor field types cannot restore controls")
	write_status()
	scene._update_status()
	check.call(not scene.play_button.disabled and scene.service_wait_since == -1, "supervisor recovery clears the warning without a forced restart")

	scene._select_source("local", true)
	scene.source_requested_at = Time.get_ticks_msec() - 16000
	write_status({"request_id": scene.source_request, "updated": Time.get_unix_time_from_system() - 30})
	scene._update_status()
	check.call(scene.source_pending and scene.play_button.disabled and scene.status_label.text.contains("Relaunch from Steam"), "a stale acknowledgement cannot complete a new launch request")
	write_status({"request_id": null})
	scene._update_status()
	check.call(scene.source_pending and scene.status_label.text.begins_with("Opening stalled"), "an unacknowledged launch has a bounded wait and explicit retry")
	write_status({"request_id": scene.source_request})
	scene._update_status()
	check.call(not scene.source_pending and not scene.play_button.disabled, "a late fresh acknowledgement recovers without issuing a duplicate launch")

	scene._show_library()
	await scene.get_tree().process_frame
	await scene.get_tree().process_frame
	scene.source_requested_at = Time.get_ticks_msec() - 16000
	write_status()
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Closing stalled"), "library shows a failed close rather than silently appearing ready")
	write_status({"request_id": scene.source_request, "library": true, "source": "", "panel_running": false})
	scene._update_status()
	check.call(not scene.source_pending and scene.status_label.text.is_empty(), "acknowledged library closure clears recovery feedback")
	scene.library_open = false
	scene._render_ui("player")
	write_status({"source": "pc"})
	write_media({"updated": Time.get_unix_time_from_system() - 30})
	scene._update_status()
	check.call(scene.status_label.text.begins_with("PC stream") and scene.play_button.disabled, "PC source is not falsely judged by missing local browser telemetry")

	write_status()
	write_media()
	refresh_healthy_panel = false
	write_json("panel-status.json", {"heartbeat": Time.get_ticks_usec(), "keyboard_visible": true, "keyboard_error": 11, "window_attached": true, "beam_ready": true})
	scene._read_panel_status()
	scene.panel_seen = Time.get_ticks_msec() - 3000
	scene._read_panel_status()
	scene._update_status()
	check.call(not scene.browser_keyboard and not scene.compositor_pointer and scene.play_button.disabled and scene.status_label.text.begins_with("Waiting for screen"), "expired panel status cannot retain keyboard, controls or misleading field errors")
	scene.service_wait_since = Time.get_ticks_msec() - 11000
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Screen not responding"), "a persistently expired panel heartbeat offers recovery")
	write_json("panel-status.json", {"keyboard_visible": true, "keyboard_target_ready": true, "window_attached": true, "beam_ready": true, "heartbeat": 1})
	scene._read_panel_status()
	scene._update_status()
	check.call(scene.browser_keyboard and scene.compositor_pointer and scene.status_label.text.begins_with("Keyboard ready"), "fresh panel heartbeat restores normal keyboard status")
	DirAccess.remove_absolute(scratch.path_join("panel-status.json"))

	scene._update_status()
	scene.service_wait_since = Time.get_ticks_msec() - 11000
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Screen not responding"), "missing panel heartbeat cannot look healthy despite advancing browser telemetry")
	var invalid := FileAccess.open(scratch.path_join("panel-status.json"), FileAccess.WRITE)
	invalid.store_string("[]")
	invalid.close()
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Screen not responding"), "non-object panel status cannot clear the screen failure")
	write_json("panel-status.json", {"heartbeat": "invalid", "window_attached": true})
	scene._update_status()
	check.call(scene.play_button.disabled, "wrong-type panel heartbeat cannot restore playback controls")
	write_status({"source": "pc"})
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Screen not responding"), "PC source also requires a live compositor panel")
	write_panel()
	scene._update_status()
	check.call(scene.status_label.text.begins_with("PC stream"), "a fresh PC panel clears screen failure without local browser telemetry")
	refresh_healthy_panel = true
	write_status()
	write_media({"updated": Time.get_unix_time_from_system() + 100})
	scene._update_status()
	check.call(scene.play_button.disabled, "future-dated telemetry cannot make stale media controls usable")
	write_json("media-status.json", {"updated": Time.get_unix_time_from_system(), "video": true, "can_control": true})
	scene._update_status()
	check.call(scene.play_button.disabled, "fresh incomplete media record cannot fabricate playback readiness")
	write_media({"can_control": "true"})
	scene._update_status()
	check.call(scene.play_button.disabled, "wrong-type media control flag is rejected without aborting status updates")
	var malformed := FileAccess.open(scratch.path_join("media-status.json"), FileAccess.WRITE)
	malformed.store_string("{")
	malformed.close()
	scene._update_status()
	check.call(scene.play_button.disabled, "malformed media JSON leaves controls unavailable")
	write_media()
	scene._update_status()
	write_media({"updated": Time.get_unix_time_from_system() - 30})
	scene._render_ui("player")
	check.call(scene.play_button.disabled and not scene.status_label.text.begins_with("Opening"), "UI rebuild rereads expired telemetry before exposing controls")
	write_media()
	write_status({"source": "pc"})
	scene._render_ui("player")
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("PC stream"), "UI rebuild honors the current PC source immediately")
	write_status()
	scene._select_source("local", true)
	scene._render_ui("player")
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Opening"), "UI rebuild during a pending source switch cannot reuse old media controls")
	write_status({"request_id": scene.source_request})
	write_media({"available": false})
	scene._update_status()

	scene._render_ui("more")
	scene.service_wait_since = Time.get_ticks_msec() - 11000
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Service not responding"), "recovery panel preserves the failure while the user chooses an action")
	write_media()
	scene._update_status()
	check.call(scene.status_label.text.begins_with("Captions, audio"), "recovered More panel returns to its normal guidance")

	# A failed write must not pretend a request is pending forever.
	scene.ipc = scratch.path_join("status.json")
	scene._source_request({"mode": "local"})
	check.call(not scene.source_pending and not scene.source_error.is_empty(), "request publication failure is visible instead of an endless Opening state")
	scene.ipc = scratch
	scene._render_ui("player")
	scene._update_status()
	check.call(scene.play_button.disabled and scene.status_label.text.begins_with("Could not send request"), "a failed source request cannot reuse the old source's enabled controls")
	scene._source_request({"mode": "local"})
	check.call(scene.source_pending and scene.source_error.is_empty() and scene.service_wait_since == -1, "explicit retry clears the prior request failure and its timeout")
	scene.source_pending = false
	DirAccess.remove_absolute(scratch.path_join("panel-status.json"))

func focus_button_world(button: Button) -> Vector3:
	var uv: Vector2 = button.get_global_rect().get_center() / scene._ui_size()
	return scene.dock.to_global(Vector3((uv.x - 0.5) * scene.dock.mesh.size.x, (0.5 - uv.y) * scene.dock.mesh.size.y, 0))
