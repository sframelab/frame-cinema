extends Node3D

# Numeric IDs are retained so installed Moon/Coast preferences keep their meaning.
# Removed prototype IDs are never built or offered in the interface.
const IDS := ["retired_lake", "retired_gallery", "retired_blue_hour", "lunar_landscape", "coastal_dusk", "dark_room", "desert_alcove", "alpine_night", "starship"]
const NAMES := ["", "", "", "Lunar Landscape", "Coastal Dusk", "Dark Room", "Desert Alcove", "Alpine Night", "Observation Deck"]
const DARK_ROOM := 5
const DESERT := 6
const ALPINE := 7
const STARSHIP := 8
const STARSHIP_ROOT := "res://starship/"
const ALPINE_ROOT := "res://alpine/"
const LUNAR_ROOT := "res://lunar/"
const COAST_ROOT := "res://coast/"
const DESERT_ROOT := "res://desert/"
var room_index := -1
var room_light := 0.55
var world: Environment
var contents: Node3D
var geometry_cache := {}
var meshes := 0
var triangles := 0
var build_ms := 0.0

# 0.4.51: Alpine Night is retired (over the frame budget with its lake and
# reflection); its files remain, but it is never offered or prewarmed.
static func available(index: int) -> bool:
	return index == DARK_ROOM or (index == 3 and FileAccess.file_exists(LUNAR_ROOT + "package.json")) or (index == 4 and FileAccess.file_exists(COAST_ROOT + "package.json")) or (index == DESERT and FileAccess.file_exists(DESERT_ROOT + "package.json")) or (index == STARSHIP and FileAccess.file_exists(STARSHIP_ROOT + "package.json"))

static func available_indices() -> Array[int]:
	var result: Array[int] = []
	for index in [3, 4, DESERT, ALPINE, STARSHIP, DARK_ROOM]:
		if available(index):
			result.append(index)
	return result

static func default_index() -> int:
	return 3 if available(3) else (4 if available(4) else (DESERT if available(DESERT) else DARK_ROOM))

func configure(environment: Environment, index: int, brightness: float) -> void:
	world = environment
	if not available(index):
		index = default_index()
	if room_index != index or contents == null:
		_build(index)
	set_light(brightness)
	refresh_transform()

func refresh_transform() -> void:
	# Rooms with custom sky shaders transform the ray into their own space.
	# Applying Environment.sky_rotation too would rotate those skies twice.
	var custom_sky := is_instance_valid(contents) and contents.has_method("refresh_transform")
	world.sky_rotation = Vector3.ZERO if custom_sky else Vector3(0, global_rotation.y, 0)
	if custom_sky:
		contents.refresh_transform()

func prewarm() -> void:
	var original := room_index
	var brightness := room_light
	for index in available_indices():
		_build(index)
	_build(original)
	set_light(brightness)

func _exit_tree() -> void:
	for cached in geometry_cache.values():
		if is_instance_valid(cached.contents) and cached.contents.get_parent() == null:
			cached.contents.free()
	geometry_cache.clear()

func _build(index: int) -> void:
	var started := Time.get_ticks_usec()
	if is_instance_valid(contents):
		contents.hide()
	room_index = index
	world.tonemap_exposure = 1.0
	if index == 3:
		_build_lunar()
	elif index == 4:
		_build_coast()
	elif index == DESERT:
		_build_desert()
	elif index == ALPINE:
		_build_alpine()
	elif index == STARSHIP:
		_build_starship()
	else:
		world.background_mode = Environment.BG_COLOR
		world.background_color = Color.BLACK
		world.sky = null
		world.fog_enabled = false
		world.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
		world.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
		world.tonemap_mode = Environment.TONE_MAPPER_AGX
		if not geometry_cache.has(DARK_ROOM):
			contents = Node3D.new()
			contents.name = "DarkRoom"
			add_child(contents)
			geometry_cache[DARK_ROOM] = {"contents": contents}
		else:
			contents = geometry_cache[DARK_ROOM].contents
		contents.show()
		meshes = 0
		triangles = 0
	build_ms = (Time.get_ticks_usec() - started) / 1000.0

func _build_lunar() -> void:
	world.background_mode = Environment.BG_COLOR
	world.background_color = Color.BLACK
	world.sky = null
	world.fog_enabled = false
	world.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	world.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	world.tonemap_mode = Environment.TONE_MAPPER_AGX
	world.tonemap_agx_contrast = 1.25
	if geometry_cache.has(3):
		contents = geometry_cache[3].contents
	else:
		contents = load(LUNAR_ROOT + "lunar_room.gd").new()
		contents.name = "LunarLandscape"
		add_child(contents)
		contents.setup(LUNAR_ROOT)
		# Match the artist's horizontal composition to Cinema's forward view.
		# Only yaw changes; the terrain remains level and metre-scale.
		var front: Dictionary = contents.metadata.views[0]
		var forward := -Vector3(front.basis_columns[2][0], front.basis_columns[2][1], front.basis_columns[2][2])
		contents.rotation.y = atan2(forward.x, -forward.z)
		# Lower the lunar foreground; keep the screen and seated view shared by all rooms.
		contents.position.y = 1.65 - float(contents.metadata.source_eye_height_m) - 0.35
		if contents.has_method("place_earth"):
			# Seat space: 32 degrees right of the screen axis, 24 degrees up.
			var azimuth := deg_to_rad(32.0)
			var elevation := deg_to_rad(24.0)
			var seat_direction := Vector3(sin(azimuth) * cos(elevation), sin(elevation), -cos(azimuth) * cos(elevation))
			var to_local := contents.transform.affine_inverse()
			contents.place_earth(to_local * Vector3(0, 1.65, 0), to_local.basis * seat_direction, 600.0, 2.7)
		geometry_cache[3] = {"contents": contents}
	meshes = contents.get_child_count()
	triangles = int(contents.metadata.triangles) + contents.prop_triangles
	contents.show()

func _build_coast() -> void:
	if geometry_cache.has(4):
		contents = geometry_cache[4].contents
		contents.apply_environment(world)
	else:
		contents = load(COAST_ROOT + "coast_room.gd").new()
		contents.name = "CoastalDusk"
		add_child(contents)
		contents.setup(COAST_ROOT, world)
		geometry_cache[4] = {"contents": contents}
	meshes = contents.get_child_count()
	triangles = contents.triangles
	contents.show()
	contents.refresh_transform()

func set_light(value: float) -> void:
	room_light = clampf(value, 0.03, 1.0)
	if room_index in [3, 4, DESERT, ALPINE, STARSHIP]:
		contents.set_light(room_light)

func _build_desert() -> void:
	if geometry_cache.has(DESERT):
		contents = geometry_cache[DESERT].contents
		contents.apply_environment(world)
	else:
		contents = load(DESERT_ROOT + "desert_room.gd").new()
		contents.name = "DesertAlcove"
		add_child(contents)
		contents.setup(DESERT_ROOT, world)
		geometry_cache[DESERT] = {"contents": contents}
	meshes = contents.get_child_count()
	triangles = contents.triangles
	contents.show()

func _build_alpine() -> void:
	if geometry_cache.has(ALPINE):
		contents = geometry_cache[ALPINE].contents
		contents.apply_environment(world)
	else:
		contents = load(ALPINE_ROOT + "alpine_room.gd").new()
		contents.name = "AlpineNight"
		add_child(contents)
		contents.setup(ALPINE_ROOT, world)
		geometry_cache[ALPINE] = {"contents": contents}
	meshes = contents.get_child_count()
	triangles = contents.triangles
	contents.show()
	contents.refresh_transform()

func _build_starship() -> void:
	if geometry_cache.has(STARSHIP):
		contents = geometry_cache[STARSHIP].contents
		contents.apply_environment(world)
	else:
		contents = load(STARSHIP_ROOT + "starship_room.gd").new()
		contents.name = "ObservationDeck"
		add_child(contents)
		contents.setup(STARSHIP_ROOT, world)
		geometry_cache[STARSHIP] = {"contents": contents}
	meshes = contents.get_child_count()
	triangles = contents.triangles
	contents.show()

func metrics() -> Dictionary:
	var result := {"kind": "dark" if room_index == DARK_ROOM else ("foreground_3d_distant_photo" if room_index == ALPINE else "baked_3d"), "id": IDS[room_index] if room_index >= 0 else "unavailable", "meshes": meshes,
		"triangles": triangles, "lights": 0, "build_ms": snappedf(build_ms, 0.1),
		"material_maps": 0, "missing_maps": [], "room_light": room_light, "panorama": room_index == ALPINE}
	if room_index == STARSHIP and is_instance_valid(contents) and contents.has_method("metrics"):
		result.merge(contents.metrics(), true)
	return result
