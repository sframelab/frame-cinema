extends Node3D

# Reusable baked geometry; environment settings and XR ownership remain in Cinema.
var metadata: Dictionary
var materials: Array = []
var prop_triangles := 0
# Object-space sun direction fitted to the original Earth bake (tools/proj/earth_sun.gd).
const EARTH_SUN := Vector3(0.399, 0.193, -0.896)
# Rotation of the NASA map about the polar axis (turns), chosen for the view.
const EARTH_LONGITUDE := 0.0
var earth: MeshInstance3D
var earth_center := Vector3.ZERO
var earth_radius := 0.0

static func vec(value: Array) -> Vector3:
	return Vector3(value[0], value[1], value[2])

static func load_mesh(path: String) -> ArrayMesh:
	var file := FileAccess.open(path, FileAccess.READ)
	assert(file != null)
	var magic := file.get_32()
	assert(magic == 0x4c554e41 or magic == 0x524f434b)
	var count := file.get_32()
	var indices := file.get_32()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = file.get_buffer(count * 12).to_vector3_array()
	arrays[Mesh.ARRAY_NORMAL] = file.get_buffer(count * 12).to_vector3_array()
	if magic == 0x524f434b:
		arrays[Mesh.ARRAY_TANGENT] = file.get_buffer(count * 16).to_float32_array()
	arrays[Mesh.ARRAY_TEX_UV] = file.get_buffer(count * 8).to_vector2_array()
	arrays[Mesh.ARRAY_INDEX] = file.get_buffer(indices * 4).to_int32_array()
	assert(file.get_position() == file.get_length())
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

static func solid_texture(color: Color) -> ImageTexture:
	var image := Image.create(4, 4, false, Image.FORMAT_RGBA8)
	image.fill(color)
	return ImageTexture.create_from_image(image)

func setup(asset_root: String) -> void:
	assert(get_child_count() == 0, "Build once and cache the lunar graph")
	var prefix := asset_root.trim_suffix("/") + "/"
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(prefix + "ground.json"))
	metadata = meta
	var textures := []
	var black := solid_texture(Color.BLACK)
	var up := solid_texture(Color(0.5, 0.5, 1))
	for level in meta.levels:
		var size := int(level.size_m)
		var maps := {}
		for kind in ["lighting", "albedo", "normal"]:
			if size > 32 and kind != "lighting":
				maps[kind] = up if kind == "normal" else black
			else:
				var image: Image
				if kind == "lighting" and OS.get_environment("FRAME_LUNAR_RAW_LIGHTING") == "1":
					image = Image.load_from_file(OS.get_environment("FRAME_LUNAR_CAPTURE").path_join(str(size)).path_join("lighting.exr"))
					image.convert(Image.FORMAT_RGBH)
					image.generate_mipmaps()
				else:
					image = load(prefix + "" + str(size) + "-" + kind + ".res")
					assert(image != null and image.is_compressed())
				maps[kind] = ImageTexture.create_from_image(image)
		textures.append(maps)
	materials = []
	for i in meta.levels.size():
		var level: Dictionary = meta.levels[i]
		var parent: Dictionary = meta.levels[mini(i+1, meta.levels.size()-1)]
		var maps: Dictionary = textures[i]
		var parent_maps: Dictionary = textures[mini(i+1, textures.size()-1)]
		var material := ShaderMaterial.new()
		material.shader = load(prefix + "full_ground.gdshader")
		material.set_shader_parameter("extent", float(level.capture_extent_m))
		material.set_shader_parameter("parent_extent", float(parent.capture_extent_m))
		material.set_shader_parameter("size", float(level.size_m))
		material.set_shader_parameter("has_parent", i+1 < meta.levels.size())
		material.set_shader_parameter("dynamic_response", 1.0 if int(level.size_m) <= 32 else 0.0)
		material.set_shader_parameter("parent_dynamic_response", 1.0 if int(parent.size_m) <= 32 else 0.0)
		for pair in [["radiance", "lighting"], ["reflectance", "albedo"], ["surface_normal", "normal"]]:
			material.set_shader_parameter(pair[0], maps[pair[1]])
		for pair in [["parent_radiance", "lighting"], ["parent_reflectance", "albedo"], ["parent_normal", "normal"]]:
			material.set_shader_parameter(pair[0], parent_maps[pair[1]])
		var ground := MeshInstance3D.new()
		ground.mesh = load_mesh(prefix + "ground-" + str(int(level.size_m)) + ".bin")
		ground.material_override = material
		add_child(ground)
		materials.append(material)
	prop_triangles = 0
	if FileAccess.file_exists(prefix + "props.json"):
		var props: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(prefix + "props.json"))
		assert(vec(props.origin_blender).distance_to(vec(meta.origin_blender)) < 0.0001)
		for name in props.props:
			var dynamic: bool = props.props[name].dynamic_screen_light
			var material := ShaderMaterial.new()
			material.shader = load(prefix + "rock_proof.gdshader" if dynamic else prefix + "baked_prop.gdshader")
			for pair in ([["radiance","lighting"],["reflectance","albedo"],["surface_normal","normal"]] if dynamic else [["radiance","lighting"]]):
				var path: String = prefix + "" + str(name) + "-" + str(pair[1])
				var image: Image
				if FileAccess.file_exists(path + ".res") and OS.get_environment("FRAME_LUNAR_RAW_PROPS") != "1":
					image = load(path + ".res")
				else:
					image = Image.load_from_file(path + ".exr")
					assert(image != null)
					image.convert(Image.FORMAT_RGBH)
					image.generate_mipmaps()
				material.set_shader_parameter(pair[0], ImageTexture.create_from_image(image))
			var prop := MeshInstance3D.new()
			prop.name = str(name)
			prop.mesh = load_mesh(prefix + "" + str(name) + ".bin")
			prop.material_override = material
			prop.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			add_child(prop)
			if str(name) == "earth":
				var bounds: Array = props.props[name].bounds
				earth = prop
				earth_center = (vec(bounds[0]) + vec(bounds[1])) * 0.5
				# The 512x256 bake read as a blue blob at hero size: shade the sphere
				# from NASA imagery instead, lit from the bake's own sun direction.
				earth_radius = (vec(bounds[1]) - vec(bounds[0])).x * 0.5
				if FileAccess.file_exists(prefix + "earth-day.res"):
					material.shader = load(prefix + "earth.gdshader")
					# An analytic sphere on a camera-facing card (earth.gdshader); the
					# baked mesh's polygon silhouette aliased against black space.
					var card := QuadMesh.new()
					card.size = Vector2(2, 2)
					prop.mesh = card
					prop.custom_aabb = AABB(earth_center - Vector3.ONE * earth_radius * 1.5, Vector3.ONE * earth_radius * 3.0)
					material.set_shader_parameter("radius", earth_radius)
					material.set_shader_parameter("surface", ImageTexture.create_from_image(load(prefix + "earth-day.res")))
					material.set_shader_parameter("masks", ImageTexture.create_from_image(load(prefix + "earth-extra.res")))
					material.set_shader_parameter("center", earth_center)
					material.set_shader_parameter("sun", EARTH_SUN)
					material.set_shader_parameter("longitude", EARTH_LONGITUDE)
				else:
					material.set_shader_parameter("night_fill", 1.0)
				earth_radius = (vec(bounds[1]) - vec(bounds[0])).x * 0.5
			materials.append(material)
			prop_triangles += int(props.props[name].triangles)

# 0.4.34: lift the baked Earth from the horizon (where the library and
# screen hid it) into a hero position above and right of the picture, like
# looking up from a lunar seat. Only translation and uniform scale change; the
# baked terminator keeps its original orientation.
func place_earth(eye_local: Vector3, direction_local: Vector3, distance: float, angular_diameter_deg: float) -> void:
	if earth == null or earth_radius <= 0.0:
		return
	var target := eye_local + direction_local.normalized() * distance
	var scale := distance * tan(deg_to_rad(angular_diameter_deg) * 0.5) / earth_radius
	earth.transform = Transform3D(Basis.IDENTITY.scaled(Vector3.ONE * scale), target - earth_center * scale)
	# Turn the phase toward the seat (about half lit): the bake's backlit crescent
	# hid nearly all of the surface.
	var material := earth.material_override as ShaderMaterial
	if material and material.shader.resource_path.ends_with("earth.gdshader"):
		material.set_shader_parameter("sun", (EARTH_SUN.normalized() - direction_local.normalized() * 1.25).normalized())

func set_light(brightness: float) -> void:
	for material in materials:
		material.set_shader_parameter("baked_strength", clampf(brightness, 0.03, 1.0) / 0.55)
