extends Node3D

# Authored seat on the scanned rear ledge, three metres back from the
# original brink. Face along the headlands rather than straight out to sea.
const VIEW_ORIGIN := Vector3(3.0, 0.3532930, 3.0)
const VIEW_YAW := 0.4363323130 # 25 degrees in the source room.

var metadata: Dictionary
var materials: Array[ShaderMaterial] = []
var sky_material: ShaderMaterial
var water_material: ShaderMaterial
var triangles := 0
var age := 0.0
var saved_basis := Basis(Vector3.ZERO, Vector3.ZERO, Vector3.ZERO)
var sky_resource: Sky
var water_renderer: Node

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
	if FileAccess.file_exists(path.trim_suffix(".bin") + ".contact"):
		var mask_bytes := FileAccess.get_file_as_bytes(path.trim_suffix(".bin") + ".contact")
		assert(mask_bytes.size() == count * 4)
		var mask := mask_bytes.to_float32_array()
		assert(mask.size() == count)
		var pairs := PackedVector2Array()
		pairs.resize(count)
		for i in count:
			assert(is_finite(mask[i]) and mask[i] >= 0.0 and mask[i] <= 1.0)
			pairs[i] = Vector2(mask[i], 0.0)
		arrays[Mesh.ARRAY_TEX_UV2] = pairs
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
	var view_basis := Basis(Vector3.UP, -VIEW_YAW)
	transform = Transform3D(view_basis, -(view_basis * VIEW_ORIGIN))
	metadata = JSON.parse_string(FileAccess.get_file_as_string(prefix + "coast.json"))
	var shared := {}
	for asset in metadata.shared:
		shared[asset] = {}
		for kind in ["albedo", "normal"]:
			shared[asset][kind] = texture_file(prefix + str(asset) + "-" + kind + ".res")
	var detail := texture_file(prefix + "rock-detail.res")
	var pebbles := texture_file(prefix + "ground-detail.res")
	for part in metadata.parts:
		var material := ShaderMaterial.new()
		material.set_shader_parameter("rock_detail", detail)
		material.set_shader_parameter("ground_detail", pebbles)
		material.shader = load(prefix + "coast_rock.gdshader")
		var radiance := texture_file(prefix + str(part.name) + "-lighting.res")
		material.set_shader_parameter("radiance", radiance)
		# Restore texture-level detail on parts baked below their rock texture.
		material.set_shader_parameter("detail_ratio", maxf(1.0, float(shared[part.asset].albedo.get_width()) / float(radiance.get_width())))
		material.set_shader_parameter("reflectance", shared[part.asset].albedo)
		material.set_shader_parameter("surface_normal", shared[part.asset].normal)
		if bool(part.get("contact_overlay", false)):
			assert(FileAccess.file_exists(prefix + str(part.name) + ".contact"))
			material.set_shader_parameter("contact_enabled", true)
			material.set_shader_parameter("contact_albedo", texture_file(prefix + str(part.name) + "-contact-albedo.res"))
			material.set_shader_parameter("contact_normal", texture_file(prefix + str(part.name) + "-contact-normal.res"))
		var columns: Array = part.source_normal_basis_columns
		material.set_shader_parameter("source_normal_basis", Basis(Vector3(columns[0][0], columns[0][1], columns[0][2]), Vector3(columns[1][0], columns[1][1], columns[1][2]), Vector3(columns[2][0], columns[2][1], columns[2][2])))
		var node := MeshInstance3D.new()
		node.name = str(part.name)
		# Automatic LODs baked offline (tools/proj/coast_lods.gd) serve the 768 px
		# water mirrors only. The rocks you look at stay at full detail: their
		# per-vertex contact (wet/dirt) mask and shading changed visibly between
		# levels as the view moved (0.4.50).
		var lods := prefix + str(part.name) + ".lod.res"
		node.mesh = load(lods) if ResourceLoader.exists(lods) else mesh_file(prefix + str(part.name) + ".bin")
		node.lod_bias = 1000.0
		node.material_override = material
		node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(node)
		materials.append(material)
		triangles += int(part.triangles)
	var sky_texture := texture_file(prefix + "sky.res")
	var poles := pole_colors(prefix + "sky.res")
	sky_material = ShaderMaterial.new()
	sky_material.shader = load(prefix + "coast_sky.gdshader")
	sky_material.set_shader_parameter("panorama", sky_texture)
	sky_material.set_shader_parameter("north_pole", poles[0])
	sky_material.set_shader_parameter("south_pole", poles[1])
	sky_resource = Sky.new()
	sky_resource.sky_material = sky_material
	apply_environment(world)
	var water := MeshInstance3D.new()
	water.name = "Ocean"
	var plane := PlaneMesh.new()
	plane.size = Vector2(384, 384)
	plane.subdivide_width = 191
	plane.subdivide_depth = 191
	water.mesh = plane
	water.position.y = float(metadata.water_height)
	water.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	water.extra_cull_margin = 1.0
	water_material = ShaderMaterial.new()
	water_material.shader = load(prefix + "coast_water.gdshader")
	water_material.set_shader_parameter("panorama", sky_texture)
	water_material.set_shader_parameter("north_pole", poles[0])
	water_material.set_shader_parameter("south_pole", poles[1])
	var shore := Image.load_from_file(prefix + "shore.png")
	shore.generate_mipmaps()
	water_material.set_shader_parameter("shore", ImageTexture.create_from_image(shore))
	var waves := Image.load_from_file(prefix + "waves.png")
	waves.generate_mipmaps()
	water_material.set_shader_parameter("waves", ImageTexture.create_from_image(waves))
	water.material_override = water_material
	add_child(water)
	triangles += 192 * 192 * 2
	# Flat far field shares the shader and meets the zero-displacement grid edge.
	for region in [Vector4(0, -1096, 4000, 1808), Vector4(0, 1096, 4000, 1808), Vector4(-1096, 0, 1808, 384), Vector4(1096, 0, 1808, 384)]:
		var far := MeshInstance3D.new()
		var patch := PlaneMesh.new()
		patch.size = Vector2(region.z, region.w)
		# Bake the offset into vertices so every patch samples the same wave field.
		var arrays := patch.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		for index in vertices.size():
			vertices[index] += Vector3(region.x, 0, region.y)
		arrays[Mesh.ARRAY_VERTEX] = vertices
		var geometry := ArrayMesh.new()
		geometry.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
		far.mesh = geometry
		far.position.y = water.position.y
		far.material_override = water_material
		far.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		far.name = "DistantOcean"
		add_child(far, true)
		triangles += 2
	set_light(0.55)
	refresh_transform()
	if FileAccess.file_exists(prefix + "water/contact.json"):
		water_renderer = load(prefix + "coastal_water.gd").new()
		water_renderer.name = "CoastalWater"
		add_child(water_renderer)
		water_renderer.setup(self, world, prefix + "water/")

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
		water_material.set_shader_parameter("world_to_room", inverse)

func set_light(level: float) -> void:
	var strength := clampf(level, 0.03, 1.0) / 0.55 * float(metadata.exposure)
	for material in materials:
		material.set_shader_parameter("baked_strength", strength)
	sky_material.set_shader_parameter("brightness", strength)
	water_material.set_shader_parameter("brightness", strength)

func _process(delta: float) -> void:
	if is_visible_in_tree():
		refresh_transform()
		age += delta
		water_material.set_shader_parameter("animation_time", age)
