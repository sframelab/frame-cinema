extends SceneTree

class Host extends Node3D:
	var xr_active := true
	var session_state := OpenXRInterface.SESSION_STATE_FOCUSED
	var preview := false
	var library_open := false
	var source_pending := false
	var browser_keyboard := false
	var panel_fresh := true
	var panel_aligned := true
	var ambient_mode := 3
	var ambient_brightness := 0.75
	var screen_width := 4.2
	var picture_top := 0.0
	var environment_index := 5
	var placement_session := "ambient-visibility-test"
	var ipc := ""
	var fit_picture := false
	var fit_media := {}
	var ui := {"page": "player"}
	func _input_available() -> bool:
		return not xr_active or session_state == OpenXRInterface.SESSION_STATE_FOCUSED
	func _placement_session_state() -> int:
		return session_state
	func _screen_center() -> Vector3:
		return Vector3(0, 2.1, -4.5)

var failures := 0
var checks := 0
var host: Host
var glow: Node3D

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
	print(("PASS " if ok else "FAIL ") + label)

func write_json(name: String, value: Dictionary) -> void:
	var file := FileAccess.open(host.ipc.path_join(name), FileAccess.WRITE)
	file.store_string(JSON.stringify(value))

func tick_sample(age: float = 0.0, source: String = "fixture") -> void:
	var now := Time.get_unix_time_from_system()
	var palette := []
	for i in 256:
		palette.append([0.6, 0.15, 0.03])
	write_json("status.json", {"updated": now, "panel_running": true, "source_session": "fixture"})
	write_json("ambient-status.json", {"session": host.placement_session, "source_session": source, "updated": now - age, "sequence": 1, "available": true, "colors": palette})
	glow.control_elapsed = 1.0
	glow.poll_elapsed = 1.0
	glow.tick(0.1)

func control_on() -> bool:
	return FileAccess.get_file_as_string(host.ipc.path_join("ambient-control.txt")).strip_edges().ends_with(" 1")

func run() -> void:
	host = Host.new()
	host.ipc = OS.get_environment("FRAME_CINEMA_TEST_OUT")
	assert(not host.ipc.is_empty())
	DirAccess.make_dir_recursive_absolute(host.ipc)
	root.add_child(host)
	glow = load("res://cinema_ambient.gd").new()
	glow.host = host
	host.add_child(glow)
	tick_sample()
	check(glow.available and glow.visible and control_on(), "focused scene samples and displays ambient")
	host.session_state = OpenXRInterface.SESSION_STATE_VISIBLE
	tick_sample()
	check(not host._input_available(), "native overlay handoff releases application input")
	check(control_on(), "visible scene keeps sampler enabled after native handoff")
	check(glow.available and glow.visible and glow.lights[0].light_energy > 0, "visible scene retains haze and surface light without XR input focus")
	for state in [OpenXRInterface.SESSION_STATE_IDLE, OpenXRInterface.SESSION_STATE_READY, OpenXRInterface.SESSION_STATE_SYNCHRONIZED, OpenXRInterface.SESSION_STATE_STOPPING, OpenXRInterface.SESSION_STATE_LOSS_PENDING, OpenXRInterface.SESSION_STATE_EXITING]:
		host.session_state = state
		tick_sample()
		check(not control_on() and not glow.visible and glow.lights[0].light_energy == 0, "nonvisible state %d disables ambient" % state)
	host.session_state = OpenXRInterface.SESSION_STATE_VISIBLE
	for gate in ["library_open", "source_pending", "browser_keyboard", "panel_fresh", "panel_aligned"]:
		var original: bool = host.get(gate)
		host.set(gate, not original)
		tick_sample()
		check(not control_on() and not glow.visible and glow.lights[0].light_energy == 0, gate + " retains ambient suppression")
		host.set(gate, original)
	host.ambient_mode = 0
	tick_sample()
	check(not control_on() and not glow.visible, "Off remains off during native handoff")
	host.ambient_mode = 3
	tick_sample(1.0)
	check(not glow.available and glow.target[0] == Color.BLACK, "stale palette cannot illuminate the scene")
	tick_sample(0.0, "other-source")
	check(not glow.available and glow.target[0] == Color.BLACK, "foreign source palette rejected")
	tick_sample()
	check(glow.visible and control_on(), "fresh visible scene recovers after suppression")
	host.session_state = OpenXRInterface.SESSION_STATE_FOCUSED
	tick_sample()
	check(glow.visible and control_on(), "returning XR input focus preserves ambient")
	host.xr_active = false
	host.session_state = OpenXRInterface.SESSION_STATE_IDLE
	tick_sample()
	check(glow.visible and control_on(), "non-XR rendering retains ambient")
	print("AMBIENT_VISIBILITY checks=%d failures=%d" % [checks, failures])
	host.queue_free()
	await process_frame
	quit(1 if failures else 0)
