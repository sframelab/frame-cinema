extends SceneTree

# Exercise the actual app's room/placement/UI paths without opening XR, a
# browser, production IPC or saved preferences. Run against a staged project.
class QuietUI extends RefCounted:
	var page := "room"
	func refresh_settings() -> void: pass

class CinemaFixture extends "res://cinema.gd":
	var screen_updates: Array[Dictionary] = []
	func _ready() -> void: pass
	func _process(_delta: float) -> void: pass
	func _save() -> void: pass
	func _render_ui(_page: String = "") -> void: pass
	func _position_dock() -> void: pass
	func _write_presentation() -> void: pass
	func _follow_room_screen() -> void:
		super._follow_room_screen()
		if is_instance_valid(room) and is_instance_valid(room.contents):
			screen_updates.append({"room": environment_index, "center": _screen_center(), "width": _display_screen_width()})

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
	const Rooms = preload("res://cinema_rooms.gd")
	check(Rooms.IDS.slice(0, 8) == ["retired_lake", "retired_gallery", "retired_blue_hour", "lunar_landscape", "coastal_dusk", "dark_room", "desert_alcove", "alpine_night"], "Existing saved room IDs must retain their meaning")
	check(Rooms.available(Rooms.STARSHIP), "Staged ship package is not available")
	check(not Rooms.available(0) and not Rooms.available(1) and not Rooms.available(2) and not Rooms.available(Rooms.ALPINE), "Retired rooms must stay retired")
	check(Rooms.NAMES[Rooms.STARSHIP] == "Observation Deck", "Public room name differs from menu label")

	var app := CinemaFixture.new()
	root.add_child(app)
	app.seat = Node3D.new()
	app.add_child(app.seat)
	app.camera = Camera3D.new()
	app.camera.position = Vector3(0, 1.65, 0)
	app.add_child(app.camera)
	app.world = WorldEnvironment.new()
	app.world.environment = Environment.new()
	app.add_child(app.world)
	app.room = Rooms.new()
	app.seat.add_child(app.room)
	app.ui = QuietUI.new()
	app.environment_index = Rooms.STARSHIP
	# The real ambient glow, created as cinema.gd does (seat child, host = app), so the
	# room's ambient profile and set_screen_field hook run on the actual paths.
	app.ambient = preload("res://cinema_ambient.gd").new()
	app.ambient.host = app
	app.seat.add_child(app.ambient)
	app._load_environment()
	var ship: Node3D = app.room.contents
	check(ship.is_visible_in_tree() and app.room.room_index == Rooms.STARSHIP, "Ship must be the active visible room")
	check(app.screen_updates.size() == 1 and app.screen_updates[-1].center == Vector3(0, 2.1, -4.5), "Room load must synchronize its surround with the actual video anchor")
	check(app.room.metrics().triangles > 0 and not app.room.metrics().panorama, "Ship must report actual 3D geometry rather than a room panorama")
	# Was 150,000. 26,000 of the room's triangles are now tiny star and object triangles, culled by direction chunks, whose shaded area is held near 0.5.13's. The stand-in test decides whether this holds.
	check(int(app.room.metrics().triangles) <= 180000, "Ship exceeds the 180k triangle budget: %d" % int(app.room.metrics().triangles))
	var glows: Array = ship.metadata.get("glows", [])
	var practical_glow: MeshInstance3D = ship.get_node_or_null("PracticalGlow")
	check(not glows.is_empty() and practical_glow != null and practical_glow.get_parent() == ship, "Lamp halos must be one PracticalGlow mesh under the ship")
	if practical_glow != null:
		check(practical_glow.mesh.surface_get_array_len(0) == 4 * glows.size(), "PracticalGlow must hold one 4-vertex quad per glow (%d vertices for %d glows)" % [practical_glow.mesh.surface_get_array_len(0), glows.size()])
	var deck: MeshInstance3D = ship.get_node_or_null("Deck")
	check(deck != null, "Ship has no Deck part")
	# Ambient on (Cinema, brightness 0.5): the ship's profile and the deck's movie field.
	app.ambient.target.fill(Color(0.35, 0.35, 0.35))
	app.ambient.advance(0.1, 2, 0.5)
	check(app.ambient.visible, "Ambient glow must be visible with a lit palette")
	# The ship lights itself analytically: Cinema's two OmniLights stay hidden at zero energy.
	for light in app.ambient.lights:
		check(not light.visible and light.light_energy == 0.0, "Ship must keep Cinema's OmniLights hidden at zero energy")
	check(not app.ambient.haze.visible, "The glass cabin must hide the ambient haze sheet")
	var ship_spread: float = app.ambient.material.get_shader_parameter("spread")
	check(is_equal_approx(ship_spread, app.ambient.RESPONSE[2].z * 0.65 * 0.7), "Ship halo spread must follow the room profile (0.7)")
	var shell: MeshInstance3D = ship.get_node_or_null("Shell")
	var emission: MeshInstance3D = ship.get_node_or_null("Emission")
	check(shell != null and shell.material_override.get_shader_parameter("movie_on") == true and shell.material_override.get_shader_parameter("movie_left").x > 0.0, "Visible ambient must light the hull parts")
	check(emission != null and emission.material_override.get_shader_parameter("movie_on") != true, "The movie light must never touch the lamps")
	check(float(ship.surround_material.get_shader_parameter("field_gain")) > 0.0, "Visible ambient must bleed onto the screen housing")
	for part in ship.get_children():
		if part is MeshInstance3D and part.material_override is ShaderMaterial and part.material_override.shader.resource_path.get_file() in ["hull.gdshader", "deck_field.gdshader"]:
			check(part.material_override.shader.code.contains("unshaded") or part.material_override.shader.code.contains("deck_common"), "Baked parts must stay unshaded: " + str(part.name))
	if deck != null:
		var field_material: ShaderMaterial = deck.material_override
		check(field_material.shader.resource_path.ends_with("deck_field.gdshader") and float(field_material.get_shader_parameter("field_gain")) > 0.0, "Visible ambient must switch the deck to its movie-field variant")
		check(field_material.get_shader_parameter("movie_on") == true and field_material.get_shader_parameter("edge_mean").x > 0.0, "Visible ambient must light the deck and give it the edge averages")
	# The source is in room space and follows the screen; recentering must not move it.
	var source: Vector3 = shell.material_override.get_shader_parameter("movie_source")
	check(source.is_equal_approx(Vector3(0, 1.65, -3.25)), "Movie source must sit 1.25 m in front of the picture and .45 m below its centre, in room space")
	# Fit: the bleed and the reflection follow the picture as shown, not the housing's aperture.
	app.picture_top = 0.12
	app.ambient.advance(0.1, 2, 0.5)
	var cropped: Vector2 = ship.surround_material.get_shader_parameter("picture_half")
	check(is_equal_approx(cropped.y, 4.2 * 9.0 / 32.0 * 0.76) and ship.deck_field_material.get_shader_parameter("picture_half") == cropped, "The housing bleed and the deck's reflection must follow Fit's picture height")
	app.picture_top = 0.0
	app.ambient.advance(0.1, 2, 0.5)
	# A white frame at full settings stays under the soft limit; a dim frame there does not reach it.
	app.ambient.target.fill(Color.WHITE)
	for step in 80:
		app.ambient.advance(0.1, 4, 1.0)
	check(float(ship.deck_field_material.get_shader_parameter("field_gain")) < 0.55, "A white frame at full brightness must hit the soft limit")
	app.ambient.target.fill(Color(0.02, 0.02, 0.02))
	for step in 80:
		app.ambient.advance(0.1, 4, 1.0)
	check(float(ship.deck_field_material.get_shader_parameter("field_gain")) > 0.99, "A dim frame at full brightness must stay clear of the soft limit")
	# The profiler's variants toggle the new path.
	check(ship.profile_variants().has("movie light off"), "The profiler must be able to measure the movie light")
	check(ship.profile_variants().has("stars hidden") and not ship.profile_variants().has("star detail off"), "The profiler must measure the star mesh, not the old lattice")
	ship.profile_variant("stars hidden", true)
	check(not ship.star_node.visible, "Profile variant must hide the star mesh")
	ship.profile_variant("stars hidden", false)
	check(ship.star_node.visible, "Profile variant must restore the star mesh")
	check(ship.profile_variants().has("cities hidden"), "The profiler must measure the city mesh")
	ship.profile_variant("cities hidden", true)
	check(not ship.city_node.visible, "Profile variant must hide the city mesh")
	ship.profile_variant("cities hidden", false)
	check(ship.city_node.visible, "Profile variant must restore the city mesh")
	ship.profile_variant("movie light off", true)
	check(shell.material_override.get_shader_parameter("movie_on") == false and ship.deck_field_material.get_shader_parameter("movie_on") == false, "Profile variant must turn the movie light off")
	ship.profile_variant("movie light off", false)
	check(shell.material_override.get_shader_parameter("movie_on") == true, "Profile variant must restore the movie light")
	ship.profile_variant("deck as hull", true)
	if deck != null:
		check(deck.material_override.shader.resource_path.ends_with("hull.gdshader") and deck.material_override.get_shader_parameter("movie_on") == true and float(deck.material_override.get_shader_parameter("spill_gain")) > 0.0, "Deck as hull must keep the movie light")
	ship.profile_variant("deck as hull", false)
	# The profiler's "without glow" step must hold everything off through tick(), then let it return.
	app.profiling = true
	app.ambient.target.fill(Color(0.35, 0.35, 0.35))
	app.ambient.tick(0.1)
	check(app.ambient.visible and shell.material_override.get_shader_parameter("movie_on") == true, "Profiling must force the glow on")
	app.ambient.profile_glow_off = true
	app.ambient.tick(0.1)
	check(not app.ambient.visible and shell.material_override.get_shader_parameter("movie_on") == false and deck.material_override.shader.resource_path.ends_with("deck.gdshader"), "Without glow must hold the halo, movie light and field off across ticks")
	app.ambient.tick(0.1)
	check(not app.ambient.visible, "Without glow must still be off on the next tick")
	app.ambient.profile_glow_off = false
	app.ambient.tick(0.1)
	check(app.ambient.visible and shell.material_override.get_shader_parameter("movie_on") == true, "Without glow must restore the glow")
	app.profiling = false
	# Ambient Off: base deck shader, field gain 0, no movie light anywhere.
	app.ambient.advance(0.1, 0, 0.5)
	if deck != null:
		var base_material: ShaderMaterial = deck.material_override
		check(base_material.shader.resource_path.ends_with("deck.gdshader") and float(ship.deck_field_material.get_shader_parameter("field_gain")) == 0.0, "Ambient Off must return the deck to deck.gdshader with field gain 0")
	check(shell.material_override.get_shader_parameter("movie_on") == false and float(ship.surround_material.get_shader_parameter("field_gain")) == 0.0, "Ambient Off must remove the movie light and the housing bleed")
	# A black frame fades out to the same state.
	app.ambient.target.fill(Color(0.35, 0.35, 0.35))
	app.ambient.advance(0.1, 2, 0.5)
	app.ambient.target.fill(Color.BLACK)
	for step in 400:
		app.ambient.advance(0.1, 2, 0.5)
	check(not app.ambient.visible and shell.material_override.get_shader_parameter("movie_on") == false and float(ship.surround_material.get_shader_parameter("field_gain")) == 0.0, "A black frame must return to the baked look exactly")
	app.ambient.advance(0.1, 0, 0.5)
	var source_request: int = app.source_request
	for width in [3.2, 4.2, 5.4]:
		var updates: int = app.screen_updates.size()
		app._set_screen_width(width)
		check(app.screen_updates.size() == updates + 1 and is_equal_approx(app.screen_updates[-1].width, width), "Screen surround did not follow %.1f m screen size" % width)
		check(app._screen_center() == Vector3(0, 2.1, -4.5) and is_equal_approx(app._display_screen_width(), width), "Ship changed the standard native video placement")
		check(is_equal_approx(float(ship.get("screen_width")), width) and ship.get("screen_center") == app._screen_center(), "Modeled surround did not adopt the actual native screen dimensions")
		check(is_equal_approx(float(shell.material_override.get_shader_parameter("movie_side")), 1.0 / (width * 1.2)), "Movie light's colour split must follow the %.1f m screen" % width)

	var moved_seat := Transform3D(Basis(Vector3.UP, 0.8), Vector3(1.4, 0.12, -0.7))
	app._commit_seat(moved_seat)
	check(app.room.global_transform.is_equal_approx(moved_seat), "Recenter must move the modeled room with the shared seat")
	check(app.screen_updates[-1].center == Vector3(0, 2.1, -4.5) and is_equal_approx(app.screen_updates[-1].width, 5.4), "Recenter must preserve screen dimensions in seat space")
	check(ship.to_global(Vector3(0, 2.1, -4.5)).is_equal_approx(app.seat.to_global(app._screen_center())), "Room surround and native screen anchors must recenter together")
	check(ship.get("screen_center") == Vector3(0, 2.1, -4.5) and is_equal_approx(float(ship.get("screen_width")), 5.4), "Modeled surround must preserve its seat-local size after recenter")
	check(shell.material_override.get_shader_parameter("movie_source") == source, "Recenter must not move the movie source in room space")
	# The stars are one parent (the skirted stars, never culled) and direction chunks under it, drawn first in the transparent pass, and the app's far keeps the sky at 60 km.
	check(ship.star_node != null and ship.star_node.mesh.get_surface_count() == 1, "Stars must be one parent mesh of one surface")
	check(ship.star_node.get_child_count() >= 20, "Star chunks must hang under the parent, so hiding it hides them all")
	for chunk in ship.star_node.get_children():
		check(chunk.mesh.get_surface_count() == 1 and is_equal_approx(chunk.sorting_offset, ship.star_node.sorting_offset), "Every star chunk must be one surface and sort with the parent")
	check(ship.star_node.custom_aabb.size.x >= 1000.0 and ship.star_node.custom_aabb.has_point(app.camera.global_position), "The star mesh's box must always hold the eye")
	check(ship.star_node.sorting_offset < 0.0, "Stars must draw before anything else that blends")
	# The city lights keep the stars' rules and share the sky's cloud map.
	check(ship.city_node != null and ship.city_node.mesh.get_surface_count() == 1, "Cities must be one mesh of one surface")
	check(ship.city_node.custom_aabb.size.x >= 1000.0 and ship.city_node.custom_aabb.has_point(app.camera.global_position), "The city mesh's box must always hold the eye")
	check(ship.star_node.sorting_offset < ship.city_node.sorting_offset, "Stars must draw before the cities")
	check(ship.sky_material.get_shader_parameter("dust") != null, "The sky must bind the dust map: unbound it reads black")
	check(ship.object_node != null and ship.object_node.mesh.get_surface_count() == 1, "Deep-sky objects must be one mesh of one surface")
	check(ship.object_node.custom_aabb.size.x >= 1000.0 and ship.object_node.custom_aabb.has_point(app.camera.global_position), "The objects' box must always hold the eye")
	check(ship.star_node.sorting_offset < ship.object_node.sorting_offset, "Objects must draw after the stars, so their dust hides the stars behind them")
	check(ship.object_material.get_shader_parameter("atlas") != null, "The objects must bind their atlas")
	ship.profile_variant("objects hidden", true)
	check(not ship.object_node.visible, "Profile variant must hide the objects")
	ship.profile_variant("objects hidden", false)
	check(ship.object_node.visible, "Profile variant must restore the objects")
	check(ship.city_material.get_shader_parameter("clouds") == ship.sky_material.get_shader_parameter("clouds"), "Cities must share the sky's cloud map")
	check(is_equal_approx(app.camera.far, 120000.0), "The Observation Deck's far must clear the engine's far / 2 sky error")
	# The Earth turns on the global spin, at the speed in the room script; no material uniform and no TIME.
	check(ship.is_processing(), "The room must advance the Earth's spin")
	check(is_equal_approx(ship.EARTH_DEG_PER_HOUR, 150.0) and is_equal_approx(ship.CLOUD_SPEED, 1.08), "The Earth must turn one turn in 2.4 hours, clouds 8% ahead")
	check(ship.sky_material.get_shader_parameter("earth_spin") == null, "The spin must stay a global uniform")
	check(ship.sky_material.get_shader_parameter("clouds") != null and ship.sky_material.get_shader_parameter("masks") != null and ship.sky_material.get_shader_parameter("surface") != null, "The belt maps must be bound")
	# The lamps' dimmer reaches no part of the sky. Below the default level the Earth, the Milky Way, the stars and the objects follow one slow ramp, through the global earth_gain.
	check(ship.sky_material.get_shader_parameter("earth_gain") == null and ship.sky_material.get_shader_parameter("star_brightness") == null, "The sky must take no dimmer through a material uniform")
	var star_gain_before: Variant = ship.star_material.get_shader_parameter("star_gain")
	ship.set_light(1.0)
	ship.settle_earth()
	check(is_equal_approx(ship.earth_level, 1.0), "The Earth must not rise past the default level")
	ship.set_light(app.light_level)
	ship.settle_earth()
	# Focus dims the room, not the movie's light.
	app.ambient.target.fill(Color(0.35, 0.35, 0.35))
	app.ambient.advance(0.1, 2, 0.5)
	var movie_before: Vector3 = shell.material_override.get_shader_parameter("movie_left")
	app.focused_view = true
	app._apply_room_light()
	check(is_equal_approx(app.room.room_light, 0.12), "Focus must dim the ship through the shared room-light path")
	check(ship.room_light == 0.12, "Focus must set the ship's room light to exactly 0.12")
	check(emission != null and float(emission.material_override.get_shader_parameter("baked_strength")) < 0.1, "Focus must dim the baked lamps below 0.1")
	check(shell.material_override.get_shader_parameter("movie_left") == movie_before, "Focus must not dim the movie light")
	check(ship.earth_level > 0.9 and ship.earth_ramp != null, "The Earth must start a slow ramp in Focus, not follow the lamps")
	ship.settle_earth()
	check(is_equal_approx(ship.earth_level, ship.EARTH_FOCUS), "Focus must settle the Earth at its own level")
	check(ship.star_material.get_shader_parameter("star_gain") == star_gain_before, "Focus must reach the stars through the global ramp only, not through a material write")
	app.focused_view = false
	app._apply_room_light()
	check(is_equal_approx(app.room.room_light, app.light_level), "Leaving Focus must restore the selected room light")
	ship.settle_earth()
	check(is_equal_approx(ship.earth_level, 1.0), "Leaving Focus must bring the Earth back")
	# Lamps stay under the 1.6 linear emitter limit at any room light: the packed lens map (BC6H overshoot leaves
	# three texels at 1.605, and no rendered lamp pixel passes 1.54) times the emitter curve at full light,
	# and the housing slits' own emission.
	var lamp_map: Image = (load(ship.source_root + "emission-lighting.res") as Image).duplicate()
	lamp_map.clear_mipmaps()
	lamp_map.decompress()
	var lamp_peak := 0.0
	for y in lamp_map.get_height():
		for x in lamp_map.get_width():
			var texel := lamp_map.get_pixel(x, y)
			lamp_peak = maxf(lamp_peak, maxf(texel.r, maxf(texel.g, texel.b)))
	ship.set_light(1.0)
	check(lamp_peak * float(emission.material_override.get_shader_parameter("baked_strength")) <= 1.61, "A lamp lens must stay at or under 1.6 linear at full room light")
	var slit: Color = ship.amber_material.emission * ship.amber_material.emission_energy_multiplier
	check(maxf(slit.r, maxf(slit.g, slit.b)) <= 1.6, "A housing slit must stay at or under 1.6 linear at full room light")
	ship.set_light(app.light_level)
	app.ambient.advance(0.1, 0, 0.5)

	app._set_environment(Rooms.DARK_ROOM)
	check(not ship.is_visible_in_tree() and app.room.contents.is_visible_in_tree(), "Changing rooms must hide ship geometry and child lights")
	check(not ship.city_node.is_visible_in_tree(), "Changing rooms must hide the city mesh")
	check(not ship.object_node.is_visible_in_tree(), "Changing rooms must hide the objects")
	# Dark Room keeps the app's own ambient: visible lights at range 8, attenuation 1.4, haze and
	# full halo spread, re-applied even though the screen width did not change.
	app.ambient.target.fill(Color(0.35, 0.35, 0.35))
	app.ambient.advance(0.1, 2, 0.5)
	for light in app.ambient.lights:
		check(light.visible and light.light_energy > 0.0, "Dark Room must get Cinema's OmniLights back")
		check(is_equal_approx(light.omni_range, 8.0) and is_equal_approx(light.omni_attenuation, 1.4), "Dark Room ambient lights must return to range 8.0, attenuation 1.4")
	check(app.ambient.haze.visible, "Dark Room must show the ambient haze again")
	check(is_equal_approx(float(app.ambient.material.get_shader_parameter("spread")), app.ambient.RESPONSE[2].z * 0.65), "Dark Room must restore the full halo spread at the same screen width")
	app.ambient.advance(0.1, 0, 0.5)
	app._set_environment(Rooms.STARSHIP)
	check(app.room.contents == ship and ship.is_visible_in_tree(), "Returning to the ship must reuse its cached geometry")
	app.ambient.target.fill(Color(0.35, 0.35, 0.35))
	app.ambient.advance(0.1, 2, 0.5)
	for light in app.ambient.lights:
		check(not light.visible and light.light_energy == 0.0, "Returning to the ship must hide Cinema's OmniLights again")
	app.ambient.advance(0.1, 0, 0.5)
	var visible_rooms := 0
	for child in app.room.get_children():
		if child is Node3D and child.is_visible_in_tree(): visible_rooms += 1
	check(visible_rooms == 1 and app.room.geometry_cache.size() == 2, "Room switching must keep one active graph and bounded caching")
	check(app.source_request == source_request and app.ipc.is_empty(), "Room and size changes must not restart playback")
	check(not app._dark_room() and not app._alpine_room() and app._effective_ambient_mode() == app.ambient_mode, "Ship must retain standard glow and remain outside Dark Room stereo mode")

	app.ui = preload("res://cinema_ui.gd").new()
	app.ui.build(app)
	app.ui.show_page("room")
	await process_frame
	await process_frame
	var cards: Array[Button] = []
	var ship_card: Button
	for node in app.ui_viewport.find_children("*", "Button", true, false):
		check(Rect2(Vector2.ZERO, app._ui_size()).encloses(node.get_global_rect()), "Room control falls outside the menu: " + node.text)
		if node.has_meta("room_id"):
			cards.append(node)
			if node.get_meta("room_id") == Rooms.STARSHIP: ship_card = node
	check(cards.size() == Rooms.available_indices().size(), "Room menu must include every available room")
	check(ship_card != null and ship_card.accessibility_name == "Observation Deck", "Ship menu target is missing or unnamed")
	for i in cards.size():
		for j in range(i + 1, cards.size()):
			check(not cards[i].get_global_rect().intersects(cards[j].get_global_rect()), "Room menu hit targets overlap")
		for caption in cards[i].get_children():
			if caption is Label:
				check(Rect2(Vector2.ZERO, cards[i].size).encloses(caption.get_rect()), "Room caption overflows its card: " + caption.text)
	if ship_card:
		app._set_environment(Rooms.DARK_ROOM)
		ship_card.pressed.emit()
		check(app.environment_index == Rooms.STARSHIP, "Ship card must activate the actual room")
	var output := OS.get_environment("FRAME_CINEMA_STARSHIP_TEST_OUT")
	if not output.is_empty():
		DirAccess.make_dir_recursive_absolute(output)
		if DisplayServer.get_name() != "headless":
			await RenderingServer.frame_post_draw
			app.ui_viewport.get_texture().get_image().save_png(output.path_join("room-menu.png"))
		var report := FileAccess.open(output.path_join("integration.json"), FileAccess.WRITE)
		report.store_string(JSON.stringify({"checks": checks, "failures": failures, "room": app.room.metrics(), "scope": "Windows fixture; no XR, headset playback or deployment"}, "  "))
	app.ambient.free()
	app.free()
	await process_frame
	print(JSON.stringify({"starship_integration_checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
