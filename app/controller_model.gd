extends RefCounted

# Read Valve's installed model in place; do not redistribute runtime assets.
static func load_installed(side: String) -> MeshInstance3D:
	var name := "frame_controller_" + side
	var base := "/opt/steamvr/drivers/frame_controller/resources/rendermodels/" + name
	var path := base.path_join(name + ".obj")
	if not FileAccess.file_exists(path):
		return null
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for line in FileAccess.get_file_as_string(path).split("\n"):
		var parts := line.strip_edges().split(" ", false)
		if parts.is_empty():
			continue
		match parts[0]:
			"v": vertices.append(Vector3(float(parts[1]), float(parts[2]), float(parts[3])))
			"vn": normals.append(Vector3(float(parts[1]), float(parts[2]), float(parts[3])))
			"vt": uvs.append(Vector2(float(parts[1]), 1.0 - float(parts[2])))
			"f":
				for triangle in range(2, parts.size() - 1):
					# OBJ is counterclockwise; Godot's front faces are clockwise.
					for corner in [1, triangle + 1, triangle]:
						var index := parts[corner].split("/")
						if index.size() > 2 and not index[2].is_empty():
							surface.set_normal(normals[int(index[2]) - 1])
						if index.size() > 1 and not index[1].is_empty():
							surface.set_uv(uvs[int(index[1]) - 1])
						surface.add_vertex(vertices[int(index[0]) - 1])
	var model := MeshInstance3D.new()
	surface.index()
	model.mesh = surface.commit()
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(0.85, 0.85, 0.85)
	var picture := Image.load_from_file(base.path_join(name + "_color.png"))
	if picture:
		picture.generate_mipmaps()
		material.albedo_texture = ImageTexture.create_from_image(picture)
	model.material_override = material
	var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(base.path_join(name + ".json")))
	if data is Dictionary:
		var grip: Dictionary = data.get("components", {}).get("openxr_grip", {}).get("component_local", {})
		var pos: Array = grip.get("origin", [0, 0, 0])
		var rot: Array = grip.get("rotate_xyz", [0, 0, 0])
		var transform := Transform3D(Basis.from_euler(Vector3(deg_to_rad(rot[0]), deg_to_rad(rot[1]), deg_to_rad(rot[2])), EULER_ORDER_XYZ), Vector3(pos[0], pos[1], pos[2]))
		model.transform = transform.affine_inverse()
	return model
