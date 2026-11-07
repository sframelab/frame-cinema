extends SceneTree
# Sky-only renders for verify_limb.py: space.gdshader with its own default uniforms, bound the way
# starship_room.gd binds it, with no room meshes in front of it. Same renderer and tone curve as the room.
# Environment: STARSHIP_LIMB_OUT (required), STARSHIP_LIMB_SHOTS (JSON [[name, yaw, pitch], ...]),
# STARSHIP_LIMB_SIZE (square px, default 2048, focal size/2), STARSHIP_LIMB_PARAMS (JSON uniform overrides).

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	# This stage's project.godot has no [shader_globals] and it has no room script; the sky shader reads both from globals.
	RenderingServer.global_shader_parameter_add("earth_spin", RenderingServer.GLOBAL_VAR_TYPE_VEC2, Vector2.ZERO)
	RenderingServer.global_shader_parameter_add("earth_gain", RenderingServer.GLOBAL_VAR_TYPE_FLOAT, 1.0)
	var output := OS.get_environment("STARSHIP_LIMB_OUT")
	assert(not output.is_empty())
	DirAccess.make_dir_recursive_absolute(output)
	var size := int(OS.get_environment("STARSHIP_LIMB_SIZE")) if OS.has_environment("STARSHIP_LIMB_SIZE") else 2048
	var shots: Array = JSON.parse_string(OS.get_environment("STARSHIP_LIMB_SHOTS"))
	var overrides: Dictionary = JSON.parse_string(OS.get_environment("STARSHIP_LIMB_PARAMS")) if OS.has_environment("STARSHIP_LIMB_PARAMS") else {}
	var view := SubViewport.new()
	view.size = Vector2i(size, size)
	view.own_world_3d = true
	view.msaa_3d = Viewport.MSAA_2X
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	var material := ShaderMaterial.new()
	material.shader = load("res://starship/space.gdshader")
	material.set_shader_parameter("surface", ImageTexture.create_from_image(load("res://starship/earth-surface.res")))
	material.set_shader_parameter("masks", ImageTexture.create_from_image(load("res://starship/earth-masks.res")))
	material.set_shader_parameter("clouds", ImageTexture.create_from_image(load("res://starship/earth-clouds.res")))
	material.set_shader_parameter("galaxy", ImageTexture.create_from_image(load("res://starship/galaxy.res")))
	for key in overrides:
		var value: Variant = overrides[key]
		material.set_shader_parameter(key, Vector3(value[0], value[1], value[2]) if value is Array else value)
	var sky := Sky.new()
	sky.process_mode = Sky.PROCESS_MODE_QUALITY
	sky.radiance_size = Sky.RADIANCE_SIZE_32
	sky.sky_material = material
	var world := WorldEnvironment.new()
	world.environment = Environment.new()
	world.environment.sky = sky
	world.environment.background_mode = Environment.BG_SKY
	world.environment.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	world.environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	world.environment.tonemap_mode = Environment.TONE_MAPPER_AGX
	world.environment.tonemap_agx_contrast = 1.2
	world.environment.tonemap_exposure = 1.0
	view.add_child(world)
	var eye := Camera3D.new()
	eye.near = 0.04
	eye.far = 100.0
	eye.fov = 90.0
	view.add_child(eye)
	eye.current = true
	for shot in shots:
		eye.rotation_degrees = Vector3(shot[2], shot[1], 0)
		for i in 4:
			await process_frame
		await RenderingServer.frame_post_draw
		assert(view.get_texture().get_image().save_png(output.path_join(str(shot[0]) + ".png")) == OK)
	view.queue_free()
	await process_frame
	print("STARSHIP_LIMB_OK")
	quit()
