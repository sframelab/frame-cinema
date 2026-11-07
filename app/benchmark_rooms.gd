extends SceneTree

# Brief, off-head stereo-workload proxy. Does not establish runtime XR frame
# pacing, browser contention, thermal stability or physical headset comfort.
func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var output := OS.get_environment("FRAME_CINEMA_PREVIEW_OUT")
	if output.is_empty():
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output)
	var views: Array[SubViewport] = []
	var eyes: Array[Camera3D] = []
	for side in [-1, 1]:
		var view := SubViewport.new()
		view.size = Vector2i(2160, 2160)
		view.msaa_3d = Viewport.MSAA_4X
		view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		view.own_world_3d = views.is_empty()
		if not views.is_empty():
			view.world_3d = views[0].find_world_3d()
		root.add_child(view)
		RenderingServer.viewport_set_measure_render_time(view.get_viewport_rid(), true)
		views.append(view)
		var eye := Camera3D.new()
		eye.fov = 100
		eye.far = 1800
		eye.position = Vector3(side * 0.032, 1.65, 0)
		view.add_child(eye)
		eye.current = true
		eyes.append(eye)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	views[0].add_child(environment)
	var room: Node3D = load("res://cinema_rooms.gd").new()
	views[0].add_child(room)
	room.configure(environment.environment, 0, 0.55)
	room.prewarm()
	var reports := []
	for index in 3:
		room.configure(environment.environment, index, 0.55)
		if not room.missing_materials.is_empty():
			push_error("Incomplete room assets")
			quit(3)
			return
		for facing in [0, 180]:
			for eye in eyes:
				eye.rotation_degrees.y = facing
			var samples: Array[float] = []
			var cpu: Array[float] = []
			var draw_calls := 0
			var per_view_calls := [0, 0]
			for frame in 55:
				await process_frame
				await RenderingServer.frame_post_draw
				if frame < 20:
					continue
				var gpu_ms := 0.0
				var cpu_ms := RenderingServer.get_frame_setup_time_cpu()
				var calls := 0
				for view_index in views.size():
					var view := views[view_index]
					var rid := view.get_viewport_rid()
					gpu_ms += RenderingServer.viewport_get_measured_render_time_gpu(rid)
					cpu_ms += RenderingServer.viewport_get_measured_render_time_cpu(rid)
					var count := RenderingServer.viewport_get_render_info(rid, RenderingServer.VIEWPORT_RENDER_INFO_TYPE_VISIBLE, RenderingServer.VIEWPORT_RENDER_INFO_DRAW_CALLS_IN_FRAME)
					calls += count
					per_view_calls[view_index] = maxi(per_view_calls[view_index], count)
				samples.append(gpu_ms)
				cpu.append(cpu_ms)
				draw_calls = maxi(draw_calls, calls)
			samples.sort()
			cpu.sort()
			if per_view_calls.min() < 2:
				push_error("Both benchmark views must draw scene geometry")
				quit(4)
				return
			reports.append({"room": room.IDS[index], "facing": facing, "samples": samples.size(), "gpu_ms_median": samples[17], "gpu_ms_p95": samples[33], "cpu_render_ms_p95": cpu[33], "draw_calls_max": draw_calls, "per_view_draw_calls_max": per_view_calls, "switch_cpu_ms": room.build_ms})
	var file := FileAccess.open(output.path_join("room-benchmark.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"engine": Engine.get_version_info().string, "os": OS.get_name(), "renderer": RenderingServer.get_current_rendering_method(), "device": RenderingServer.get_video_adapter_name(), "kind": "two separate 2160-square views; 4x MSAA; no XR/browser; short proxy only", "samples": reports}, "  "))
	file.close()
	for view in views:
		view.queue_free()
	await process_frame
	print("ROOM_BENCHMARK_OK")
	quit()
