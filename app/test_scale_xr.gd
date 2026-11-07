extends "res://cinema.gd"
var age := 0.0
var samples: Array = []
var card: ImageTexture
func _save() -> void: pass
func _update_status() -> void: pass
func _lake_reflection_wanted() -> bool: return environment_index == 7
func _ready() -> void:
	preferences_path = "user://scale-fixture-none.cfg"
	environment_index = 7
	ambient_mode = 3
	light_level = .2
	screen_width = 4.2
	super._ready()
	var picture := Image.create(384,216,false,Image.FORMAT_RGBA8)
	picture.fill(Color(.2,.35,.5))
	picture.fill_rect(Rect2i(20,30,110,100),Color(.8,.5,.2))
	picture.generate_mipmaps()
	card = ImageTexture.create_from_image(picture)
	var plane := MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(3360,1890)
	plane.mesh = quad
	plane.position = _screen_center()
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = card
	plane.material_override = material
	seat.add_child(plane)
func _process(delta: float) -> void:
	super._process(delta)
	age += delta
	room.contents.water_material.set_shader_parameter("screen_picture",card)
	room.contents.water_material.set_shader_parameter("screen_size",Vector2(3360,1890))
	room.contents.water_material.set_shader_parameter("screen_active",true)
	assert(not ambient.visible and _effective_ambient_mode() == 0)
	if age > 3 and age < 10 and Engine.get_process_frames()%4 == 0:
		samples.append({"time":Time.get_unix_time_from_system(),"gpu_ms":_scene_gpu_ms()})
	if age < 11: return
	set_process(false)
	for width in [3.2,5.4,4.2]:
		_set_screen_width(width)
		assert(absf(_display_screen_width()/(_screen_center()-Vector3(0,1.65,0)).length()-width/Vector3(0,.45,-4.5).length()) < .000001)
		assert(_screen_center().y-_display_screen_width()*9/32 > -1280)
		# Lower edge just under the horizon (far shore), or the "Lower" choice.
		for height in ALPINE_BOTTOM_DEG.size():
			_set_alpine_height(height)
			assert(absf(rad_to_deg(atan((_screen_center().y-1.65-_display_screen_width()*9/32)/3600))+ALPINE_BOTTOM_DEG[height]) < 0.01)
			room.contents.update_picture(self,0)
			assert(room.contents.water_material.get_shader_parameter("screen_center").is_equal_approx(_alpine_reflection_screen()[0]))
		_set_alpine_height(0)
	assert(room.contents.mip_chain_bytes(Vector2i(384,216)) == Image.create(384,216,true,Image.FORMAT_RGBA8).get_data().size())
	_render_ui("room")
	ui.refresh_settings()
	for control in ui_viewport.find_children("*","Button",true,false):
		if control.get_meta("setting","") in ["ambient","brightness"]: assert(control.disabled)
	_set_ambient_mode(2)
	assert(ambient_mode == 3)
	assert(dock.position == Vector3(0,.67,-1.65))
	_set_environment(5)
	assert(_effective_ambient_mode() == 3 and _display_screen_width() == 4.2)
	_set_environment(7)
	FileAccess.open(OS.get_environment("FRAME_SCALE_OUT").path_join("room-samples.json"),FileAccess.WRITE).store_string(JSON.stringify({"samples":samples,"angular_size":true,"forward_gaze":true,"nearby_ui":true,"reflection_geometry":true,"alpine_glow_off":true,"preferences_restored":true},"  "))
	print("SCALE_XR_OK")
	get_tree().quit()
