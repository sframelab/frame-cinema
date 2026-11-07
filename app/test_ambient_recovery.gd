extends SceneTree
class Host extends Node3D:
	var xr_active := false
	var preview := true
	var library_open := false
	var source_pending := false
	var browser_keyboard := false
	var panel_fresh := true
	var panel_aligned := true
	var ambient_mode := 3
	var ambient_brightness := .5
	var screen_width := 4.2
	var picture_top := 0.0
	var environment_index := 5
	var placement_session := "ambient-recovery"
	var ipc := ""
	var fit_picture := false
	var fit_media := {}
	var ui := {"page":"focus"}
	func _placement_session_state() -> int: return OpenXRInterface.SESSION_STATE_VISIBLE
	func _alpine_room() -> bool: return environment_index == 7
	func _effective_ambient_mode() -> int: return 0 if _alpine_room() else ambient_mode
	func _display_screen_width() -> float: return 840 if _alpine_room() else 4.2
	func _screen_center() -> Vector3: return Vector3(0,5.54423,-900) if _alpine_room() else Vector3(0,2.1,-4.5)
	func _lake_reflection_wanted() -> bool: return _alpine_room()

func _initialize() -> void: call_deferred("run")
func write(host: Host,name: String,value: Dictionary) -> void:
	FileAccess.open(host.ipc.path_join(name),FileAccess.WRITE).store_string(JSON.stringify(value))
func run() -> void:
	var host := Host.new()
	host.ipc = OS.get_environment("FRAME_CINEMA_TEST_OUT")
	root.add_child(host)
	var current = load("res://cinema_ambient.gd").new()
	var baseline = load("res://ambient_baseline.gd").new()
	for light in [current,baseline]:
		light.host = host
		host.add_child(light)
	var now := Time.get_unix_time_from_system()
	var colors := []
	for i in 256: colors.append([.6,.2,.1])
	var sample := {"session":host.placement_session,"source_session":"fixture","updated":now,"sequence":1,"available":true,"colors":colors,"window":55,"viewport":[1920,1080]}
	write(host,"status.json",{"updated":now,"panel_running":true,"source_session":"fixture"})
	write(host,"ambient-status.json",sample)
	for light in [current,baseline]:
		light.poll_elapsed = 1
		light.tick(.05)
		assert(light.available and is_equal_approx(light.target[0].r,.6))
	# Reproduce the old blackout trigger: one unavailable capture, same source.
	sample.available = false
	write(host,"ambient-status.json",sample)
	for light in [current,baseline]:
		light.poll_elapsed = 1
		light.tick(.05)
	assert(baseline.target[0] == Color.BLACK)
	assert(not current.available and current.palette_held and is_equal_approx(current.target[0].r,.6))
	current.consume(null,"fixture",now+.2)
	assert(current.palette_held and is_equal_approx(current.target[0].r,.6))
	current.consume(null,"fixture",now+.26)
	assert(not current.palette_held and current.target[0] == Color.BLACK)
	sample.available = true
	current.consume(sample,"fixture",now)
	# A genuine black frame must take effect immediately, not invoke the hold.
	for i in 256: colors[i] = [0,0,0]
	sample.colors = colors
	sample.sequence = 2
	current.consume(sample,"fixture",now+.01)
	assert(current.available and not current.palette_held and current.target[0] == Color.BLACK)
	current.consume(null,"new-source",now+.02)
	assert(not current.palette_held and current.last_good_updated == 0 and current.colors[0] == Color.BLACK)
	assert(current.field_elapsed >= current.FIELD_INTERVAL)
	# Alpine has no optical updates, while reflection sampling remains requested.
	host.environment_index = 7
	var updates: int = current.field_updates
	current.control_elapsed = 1
	current.tick(.05)
	assert(not current.visible and current.lights[0].light_energy == 0 and current.field_updates == updates)
	assert(FileAccess.get_file_as_string(host.ipc.path_join("ambient-control.txt")).ends_with(" 1 1"))
	assert(host.ambient_mode == 3)
	# Playing at 72 Hz, drifting colours redraw the field on every third frame.
	host.environment_index = 5
	current.available = true
	current.control_elapsed = 0
	current.target.fill(Color(.6,.2,.1))
	current.colors = current.target.duplicate()
	updates = current.field_updates
	for frame in 72:
		current.target.fill(Color(.6 + frame * .0002,.2,.1))
		current.poll_elapsed = 0
		current.tick(1.0 / 72.0)
	var redraws: int = current.field_updates - updates
	assert(redraws >= 23 and redraws <= 26, "field redraws in one second: %d" % redraws)
	# A jump redraws at once, on every frame while the colours move fast.
	current.target.fill(Color.WHITE)
	updates = current.field_updates
	for frame in 12:
		current.poll_elapsed = 0
		current.tick(1.0 / 72.0)
	assert(current.field_updates - updates == 12, "field redraws in a jump: %d" % (current.field_updates - updates))
	# A last small change, under the jump limit, lands within three frames from any point in the cycle.
	for phase in 3:
		for frame in phase:
			current.poll_elapsed = 0
			current.tick(1.0 / 72.0)
		var settled: Color = current.colors[0] - Color(.002,.002,.002,0)
		current.colors.fill(settled)
		current.target.fill(settled)
		for frame in 3:
			current.poll_elapsed = 0
			current.tick(1.0 / 72.0)
		assert(current.uploaded_colors == current.colors)
	# One sampled zone can start a redraw, in any channel, even at the same peak.
	current.colors.fill(Color(.9,.2,.2))
	current.target.fill(Color(.9,.2,.2))
	current.poll_elapsed = 0
	current.tick(1.0 / 72.0)
	current.colors[128] = Color(.2,.2,.9)
	current.target[128] = Color(.2,.2,.9)
	updates = current.field_updates
	current.poll_elapsed = 0
	current.tick(1.0 / 72.0)
	assert(current.field_updates - updates == 1, "field redraws for one zone: %d" % (current.field_updates - updates))
	# A direct advance() always redraws, even for a change under the jump limit.
	updates = current.field_updates
	for frame in 3:
		var small: Color = current.colors[0] - Color(.001,.001,.001,0)
		current.colors.fill(small)
		current.target.fill(small)
		current.advance(1.0 / 72.0,3,.5)
	assert(current.field_updates - updates == 3, "direct redraws: %d" % (current.field_updates - updates))
	print("AMBIENT_RECOVERY_OK: old dropout reproduced; bounded same-source hold; real black, source change, Alpine Off/reflection, field redraw rate tested")
	quit()
