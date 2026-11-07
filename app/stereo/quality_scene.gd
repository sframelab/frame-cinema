extends "res://cinema.gd"
var observations: Array = []
var observation_clock := 0.0
var save_clock := 0.0
func _ready() -> void:
	preferences_path = "user://ambient-fixture-none.cfg"
	environment_index = 5
	ambient_mode = 2
	ambient_brightness = .5
	screen_width = 4.2
	super._ready()
	focused_view = true
	library_open = false
	_render_ui.call_deferred("focus")
	dock.hide()
func _update_status() -> void:
	_read_panel_status()
func _read_panel_status() -> void:
	# This fixture places its leased overlays itself and has no panel_host
	# heartbeat. Model that envelope from its actual fresh browser clock.
	var path := ipc.path_join("stereo-fixture/video-frame.txt")
	var fields := FileAccess.get_file_as_string(path).strip_edges().split(" ",false) if FileAccess.file_exists(path) else PackedStringArray()
	panel_fresh = fields.size() == 11 and fields[0] == "FCVF1" and fields[1] == placement_session and fields[3].is_valid_float() and absf(Time.get_unix_time_from_system()-float(fields[3])) < .5
	panel_aligned = panel_fresh
func _tick_ambient(delta: float) -> void:
	var original := ipc
	ipc = ipc.path_join("stereo-fixture")
	if DirAccess.dir_exists_absolute(ipc):
		var status := {"updated":Time.get_unix_time_from_system(),"panel_running":true,"source_session":"fixture"}
		var file := FileAccess.open(ipc.path_join("status.tmp"),FileAccess.WRITE)
		file.store_string(JSON.stringify(status))
		file.close()
		DirAccess.rename_absolute(ipc.path_join("status.tmp"),ipc.path_join("status.json"))
		ambient.tick(delta)
	ipc = original
func _process(delta: float) -> void:
	super._process(delta)
	dock.hide()
	observation_clock += delta
	save_clock += delta
	if observation_clock >= .02:
		observation_clock = 0
		var peak := 0.0
		for color in ambient.target: peak = maxf(peak,maxf(color.r,maxf(color.g,color.b)))
		observations.append({"time":Time.get_unix_time_from_system(),"available":ambient.available,"held":ambient.palette_held,"visible":ambient.visible,"target_peak":peak})
	if save_clock >= 1:
		save_clock = 0
		FileAccess.open(ipc.path_join("ambient-observed.json"),FileAccess.WRITE).store_string(JSON.stringify(observations))
