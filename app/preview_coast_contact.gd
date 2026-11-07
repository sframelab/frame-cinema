extends SceneTree

var view: SubViewport
var scene: Node3D
var eye: Camera3D
var output: String

func _initialize() -> void: call_deferred("run")

func capture(name: String) -> void:
	for frame in 4: await process_frame
	await RenderingServer.frame_post_draw
	view.get_texture().get_image().save_png(output.path_join(name+".png"))

func run() -> void:
	OS.set_environment("FRAME_CINEMA_IPC", "")
	output = OS.get_environment("FRAME_CINEMA_TEST_OUT")
	DirAccess.make_dir_recursive_absolute(output)
	view = SubViewport.new()
	view.size = Vector2i(1600,1000)
	view.own_world_3d = true
	view.msaa_3d = Viewport.MSAA_4X
	view.use_debanding = true
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	scene = load("res://cinema.gd").new()
	scene.preferences_path = output.path_join("fixture-settings.cfg")
	view.add_child(scene)
	scene.set_process(false)
	scene._set_environment(4)
	for frame in 2: await process_frame
	scene.library_open = false
	scene._render_ui("focus")
	scene.dock.hide()
	scene.screen_width = 5.4
	var screen := MeshInstance3D.new()
	screen.mesh = QuadMesh.new()
	screen.mesh.size = Vector2(5.4,5.4*9.0/16.0)
	screen.position = scene._screen_center()
	var black := StandardMaterial3D.new()
	black.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	black.albedo_color = Color(.012,.012,.012)
	screen.material_override = black
	scene.seat.add_child(screen)
	eye = Camera3D.new()
	eye.fov = 78
	eye.far = 1800
	scene.seat.add_child(eye)
	eye.current = true
	var glow: Node3D = scene.ambient
	glow.colors.fill(Color(.12,.35,.65))
	glow.target = glow.colors.duplicate()
	glow.advance(0.0,2,.75)
	for pose in [["front", Vector3(0,1.65,0)], ["left-eye",Vector3(-.032,1.65,0)], ["right-eye",Vector3(.032,1.65,0)], ["lean", Vector3(.35,1.9,.1)]]:
		eye.position = pose[1]
		eye.look_at(scene.seat.to_global(Vector3(0,1.6,-4.5)))
		for mode in ["baseline", "fixed", "no-glow"]:
			glow.contact_room = -1
			glow.advance(0.0,2,.75)
			glow.visible = mode != "no-glow"
			if mode == "baseline":
				for material in [glow.material,glow.haze_material]:
					material.set_shader_parameter("terrain_contact_enabled",true)
					material.set_shader_parameter("ground_fade",Vector2(-100,-99))
			await capture(pose[0]+"-"+mode)
	print("COAST_CONTACT_PREVIEW_OK")
	view.queue_free()
	await process_frame
	quit()
