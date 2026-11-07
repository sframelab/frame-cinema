extends "res://cinema.gd"
var age := 0.0
var samples: Array = []
var card: ImageTexture
var plane: MeshInstance3D
func _save() -> void: pass
func _update_status() -> void: pass
func _lake_reflection_wanted() -> bool: return environment_index == 7
func _ready() -> void:
	environment_index = 7
	ambient_mode = 0
	light_level = .2
	screen_width = 4.2
	super._ready()
	var picture := Image.create(384,216,false,Image.FORMAT_RGBA8)
	picture.fill(Color(.2,.35,.5))
	picture.fill_rect(Rect2i(20,30,110,100),Color(.8,.5,.2))
	picture.generate_mipmaps()
	card = ImageTexture.create_from_image(picture)
	plane = MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(150,84.375)
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
	room.contents.water_material.set_shader_parameter("screen_active",true)
	# Exercise the actual scaled glow and retain only its paired timing ranges.
	if age > 6:
		ambient.target.fill(Color(.3,.5,.7))
		ambient.advance(delta,2,.5)
	if age > 3 and age < 11 and Engine.get_process_frames()%4 == 0:
		samples.append({"time":Time.get_unix_time_from_system(),"gpu_ms":_scene_gpu_ms(),"glow":age>7})
	if age >= 12:
		set_process(false)
		for width in [3.2,5.4,4.2]:
			var previous_revision := recenter_request
			var previous_center := _screen_center()
			_set_screen_width(width)
			assert(recenter_request > previous_revision or previous_center.is_equal_approx(_screen_center()))
			room.contents.update_picture(self,0.05)
			assert(is_equal_approx(_display_screen_width(),width*250.0/7.0))
			assert(_screen_center().y-_display_screen_width()*9.0/32.0 >= -46.001)
			assert(atan2(_screen_center().y-1.65,104.0) < .065)
			assert(room.contents.water_material.get_shader_parameter("screen_center").is_equal_approx(_screen_center()))
		assert(_browser_reach() == 180)
		ambient._layout(_display_screen_width(),1.3)
		assert(is_equal_approx(ambient.halo.scale.x,250.0/7.0))
		assert(ambient.halo.position.z < _screen_center().z)
		assert(is_equal_approx(ambient.material.get_shader_parameter("screen_size").x,4.2))
		library_open = true
		_render_ui("library")
		assert(dock.position == Vector3(0,2.1,-4.5))
		_show_room()
		await get_tree().process_frame
		assert(dock.position == Vector3(0,.67,-1.65))
		var alpine = room.contents
		_set_environment(5)
		assert(_display_screen_width() == 4.2 and _screen_center() == Vector3(0,2.1,-4.5))
		assert(not alpine.is_visible_in_tree() and not get_viewport().use_hdr_2d)
		_set_environment(7)
		assert(room.contents == alpine and is_equal_approx(_display_screen_width(),150.0))
		FileAccess.open(OS.get_environment("FRAME_IMMERSIVE_OUT").path_join("room-samples.json"),FileAccess.WRITE).store_string(JSON.stringify({"samples":samples,"room_switch":true,"screen_sizes":true,"nearby_ui":true,"reflection_geometry":true},"  "))
		print("IMMERSIVE_ROOM_XR_OK")
		get_tree().quit()
