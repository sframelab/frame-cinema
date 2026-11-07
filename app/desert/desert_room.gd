extends Node3D

var metadata: Dictionary
var materials: Array[ShaderMaterial] = []
var sky_material: ShaderMaterial
var triangles := 0
var age := 0.0
var saved_basis := Basis(Vector3.ZERO, Vector3.ZERO, Vector3.ZERO)
var sky_resource: Sky
var drift_material: ShaderMaterial

static func mesh_file(path: String) -> ArrayMesh:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null and file.get_32() == 0x524f434b)
	var count := file.get_32()
	var indices := file.get_32()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_NORMAL] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_TANGENT] = file.get_buffer(count * 16).to_float32_array()
	arrays[Mesh.ARRAY_TEX_UV] = file.get_buffer(count * 8).to_vector2_array()
	arrays[Mesh.ARRAY_INDEX] = file.get_buffer(indices * 4).to_int32_array()
	assert(file.get_position() == file.get_length())
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

static func texture_file(path: String) -> ImageTexture:
	var image: Image = load(path)
	assert(image != null and image.is_compressed())
	return ImageTexture.create_from_image(image)

static func pole_colors(path: String) -> Array[Vector3]:
	# Equirectangular longitude collapses to one direction at either pole.
	# The compressed source's first two rows contain a dark stitching edge.
	# Reconstruct each pole from the adjoining 0.25–0.5 degree ring in linear
	# HDR, once at load. Averaging row zero itself would preserve that spot.
	var image: Image = load(path).duplicate()
	if image.is_compressed():
		assert(image.decompress() == OK)
	var result: Array[Vector3] = []
	for side in 2:
		var sum := Vector3.ZERO
		for offset in range(3, 6):
			var row := offset if side == 0 else image.get_height() - 1 - offset
			for x in image.get_width():
				var value := image.get_pixel(x, row)
				sum += Vector3(value.r, value.g, value.b)
		result.append(sum / float(image.get_width() * 3))
	return result

func setup(prefix: String, world: Environment) -> void:
	metadata = JSON.parse_string(FileAccess.get_file_as_string(prefix + "desert.json"))
	var ground_light := texture_file(prefix + "sheltered-sand-lighting.res")
	var ground_grain := texture_file(prefix + "sheltered-sand-albedo.res")
	var has_detail := metadata.has("detail_revision")
	var fine_grain: ImageTexture = texture_file(prefix + "sand-grain.res") if has_detail else null
	var contact_map: ImageTexture = texture_file(prefix + "sand-contact.res") if has_detail else null
	var ripple_detail: ImageTexture = texture_file(prefix + "ripple-detail.res") if has_detail else null
	var shared := {}
	for asset in metadata.shared:
		shared[asset] = {}
		for kind in ["albedo", "normal"]:
			shared[asset][kind] = texture_file(prefix + str(asset) + "-" + kind + ".res")
	for part in metadata.parts:
		var material := ShaderMaterial.new()
		var is_sand := bool(part.sand)
		material.shader = load(prefix + ("desert_sand.gdshader" if is_sand else "desert_rock.gdshader"))
		if has_detail and str(part.asset) == "namaqualand_boulder_05":
			material.set_shader_parameter("radiance_tint", Vector3(.78,.75,.72))
		if is_sand:
			material.set_shader_parameter("near_radiance", ground_light)
			material.set_shader_parameter("grain_reflectance", ground_grain)
			material.set_shader_parameter("near_surface", str(part.name) == "sheltered-sand")
			material.set_shader_parameter("detail_enabled", has_detail)
			material.set_shader_parameter("mineral_grain", metadata.get("grain_revision", "") == "sand-mineral-color-20261002")
			if has_detail:
				material.set_shader_parameter("fine_grain", fine_grain)
				material.set_shader_parameter("contact_map", contact_map)
				material.set_shader_parameter("ripple_detail", ripple_detail)
		material.set_shader_parameter("radiance", ground_light if str(part.name) == "sheltered-sand" else texture_file(prefix + str(part.name) + "-lighting.res"))
		material.set_shader_parameter("reflectance", ground_grain if str(part.name) == "sheltered-sand" else (texture_file(prefix + str(part.name) + "-albedo.res") if bool(part.sand) else shared[part.asset].albedo))
		material.set_shader_parameter("surface_normal", texture_file(prefix + str(part.name) + "-normal.res") if bool(part.sand) else shared[part.asset].normal)
		if not is_sand:
			var bake: Texture2D = material.get_shader_parameter("radiance")
			var scan: Texture2D = material.get_shader_parameter("reflectance")
			material.set_shader_parameter("detail_ratio", maxf(1.0, float(scan.get_width()) / float(bake.get_width())))
		var columns: Array = part.source_normal_basis_columns
		material.set_shader_parameter("source_normal_basis", Basis(Vector3(columns[0][0], columns[0][1], columns[0][2]), Vector3(columns[1][0], columns[1][1], columns[1][2]), Vector3(columns[2][0], columns[2][1], columns[2][2])))
		var node := MeshInstance3D.new()
		node.name = str(part.name)
		node.mesh = mesh_file(prefix + str(part.name) + ".bin")
		node.material_override = material
		node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(node)
		materials.append(material)
		triangles += int(part.triangles)
	if has_detail:
		var talus := MeshInstance3D.new()
		talus.name = "Weathered fragments at formation feet"
		talus.mesh = mesh_file(prefix + "contact-talus.bin")
		var material := ShaderMaterial.new()
		material.shader = load(prefix + "desert_debris.gdshader")
		material.set_shader_parameter("radiance", ground_light)
		material.set_shader_parameter("reflectance", shared["namaqualand_boulder_05"].albedo)
		talus.material_override = material
		talus.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(talus)
		materials.append(material)
		triangles += int(metadata.detail_triangles)
	var sky_texture := texture_file(prefix + "sky.res")
	for material in materials:
		material.set_shader_parameter("atmosphere_sky", sky_texture)
	var poles := pole_colors(prefix + "sky.res")
	sky_material = ShaderMaterial.new()
	sky_material.shader = load(prefix + "desert_sky.gdshader")
	sky_material.set_shader_parameter("panorama", sky_texture)
	sky_material.set_shader_parameter("north_pole", poles[0])
	sky_material.set_shader_parameter("south_pole", poles[1])
	sky_resource = Sky.new()
	sky_resource.sky_material = sky_material
	apply_environment(world)
	build_sand_drift(prefix)
	set_light(0.55)
	refresh_transform()

func apply_environment(world: Environment) -> void:
	world.sky = sky_resource
	world.background_mode = Environment.BG_SKY
	world.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	world.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	world.tonemap_mode = Environment.TONE_MAPPER_AGX
	world.tonemap_agx_contrast = 1.25
	world.tonemap_exposure = 1.0
	world.fog_enabled = false

func refresh_transform() -> void:
	if global_basis != saved_basis:
		saved_basis = global_basis
		var inverse := global_basis.orthonormalized().inverse()
		sky_material.set_shader_parameter("world_to_room", inverse)

func set_light(level: float) -> void:
	var strength := clampf(level, 0.03, 1.0) / 0.55 * float(metadata.exposure)
	for material in materials:
		material.set_shader_parameter("baked_strength", strength)
	sky_material.set_shader_parameter("brightness", strength)
	if drift_material != null:
		drift_material.set_shader_parameter("brightness", strength)

func build_sand_drift(prefix: String) -> void:
	# A single inexpensive draw transports sparse grains through the exposed
	# entrance as small aggregated wisps. The dunes and sheltered floor are deliberately stationary.
	var mesh := QuadMesh.new()
	mesh.size = Vector2(0.075, 0.009)
	drift_material = ShaderMaterial.new()
	drift_material.shader = load(prefix + "sand_drift.gdshader")
	mesh.material = drift_material
	var batch := MultiMesh.new()
	batch.transform_format = MultiMesh.TRANSFORM_3D
	batch.use_custom_data = true
	batch.mesh = mesh
	batch.instance_count = 384 if metadata.has("detail_revision") else 96
	var random := RandomNumberGenerator.new()
	random.seed = 613309
	for index in batch.instance_count:
		var x := random.randf_range(-3.7, 3.7)
		var z := random.randf_range(-10.4, -7.0)
		var seed_value := random.randf()
		if metadata.has("drift_sites"):
			x=float(metadata.drift_sites[index][0])
			z=float(metadata.drift_sites[index][2])
			seed_value=float(metadata.drift_sites[index][3])
		var y := 0.07 * sin(x * 0.25 - z * 0.12) + 0.10 * sin(-z * 0.18 - 0.6)
		var r := Vector2(x,z).length()
		y += (1.0-exp(-maxf(0.0,r-9.0)/24.0)) * (1.6 + 1.7*sin(-z*0.028+x*0.015) + 1.15*sin(x*0.036+z*0.011))
		if metadata.has("drift_sites"):
			y=float(metadata.drift_sites[index][1])
		batch.set_instance_transform(index, Transform3D(Basis.IDENTITY, Vector3(x, y, z)))
		batch.set_instance_custom_data(index, Color(seed_value,(x+4.0)/8.0,(z+12.0)/8.0,1))
	var node := MultiMeshInstance3D.new()
	node.name = "Entrance sand drift"
	node.multimesh = batch
	node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	node.custom_aabb = AABB(Vector3(-9,-1,-13), Vector3(20,4,8))
	add_child(node)
	triangles += batch.instance_count * 2

func _process(delta: float) -> void:
	if is_visible_in_tree():
		refresh_transform()
		age += delta
		drift_material.set_shader_parameter("animation_time", age)
