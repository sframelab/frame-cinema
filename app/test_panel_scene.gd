extends "res://cinema.gd"
var fixture_age := 0.0
var fixture_started := 0
var stage := -1
func _save() -> void: pass
func _ready() -> void:
	preferences_path = "user://panel-fixture-none.cfg"
	environment_index = 7
	screen_width = 4.2
	ambient_mode = 0
	super._ready()
	fixture_started = Time.get_ticks_msec()
	library_open = false
	focused_view = true
	_render_ui.call_deferred("focus")
func _update_status() -> void:
	_read_panel_status()
func _process(delta: float) -> void:
	super._process(delta)
	fixture_age = (Time.get_ticks_msec() - fixture_started) * 0.001
	var next := mini(3,maxi(0,int((fixture_age-6)/8)))
	if next != stage:
		stage = next
		if stage < 3: _set_screen_width([3.2,4.2,5.4][stage])
		else: _set_environment(5)
	if fixture_age > 39: _quit_recorded("escape_key")
