extends SceneTree

# Actual modeled surround, independent of the hull/texture bake. The picture
# aperture must remain unobstructed for all three native video sizes.
var checks := 0
var failures: Array[String] = []

func check(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failures.append(message)
		push_error(message)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var ship = load("res://starship/starship_room.gd").new()
	root.add_child(ship)
	ship._build_surround()
	var center := Vector3(0, 2.1, -4.5)
	var extents := {}
	for width in [3.2, 4.2, 5.4]:
		ship.follow_screen(center, width)
		var aperture := Rect2(Vector2(-width * 0.5, -width * 9.0 / 32.0), Vector2(width, width * 9.0 / 16.0))
		check(ship.screen_surround.position.is_equal_approx(center), "Surround center must match native video anchor")
		var pieces := {}
		for part in ship.screen_surround.get_children():
			var bounds: AABB = part.mesh.get_aabb()
			bounds.position += part.position
			pieces[str(part.name)] = bounds
			var projected := Rect2(Vector2(bounds.position.x, bounds.position.y), Vector2(bounds.size.x, bounds.size.y))
			check(not projected.intersects(aperture), "Opaque surround crosses %.1f m picture aperture: %s" % [width, part.name])
			check(bounds.position.y + center.y >= 0.4499, "Screen surround sinks below deck: " + str(part.name))
		# The housing stays a shallow monolith in front of the screen plane; only the
		# deck contact shadow reaches forward.
		var z_extents := {}
		for piece_name in pieces:
			var bounds: AABB = pieces[piece_name]
			z_extents[piece_name] = [snappedf(bounds.position.z, 0.0001), snappedf(bounds.end.z, 0.0001)]
			if piece_name != "ContactShadow":
				check(bounds.end.z <= 0.031, "%s reaches z %.4f in front of the %.1f m screen (limit .031)" % [piece_name, bounds.end.z, width])
		extents[str(width)] = z_extents
		# Posts stand on the deck and rise above the top bar.
		for side in ["Left", "Right"]:
			check(pieces.has(side) and pieces.has("Top") and pieces[side].end.y > pieces["Top"].end.y, "%s post must rise above the top bar at %.1f m" % [side, width])
			check(pieces.has(side) and absf(pieces[side].position.y + center.y - 0.4505) <= 0.002, "%s post must reach the deck at %.1f m" % [side, width])
		# The contact shadow lies on top of every deck surface under it, and the 5.4 m
		# housing (no plinth) has none.
		if width < 5.0:
			check(pieces.has("ContactShadow") and pieces["ContactShadow"].position.y + center.y >= 0.488, "ContactShadow must sit at deck height .488 or above at %.1f m" % width)
		else:
			check(not pieces.has("ContactShadow"), "The 5.4 m housing must have no ContactShadow")
		# Slit halo cards follow Focus and restore exactly.
		for card_name in ["GlowLeft", "GlowRight"]:
			var card: MeshInstance3D = ship.screen_surround.get_node_or_null(card_name)
			var glow: ShaderMaterial = card.material_override if card != null else null
			if glow == null:
				check(false, "%s has no halo material at %.1f m" % [card_name, width])
				continue
			ship.set_light(0.55)
			var normal := float(glow.get_shader_parameter("brightness"))
			ship.set_light(0.12)
			check(float(glow.get_shader_parameter("brightness")) <= normal * 0.3, "Focus must dim %s to 0.3x or less at %.1f m" % [card_name, width])
			ship.set_light(0.55)
			check(is_equal_approx(float(glow.get_shader_parameter("brightness")), normal), "Leaving Focus must restore %s exactly at %.1f m" % [card_name, width])
	ship.set_light(0.55)
	var normal_emission: Color = ship.amber_material.emission
	ship.set_light(0.12)
	check(ship.amber_material.emission.get_luminance() < normal_emission.get_luminance() * 0.3, "Focus must dim the surround lamps")
	ship.set_light(0.55)
	check(ship.amber_material.emission.is_equal_approx(normal_emission), "Leaving Focus must restore surround lamps exactly")
	# The movie bleeds onto the housing only while the glow is on, and leaves nothing behind.
	var housing: ShaderMaterial = ship.surround_material
	check(housing.shader.code.contains("unshaded"), "The housing must stay unshaded")
	check(housing.get_shader_parameter("field_gain") == null, "The housing must start with no bleed")
	var palette := PackedColorArray([Color.WHITE, Color.WHITE, Color.WHITE, Color.WHITE, Color.WHITE, Color.WHITE])
	ship.set_screen_spill(palette, Vector2(4.2, 4.2 * 0.5625 * 0.76), 0.35)
	check(float(housing.get_shader_parameter("field_gain")) > 0.0, "Visible ambient must bleed onto the housing")
	check(housing.get_shader_parameter("picture_half").is_equal_approx(Vector2(2.1, 4.2 * 0.5625 * 0.38)), "The bleed must start at the picture as Fit shows it")
	ship.set_screen_spill(palette, Vector2(4.2, 4.2 * 0.5625 * 0.76), 0.0)
	check(float(housing.get_shader_parameter("field_gain")) == 0.0, "Ambient off must remove the bleed exactly")
	ship.free()
	print(JSON.stringify({"z_extents": extents}))
	print(JSON.stringify({"starship_surround_checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
