extends SceneTree

# Isolated offscreen proxy. Never starts XR, changes the live room, or reads
# provider pixels. Does not include browser sampling or headset composition.
func _initialize() -> void: call_deferred("run")

func run() -> void:
	if not OS.get_cmdline_user_args().has("--preview"):
		quit(2)
		return
	OS.set_environment("FRAME_CINEMA_IPC", "")
	OS.set_environment("FRAME_CINEMA_SESSION", "")
	var output := OS.get_environment("FRAME_CINEMA_PREVIEW_OUT")
	if output.is_empty():
		quit(3)
		return
	DirAccess.make_dir_recursive_absolute(output)
	var views: Array[SubViewport] = []
	for side in [-1, 1]:
		var view := SubViewport.new()
		view.size = Vector2i(2160, 2160)
		view.msaa_3d = Viewport.MSAA_4X
		view.use_debanding = true
		view.own_world_3d = views.is_empty()
		if not views.is_empty(): view.world_3d = views[0].find_world_3d()
		view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		root.add_child(view)
		RenderingServer.viewport_set_measure_render_time(view.get_viewport_rid(), true)
		views.append(view)
		var eye := Camera3D.new()
		eye.position = Vector3(side * .032, 1.65, 0)
		eye.fov = 100
		eye.far = 1800
		view.add_child(eye)
		eye.current = true
	var scene: Node3D = load("res://cinema.gd").new()
	scene.preferences_path = output.path_join("fixture-settings.cfg")
	views[0].add_child(scene)
	scene.set_process(false)
	scene.library_open = false
	scene._render_ui("focus")
	scene.dock.hide()
	scene.screen_width = 5.4
	for cache in [scene.ambient.diffusion_view, scene.ambient.field_view]:
		RenderingServer.viewport_set_measure_render_time(cache.get_viewport_rid(), true)
	var results := []
	var room := int(OS.get_environment("FRAME_BUDGET_ROOM"))
	if room not in [3, 4, 5, 6]:
		quit(4)
		return
	scene._set_environment(room)
	for variant in ["off", "glow", "full", "off-repeat"]:
		var totals := []; var caches := []
		for frame in 55:
			for index in 256:
				var value := .5 + .5 * sin(index * .17 + frame * .12)
				scene.ambient.target[index] = Color(.6 * value, .04 + .4 * (1.0 - value), .2 + .2 * value)
			scene.ambient.advance(1.0 / 72.0, 4 if variant in ["glow", "full"] else 0, .75)
			if variant != "full":
				for light in scene.ambient.lights: light.light_energy = 0
			await process_frame
			await RenderingServer.frame_post_draw
			if frame < 20: continue
			var total := 0.0
			for view in views: total += RenderingServer.viewport_get_measured_render_time_gpu(view.get_viewport_rid())
			var cache_ms := 0.0
			if variant in ["glow", "full"]:
				for cache in [scene.ambient.diffusion_view, scene.ambient.field_view]:
					cache_ms += RenderingServer.viewport_get_measured_render_time_gpu(cache.get_viewport_rid())
			if room == 4: total += scene.room.contents.water_renderer.metrics().reflection_gpu_ms
			totals.append(total + cache_ms); caches.append(cache_ms)
		totals.sort(); caches.sort()
		results.append({"variant":variant, "gpu_median_ms":totals[17], "gpu_p95_ms":totals[33], "cache_median_ms":caches[17]})
	var file := FileAccess.open(output.path_join("ambient-room%d.json" % room), FileAccess.WRITE)
	file.store_string(JSON.stringify({"room":scene.room.IDS[room], "engine":Engine.get_version_info().string, "device":RenderingServer.get_video_adapter_name(), "samples":35, "kind":"two 2160-square 4x MSAA offscreen views; simulated changing Reactive palette, brightness 75%, 5.4m screen; no XR/browser capture/compositor; other live app may contend", "results":results}, "  "))
	file.close()
	print("AMBIENT_BUDGET_OK")
	quit()
