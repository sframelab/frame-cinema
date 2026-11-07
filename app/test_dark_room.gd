extends "res://cinema.gd"
func _save() -> void: pass
func _update_status() -> void: pass
func _ready() -> void:
	preferences_path = "user://polish-0430-nonexistent.cfg"
	super._ready()
	stereo_mode = 3
	for index in [3,4,6,7,5]:
		_set_environment(index)
		assert(_effective_stereo_mode() == (3 if index == 5 else 0))
		if index != 5:
			assert(not stereo_controller.allowed)
			_set_stereo_mode(2)
			assert(stereo_mode == 3)
		_write_presentation()
		var packet := FileAccess.get_file_as_string(ipc.path_join("stereo-control.txt")).split(" ",false)
		assert(int(packet[4]) == (3 if index == 5 else 0))
		_render_ui("more")
		var found := 0
		for control in ui_viewport.find_children("*","Button",true,false):
			if control.text in ["Subtle","Normal","Strong"]:
				assert(control.disabled == (index != 5))
				found += 1
		assert(found == 3)
	_set_stereo_mode(2)
	assert(stereo_mode == 2)
	print("DARK_ROOM_STEREO_GATES_OK")
	get_tree().quit()
