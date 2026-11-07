extends SceneTree

# One still of a room with no screen and no menus (PC, not shipped): the picture the Observation Deck's
# screen shows in the Steam library art. Run from the app project with the room index and view:
#   PASS_OUT=<png> PASS_ROOM=4 PASS_YAW=-30 PASS_PITCH=-3 PASS_FOV=55 \
#   godot --path <project> --rendering-method mobile --xr-mode off --script <this>
# Room 4 is the Coast; the library art's still is the Coast at yaw -30, pitch -3, fov 55, 2400x1350.
func _initialize() -> void:
	call_deferred("run")

func settle(frames: int = 12) -> void:
	for i in frames:
		await process_frame
	await RenderingServer.frame_post_draw

func run() -> void:
	OS.set_environment("FRAME_CINEMA_IPC", "")
	var output := OS.get_environment("PASS_OUT")
	var studio := SubViewport.new()
	studio.size = Vector2i(2400, 1350)
	studio.own_world_3d = true
	studio.msaa_3d = Viewport.MSAA_4X
	studio.use_debanding = true
	studio.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(studio)
	var scene: Node3D = load("res://cinema.gd").new()
	scene.preferences_path = output.get_base_dir().path_join("unused-preferences.cfg")
	studio.add_child(scene)
	scene.set_process(false)
	scene._recenter()
	scene.camera.far = 4000.0
	scene._set_environment(int(OS.get_environment("PASS_ROOM")))
	await settle(6)
	scene.dock.visible = false
	for node in scene.find_children("*", "MeshInstance3D", true, false):
		if node.get_parent() == scene.dock:
			node.visible = false
	scene.camera.rotation_degrees = Vector3(float(OS.get_environment("PASS_PITCH")), float(OS.get_environment("PASS_YAW")), 0)
	scene.camera.fov = float(OS.get_environment("PASS_FOV"))
	await settle(20)
	studio.get_texture().get_image().save_png(output)
	print("ROOM_STILL_OK")
	quit()
