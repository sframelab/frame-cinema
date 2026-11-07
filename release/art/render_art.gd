extends SceneTree

# Release artwork renders (PC, not shipped): each room from the seat at 3840 px,
# menus hidden, the screen showing a neutral stand-in frame (Poly Haven CC0
# "spruit sunrise"). Output: FRAME_CINEMA_ART_OUT/<room>-<shot>.png.
# Usage: godot --path <project> --rendering-method mobile --xr-mode off --script <this>
const SHOTS := [
	# [room, name, pitch, yaw, fov, size, screen width (app range 3.2-5.4 m)].
	# Lunar shots keep the Earth in frame; the capsule and header use the
	# smallest screen so the title sits over the lunar ground, not the picture.
	[4, "coast-wide", -3.0, 8.0, 70.0, Vector2i(3840, 2160), 5.4],
	[6, "desert-wide", -4.0, 0.0, 70.0, Vector2i(3840, 2160), 5.4],
	[3, "lunar-wide", 6.0, 0.0, 62.0, Vector2i(3840, 2160), 5.4],
	# Library art: seen from just above the ground ~3 m behind the seat, so
	# black sky shows under the screen (default size, its bottom ~0.9 m up)
	# and its glow pools on the regolith: the screen visibly floats.
	[3, "lunar-hero", 8.0, 0.0, 46.0, Vector2i(3840, 1240), 4.2, Vector3(0.0, 0.35, 3.0)],
	[3, "lunar-capsule", 10.0, -6.0, 75.0, Vector2i(1200, 1800), 3.2, Vector3(0.0, 0.35, 3.0)],
	[3, "lunar-header", 9.0, -3.0, 56.0, Vector2i(1840, 860), 4.2, Vector3(0.0, 0.35, 3.0)],
	[5, "dark-wide", -2.0, 0.0, 70.0, Vector2i(3840, 2160), 5.4],
]

func _edge_color(picture: Image, region: Rect2i) -> Color:
	var sum := Color(0, 0, 0)
	var count := 0
	for y in range(region.position.y, region.end.y, 4):
		for x in range(region.position.x, region.end.x, 4):
			sum += picture.get_pixel(x, y).srgb_to_linear()
			count += 1
	return sum / float(maxi(count, 1))

func _light_from_picture(scene: Node3D, picture: Image) -> void:
	var ambient = scene.ambient
	var w := picture.get_width()
	var h := picture.get_height()
	# Zones run edge by edge (top, right, bottom, left), SEGMENTS per edge.
	var segments: int = ambient.ZONES / 4
	for edge in 4:
		for segment in segments:
			var t0 := float(segment) / segments
			var t1 := float(segment + 1) / segments
			var region: Rect2i
			match edge:
				0: region = Rect2i(int(w * t0), 0, int(w * (t1 - t0)), h / 6)
				1: region = Rect2i(w * 5 / 6, int(h * t0), w / 6, int(h * (t1 - t0)))
				2: region = Rect2i(int(w * t0), h * 5 / 6, int(w * (t1 - t0)), h / 6)
				_: region = Rect2i(0, int(h * t0), w / 6, int(h * (t1 - t0)))
			ambient.target[edge * segments + segment] = _edge_color(picture, region)
	scene.ambient_mode = 3
	scene.ambient_brightness = 0.7
	for step in 120:
		ambient.advance(0.1, 3, 0.7)
	# Keep only the light cast onto the ground: the halo/haze rings model the
	# glow around the screen as seen from the seat and read as a fuzzy box here.
	ambient.halo.visible = false
	ambient.haze.visible = false

func _initialize() -> void:
	call_deferred("run")

func settle(frames: int = 12) -> void:
	for i in frames:
		await process_frame
	await RenderingServer.frame_post_draw

func run() -> void:
	OS.set_environment("FRAME_CINEMA_IPC", "")
	var output := OS.get_environment("FRAME_CINEMA_ART_OUT")
	if output.is_empty():
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output)
	var studio := SubViewport.new()
	studio.size = Vector2i(3840, 2160)
	studio.own_world_3d = true
	studio.msaa_3d = Viewport.MSAA_4X
	studio.use_debanding = true
	studio.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(studio)
	var scene: Node3D = load("res://cinema.gd").new()
	scene.preferences_path = output.path_join("unused-art-preferences.cfg")
	studio.add_child(scene)
	scene.set_process(false)
	scene._recenter()
	scene.camera.far = 4000.0
	var still := Image.load_from_file(ProjectSettings.globalize_path("res://environments/spruit_sunrise.jpg"))
	var crop := Rect2i(int(still.get_width() * 0.30), int(still.get_height() * 0.36), int(still.get_width() * 0.22), 0)
	crop.size.y = int(crop.size.x * 9.0 / 16.0)
	still = still.get_region(crop)
	var movie := MeshInstance3D.new()
	movie.mesh = QuadMesh.new()
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = ImageTexture.create_from_image(still)
	movie.material_override = material
	scene.seat.add_child(movie)
	var seat_eye: Vector3 = scene.camera.position
	for shot in SHOTS:
		scene._set_environment(shot[0])
		await settle(4)
		scene.screen_width = shot[6]
		movie.position = scene._screen_center()
		movie.mesh.size = Vector2(scene._display_screen_width(), scene._display_screen_width() * 9.0 / 16.0)
		scene.dock.visible = false
		if scene.get("ui_viewport") != null:
			for node in scene.find_children("*", "MeshInstance3D", true, false):
				if node != movie and node.get_parent() == scene.dock:
					node.visible = false
		studio.size = shot[5]
		scene.camera.rotation_degrees = Vector3(shot[2], shot[3], 0)
		scene.camera.fov = shot[4]
		if shot.size() > 7:
			# Outside view (hero): the camera stands back from the seat so the
			# screen is seen hovering over the ground; the picture keeps the
			# real screen's orientation, facing the seat. The app's own screen
			# glow ("Fuller glow") is driven from the picture's edge colours, as
			# the live sampler would, so its light spills onto the ground below.
			scene.camera.position = shot[7]
			movie.basis = Basis()
			_light_from_picture(scene, still)
		else:
			# Seat views: keep the stand-in picture parallel to the image plane
			# (QuadMesh faces +Z, the camera looks down -Z): a clean rectangle
			# where off-axis perspective read as a crooked screen on cover art.
			scene.camera.position = seat_eye
			movie.global_basis = scene.camera.global_basis
		await settle()
		studio.get_texture().get_image().save_png(output.path_join(str(shot[1]) + ".png"))
		print("ART ", shot[1])
	print("RENDER_ART_OK")
	quit()
