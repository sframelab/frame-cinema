extends RefCounted

class PlacementFixture:
	extends "res://cinema.gd"
	var simulated_session := OpenXRInterface.SESSION_STATE_SYNCHRONIZED
	func _ready() -> void:
		pass
	func _process(_delta: float) -> void:
		pass
	func _placement_session_state() -> int:
		return simulated_session

func run(scene: Node3D, check: Callable) -> void:
	var request: int = scene.source_request
	scene._set_environment(0)
	await scene.get_tree().process_frame
	var lake: Node3D = scene.room.contents
	var metrics: Dictionary = scene.room.metrics()
	check.call(metrics.kind == "modeled_3d" and not metrics.panorama and metrics.missing_maps.is_empty(), "modeled rooms load their verified surface maps and optimized trees")
	check.call(metrics.triangles > 50000 and metrics.triangles < 450000, "outdoor geometry stays within the explicit pre-device triangle budget")
	var bank: MeshInstance3D = lake.find_child("WoodedBank", false, false)
	var trees: Array = lake.find_children("Pine*", "MeshInstance3D", false, false)
	var trees_on_land := bank != null and trees.size() == 24
	for tree in trees:
		# The bank's fully emerged central ellipse contains every tree base.
		trees_on_land = trees_on_land and Vector2(tree.position.x / 49.0, (tree.position.z - 26.0) / 34.0).length() < 0.73
	check.call(trees_on_land, "every tree base lies on the emerged bank instead of open water")
	scene._set_environment(1)
	await scene.get_tree().process_frame
	var gallery: Node3D = scene.room.contents
	var old_lights_hidden := true
	for light in scene.room.geometry_cache[0].lights:
		old_lights_hidden = old_lights_hidden and not light.is_visible_in_tree()
	check.call(gallery != lake and not lake.is_visible_in_tree() and gallery.is_visible_in_tree() and old_lights_hidden, "switching rooms hides the old geometry and all its lights")
	scene._set_environment(2)
	await scene.get_tree().process_frame
	check.call(scene.room.contents == lake and not gallery.is_visible_in_tree(), "Blue Hour reuses the prepared lake graph without rebuilding meshes")
	scene._set_environment(0)
	await scene.get_tree().process_frame
	check.call(scene.room.contents == lake and scene.source_request == request, "room changes reuse cached geometry without touching the video source")
	var old_light: float = scene.light_level
	scene.light_level = 0.55
	scene.library_open = false
	scene._render_ui("player")
	var full_energy: float = scene.room.lights[0].light_energy
	scene._focus_screen()
	await scene.get_tree().process_frame
	check.call(scene.room.room_light <= 0.12 and scene.room.lights[0].light_energy < full_energy * 0.3 and scene.room.water.get_shader_parameter("room_light") <= 0.12, "Focus dims actual 3D lighting and water, not just the sky")
	scene._show_controls()
	await scene.get_tree().process_frame
	check.call(is_equal_approx(scene.room.lights[0].light_energy, full_energy), "leaving Focus restores room lighting exactly")
	scene.light_level = old_light
	scene._apply_room_light()
	var active_count := 0
	for child in scene.room.get_children():
		if child.is_visible_in_tree():
			active_count += 1
	check.call(active_count == 1 and scene.room.get_child_count() == 2 and scene.room.geometry_cache.size() == 2, "repeated environment switches keep one visible graph and two bounded cached layouts")
	_test_placement(scene.get_tree(), check)

func _test_placement(tree: SceneTree, check: Callable) -> void:
	var fixture := PlacementFixture.new()
	fixture.camera = Camera3D.new()
	fixture.origin = XROrigin3D.new()
	fixture.add_child(fixture.origin)
	fixture.seat = Node3D.new()
	fixture.world = WorldEnvironment.new()
	fixture.world.environment = Environment.new()
	fixture.origin.add_child(fixture.camera)
	fixture.add_child(fixture.seat)
	fixture.add_child(fixture.world)
	tree.root.add_child(fixture)
	fixture.xr_active = true
	fixture.camera.position = Vector3(2, 1.85, 4)
	fixture.camera.rotation.y = 0.6
	var head := XRPositionalTracker.new()
	head.name = "head"
	head.type = XRServer.TRACKER_HEAD
	XRServer.add_tracker(head)
	fixture._recenter()
	check.call(fixture.placement_pending and not fixture.placed and fixture.recenter_request == 0, "launching without a head pose keeps recenter pending and publishes no placement")
	head.set_pose("default", Transform3D.IDENTITY, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_HIGH)
	fixture._try_recenter()
	check.call(not fixture.placed, "a cached pose while the session is unfocused cannot commit startup placement")
	fixture.simulated_session = OpenXRInterface.SESSION_STATE_FOCUSED
	head.set_pose("default", Transform3D.IDENTITY, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_NONE)
	fixture._try_recenter()
	check.call(not fixture.placed, "a retained head transform with no tracking confidence cannot commit placement")
	head.set_pose("default", Transform3D.IDENTITY, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_LOW)
	fixture.camera.position = Vector3(-1, 1.2, -2)
	fixture._try_recenter()
	check.call(not fixture.placed and fixture.placement_pending, "inferred head position keeps placement pending until full tracking returns")
	fixture.camera.position = Vector3(2, 1.85, 4)
	head.set_pose("default", Transform3D.IDENTITY, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_HIGH)
	fixture._try_recenter()
	check.call(fixture.placed and not fixture.placement_pending and fixture.seat.position.is_equal_approx(Vector3(2, 0.2, 4)) and is_equal_approx(fixture.seat.rotation.y, 0.6), "fresh focused tracking places the room at the real head position and yaw")
	var original: Transform3D = fixture.seat.transform
	fixture.placement_session = "fixture-scene"
	fixture.ipc = (OS.get_environment("FRAME_CINEMA_TEST_OUT") if not OS.get_environment("FRAME_CINEMA_TEST_OUT").is_empty() else OS.get_user_data_dir()).path_join("placement-wire")
	DirAccess.make_dir_recursive_absolute(fixture.ipc)
	head.set_pose("default", fixture.camera.transform, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_HIGH)
	fixture._write_placement()
	var packet := FileAccess.get_file_as_string(fixture.ipc.path_join("placement.txt")).split(" ", false)
	var expected: Vector3 = fixture.seat.to_global(Vector3(0, 2.1, -4.5))
	check.call(packet.size() == 35 and packet[0] == "FCPL2" and packet[1] == "fixture-scene" and int(packet[6]) == 1 and Vector3(float(packet[26]), float(packet[30]), float(packet[34])).is_equal_approx(expected), "placement producer serializes the actual rotated scene anchor and tracking state")
	fixture.camera.position.x += 0.5
	head.set_pose("default", fixture.camera.transform, Vector3.ZERO, Vector3.ZERO, XRPose.XR_TRACKING_CONFIDENCE_HIGH)
	fixture._write_placement()
	var moved := FileAccess.get_file_as_string(fixture.ipc.path_join("placement.txt")).split(" ", false)
	check.call(packet.slice(23) == moved.slice(23) and packet[3] == moved[3] and packet[14] != moved[14], "head motion updates calibration input without rewriting the screen anchor")
	var before_head: Transform3D = fixture.camera.global_transform
	var revision: int = fixture.recenter_request
	var delta := Transform3D(Basis(Vector3.UP, 0.7), Vector3(0.6, -0.2, 0.4))
	fixture.placement_reference = fixture.origin.global_transform * XRServer.get_reference_frame()
	fixture._apply_reference_delta(delta)
	fixture.camera.transform = delta.affine_inverse() * before_head
	check.call(fixture.camera.global_transform.is_equal_approx(before_head) and fixture.seat.transform.is_equal_approx(original) and fixture.recenter_request == revision and fixture.placement_generation == 1, "valid runtime origin delta preserves physical head and screen without recenter or generation change")
	var second := Transform3D(Basis(Vector3.RIGHT, -0.15), Vector3(-0.3, 0.1, 0.2))
	fixture._apply_reference_delta(second)
	fixture.camera.transform = second.affine_inverse() * fixture.camera.transform
	check.call(fixture.camera.global_transform.is_equal_approx(before_head) and fixture.reference_preserved == 2, "ordered noncommuting runtime deltas preserve world continuity")
	head.invalidate_pose("default")
	fixture.camera.position.x = 7
	fixture._recenter()
	check.call(fixture.placement_pending and fixture.seat.transform.is_equal_approx(original), "manual recenter during tracking loss retains the existing room until tracking returns")
	fixture._write_placement()
	packet = FileAccess.get_file_as_string(fixture.ipc.path_join("placement.txt")).split(" ", false)
	check.call(int(packet[6]) == 0, "tracking loss publishes an unusable pose even when camera retains its transform")
	fixture._reference_space_reset()
	check.call(fixture.placement_generation == 2 and fixture.seat.transform.is_equal_approx(original) and fixture.recenter_request == revision, "unknown reference delta requests mapping recovery without choosing a new screen location")
	DirAccess.remove_absolute(fixture.ipc.path_join("placement.txt"))
	DirAccess.remove_absolute(fixture.ipc)
	XRServer.remove_tracker(head)
	fixture.free()
