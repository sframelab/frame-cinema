extends SceneTree

# Offscreen capture of the actual geometry, plus same-camera thumbnails.
# This script never creates XR, browser processes, input or production IPC.
func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var output := OS.get_environment("FRAME_CINEMA_PREVIEW_OUT")
	if output.is_empty():
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output)
	var view := SubViewport.new()
	view.size = Vector2i(1600, 1000)
	view.own_world_3d = true
	view.msaa_3d = Viewport.MSAA_4X
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	view.add_child(environment)
	var room: Node3D = load("res://cinema_rooms.gd").new()
	view.add_child(room)
	var eye := Camera3D.new()
	eye.fov = 78
	eye.far = 1800
	view.add_child(eye)
	eye.current = true
	var reports := []
	for index in range(room.IDS.size()):
		room.configure(environment.environment, index, 0.55)
		for shot in ["front", "side", "back", "lean", "focus", "recenter"]:
			room.transform = Transform3D.IDENTITY
			environment.environment.sky_rotation = Vector3.ZERO
			eye.position = Vector3(0.35 if shot == "lean" else 0.0, 1.65, 0)
			eye.rotation_degrees = Vector3(-8, 65 if shot == "side" else (180 if shot == "back" else 0), 0)
			if shot == "recenter":
				var placement := Transform3D(Basis(Vector3.UP, PI / 4.0), Vector3(2, 0.2, 4))
				room.transform = placement
				environment.environment.sky_rotation.y = PI / 4.0
				eye.transform = placement * eye.transform
			room.set_light(0.12 if shot == "focus" else 0.55)
			for i in 5:
				await process_frame
			await RenderingServer.frame_post_draw
			var picture := view.get_texture().get_image()
			picture.save_png(output.path_join(room.IDS[index] + "-" + shot + ".png"))
			if shot == "front":
				picture.resize(768, 480, Image.INTERPOLATE_LANCZOS)
				picture.save_png(output.path_join(room.IDS[index] + "-thumb.png"))
		room.transform = Transform3D.IDENTITY
		environment.environment.sky_rotation = Vector3.ZERO
		reports.append(room.metrics())
	var file := FileAccess.open(output.path_join("rooms.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"renderer": RenderingServer.get_current_rendering_method(), "rooms": reports}, "  "))
	file.close()
	view.queue_free()
	await process_frame
	print("ROOM_PREVIEW_OK")
	quit()
