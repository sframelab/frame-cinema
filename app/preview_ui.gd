extends SceneTree

# Render the actual app UI with no browser, XR session, saved-settings writes
# or production IPC. Outputs are intentionally ignored local review artifacts.
func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	OS.set_environment("FRAME_CINEMA_IPC", "")
	var output := OS.get_environment("FRAME_CINEMA_PREVIEW_OUT")
	if output.is_empty():
		push_error("Set FRAME_CINEMA_PREVIEW_OUT to the review output directory")
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output)
	var studio := SubViewport.new()
	studio.size = Vector2i(1600, 1000)
	studio.own_world_3d = true
	studio.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(studio)
	var scene: Node3D = load("res://cinema.gd").new()
	scene.preferences_path = output.path_join("unused-preview-preferences.cfg")
	studio.add_child(scene)
	scene.set_process(false)
	scene._recenter()
	var layout := {}
	for page in ["library", "player", "room", "more", "focus"]:
		scene.library_open = page == "library"
		scene.media_state = {"available": true, "page_ready": true, "video": true, "can_control": true, "can_seek": true, "paused": true, "fullscreen": true}
		scene._render_ui(page)
		if page == "player":
			scene.status_label.text = "Paused  ·  1080p  ·  B: controls"
		await process_frame
		await process_frame
		await RenderingServer.frame_post_draw
		scene.ui_viewport.get_texture().get_image().save_png(output.path_join(page + ".png"))
		var controls := []
		for node in scene.ui_viewport.find_children("*", "Button", true, false):
			var logical: Rect2 = node.get_global_rect()
			var scale: Vector2 = Vector2(scene.ui_viewport.size) / scene._ui_size()
			var rect := Rect2(logical.position * scale, logical.size * scale)
			controls.append({"text": node.text, "service": node.get_meta("service_id", ""), "rect": [rect.position.x, rect.position.y, rect.size.x, rect.size.y], "fits": Rect2(Vector2.ZERO, scene._ui_size()).encloses(logical)})
		layout[page] = controls
	for message in ["Cinema not responding · Relaunch from Steam", "Playback not advancing · More → Reload"]:
		scene.ui.update_focus_notice(message)
		await process_frame
		await process_frame
		await RenderingServer.frame_post_draw
		scene.ui_viewport.get_texture().get_image().save_png(output.path_join("focus-" + message.get_slice(" ", 0).to_lower() + ".png"))
	# Review the longest recovery copy in the actual compact dock, including
	# the long provider name; these are visual fixtures, not live device states.
	scene.selected_service = "disneyplus"
	scene.library_open = false
	for message in ["Cinema not responding · Relaunch from Steam", "Service not responding · More → Reopen", "Playback not advancing · More → Reload"]:
		scene.media_state = {}
		scene._render_ui("player")
		scene.status_label.text = message
		await process_frame
		await process_frame
		await RenderingServer.frame_post_draw
		scene.ui_viewport.get_texture().get_image().save_png(output.path_join("recovery-" + message.get_slice(" ", 0).to_lower() + ".png"))
	scene.library_open = true
	scene._render_ui("library")
	await process_frame
	await process_frame
	await RenderingServer.frame_post_draw
	studio.get_texture().get_image().save_png(output.path_join("scene.png"))
	var report := FileAccess.open(output.path_join("layout.json"), FileAccess.WRITE)
	report.store_string(JSON.stringify(layout, "  "))
	report.close()
	scene.queue_free()
	await process_frame
	print("UI preview saved; no production session or preferences used")
	quit()
