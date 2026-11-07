extends RefCounted

# 0.4.34 design pass: visionOS-style glass windows, ornaments and controls.
# Page sizes, button semantics, scene references and texts used by tests and
# by cinema.gd are unchanged; only presentation differs from 0.4.33.

const INK := Color(0.97, 0.975, 0.985)
const MUTED := Color(1, 1, 1, 0.62)
const FAINT := Color(1, 1, 1, 0.40)
const DARK_INK := Color(0.10, 0.105, 0.12)
const BASE := Color(1, 1, 1, 0.10)
const RENDER_SCALE := 2
const ACCENT := Color("dce9ff")
var scene: Node3D
var page := "library"
var panel: PanelContainer
var column: VBoxContainer
var heading: Label
var font: FontFile
var icons := {}
var room_images := {}
var faces := {}
var composition_layer: OpenXRCompositionLayerQuad
var focus_notice_panel: PanelContainer
var focus_hint_age := 0.0
var room_description: Label
var glass: ColorRect
const FOCUS_HINT_HOLD := 0.15
const FOCUS_HINT_FADE := 0.6
const UI_MESH_LAYER := 1 << 18
const WINDOW_RADIUS := 52.0
# Fallback colours when bundled provider artwork is unavailable.
const CARD_HUES := {"netflix": Color(0.07, 0.07, 0.08), "hbomax": Color(0.30, 0.20, 0.86), "disneyplus": Color(0.04, 0.16, 0.50),
	"primevideo": Color(0.02, 0.26, 0.42), "plex": Color(0.26, 0.19, 0.04)}

func icon(kind: String) -> Texture2D:
	if icons.has(kind):
		return icons[kind]
	var paths := {
		"services": '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>',
		"back": '<path d="M14.5 5 7.5 12l7 7"/>',
		"play": '<path d="M7.5 4.8v14.4c0 .8.9 1.3 1.6.9l11.3-7.2c.6-.4.6-1.3 0-1.7L9.1 3.9c-.7-.4-1.6.1-1.6.9Z" fill="white" stroke="none"/>',
		"pause": '<rect x="6" y="4.5" width="4.2" height="15" rx="1.3" fill="white" stroke="none"/><rect x="13.8" y="4.5" width="4.2" height="15" rx="1.3" fill="white" stroke="none"/>',
		"keyboard": '<rect x="2" y="5.5" width="20" height="13" rx="3"/><path d="M6 9.5h.01m4 0h.01m4 0h.01m4 0h.01M6 12.5h.01m4 0h.01m4 0h.01m4 0h.01M7.5 15.5h9"/>',
		"room": '<path d="m2.5 19 6.5-10.5 4.5 6.5 3-4 5 8Z"/><circle cx="17" cy="5.5" r="1.8"/>',
		"focus": '<rect x="2.5" y="4.5" width="19" height="13" rx="2.5"/><path d="M8 21h8"/>',
		"more": '<circle cx="5.5" cy="12" r="1.3" fill="white" stroke="none"/><circle cx="12" cy="12" r="1.3" fill="white" stroke="none"/><circle cx="18.5" cy="12" r="1.3" fill="white" stroke="none"/>',
		"recenter": '<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m8 0h3a2 2 0 0 0 2-2v-3"/><circle cx="12" cy="12" r="2.6"/>',
		"skip_back": '<path d="M9.2 4.1A8.4 8.4 0 1 1 4.1 9.4"/><path d="M9.8 1.5 6.7 4.2l3.2 2.3"/><path d="M9.4 10.5l1.4-1v6.4" stroke-width="1.5"/><ellipse cx="14.6" cy="12.7" rx="1.9" ry="3.2" stroke-width="1.5"/>',
		"skip_forward": '<path d="M14.8 4.1A8.4 8.4 0 1 0 19.9 9.4"/><path d="M14.2 1.5l3.1 2.7-3.2 2.3"/><path d="M8.4 10.5l1.4-1v6.4" stroke-width="1.5"/><ellipse cx="13.6" cy="12.7" rx="1.9" ry="3.2" stroke-width="1.5"/>',
		"chevron": '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
		"check": '<path d="m6 12.5 4 4 8-9"/>',
		"done": '<path d="M6 6l12 12M18 6 6 18"/>',
	}
	var svg := '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24"><g fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">%s</g></svg>' % paths.get(kind, paths.more)
	var picture := Image.new()
	picture.load_svg_from_string(svg)
	icons[kind] = ImageTexture.create_from_image(picture)
	return icons[kind]

func face(weight: int, size: int, tracking: int = 0) -> FontVariation:
	var key := "%d:%d:%d" % [weight, size, tracking]
	if faces.has(key):
		return faces[key]
	var variation := FontVariation.new()
	variation.base_font = font
	variation.variation_opentype = {"wght": weight, "opsz": clampi(size, 14, 32)}
	variation.spacing_glyph = tracking
	faces[key] = variation
	return variation

func box(color: Color, radius: int = 40, margin: int = 18) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.set_corner_radius_all(radius)
	style.corner_detail = 24
	style.anti_aliasing = true
	style.anti_aliasing_size = 1.0
	style.set_content_margin_all(margin)
	return style

func label(text: String, size: int, color: Color = INK, weight: int = 450, tracking: int = 0) -> Label:
	var node := Label.new()
	node.text = text
	node.add_theme_font_size_override("font_size", size)
	node.add_theme_color_override("font_color", color)
	node.add_theme_font_override("font", face(weight, size, tracking))
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return node

func choice(text: String, setting: String, value: float, action: Callable, width: float) -> Button:
	var node := button(text, action, width)
	node.toggle_mode = true
	node.set_meta("setting", setting)
	node.set_meta("value", value)
	node.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	node.custom_minimum_size.y = 60
	node.add_theme_stylebox_override("normal", box(Color.TRANSPARENT, 30, 10))
	node.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 0.10), 30, 10))
	var selected := box(Color(1, 1, 1, 0.92), 30, 10)
	selected.shadow_color = Color(0, 0, 0, 0.18)
	selected.shadow_size = 6
	selected.shadow_offset = Vector2(0, 2)
	node.add_theme_stylebox_override("pressed", selected)
	node.add_theme_stylebox_override("hover_pressed", selected)
	node.add_theme_stylebox_override("disabled", box(Color.TRANSPARENT, 30, 10))
	node.add_theme_color_override("font_pressed_color", DARK_INK)
	node.add_theme_color_override("font_hover_pressed_color", DARK_INK)
	node.add_theme_font_override("font", face(560, 23))
	node.add_theme_font_size_override("font_size", 23)
	return node

func choices(parent: Node) -> HBoxContainer:
	var surface := PanelContainer.new()
	surface.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var track := box(Color(0, 0, 0, 0.22), 34, 4)
	track.border_color = Color(1, 1, 1, 0.06)
	track.set_border_width_all(1)
	surface.add_theme_stylebox_override("panel", track)
	parent.add_child(surface)
	return row(surface, 2)

func refresh_settings() -> void:
	if page != "room": return
	var values := {"screen": scene.screen_width, "ambient": float(scene._effective_ambient_mode()), "brightness": scene.ambient_brightness, "light": scene.light_level,
		"alpine_height": float(scene.alpine_height)}
	for node in scene.ui_viewport.find_children("*", "Button", true, false):
		var setting: String = node.get_meta("setting", "")
		if not values.has(setting): continue
		node.set_pressed_no_signal(is_equal_approx(float(node.get_meta("value")), values[setting]))
		node.disabled = (setting == "light" and scene._dark_room()) or (setting == "brightness" and scene._effective_ambient_mode() == 0) or (setting == "ambient" and scene._alpine_room())
	if is_instance_valid(room_description): room_description.text = room_hint()

func button(text: String, action: Callable, width: float = 180, tint: Color = BASE) -> Button:
	var node := Button.new()
	node.text = text
	node.custom_minimum_size = Vector2(width, 64)
	node.add_theme_font_override("font", face(560, 24))
	node.add_theme_font_size_override("font_size", 24)
	node.add_theme_color_override("font_color", INK)
	node.add_theme_color_override("font_hover_color", Color.WHITE)
	node.add_theme_color_override("font_pressed_color", Color.WHITE)
	node.add_theme_color_override("icon_normal_color", INK)
	node.add_theme_color_override("icon_hover_color", Color.WHITE)
	node.add_theme_stylebox_override("normal", box(tint, 32, 18))
	node.add_theme_stylebox_override("hover", box(Color(1, 1, 1, maxf(tint.a, 0.0) + 0.12), 32, 18))
	node.add_theme_stylebox_override("pressed", box(Color(1, 1, 1, 0.30), 32, 18))
	node.add_theme_stylebox_override("hover_pressed", box(Color(1, 1, 1, 0.30), 32, 18))
	node.add_theme_stylebox_override("disabled", box(Color(1, 1, 1, minf(tint.a, 0.04)), 32, 18))
	node.add_theme_color_override("font_disabled_color", Color(1, 1, 1, 0.30))
	node.add_theme_color_override("icon_disabled_color", Color(1, 1, 1, 0.30))
	var focus := box(Color.TRANSPARENT, 32, 18)
	focus.set_border_width_all(3)
	focus.border_color = ACCENT
	node.add_theme_stylebox_override("focus", focus)
	node.pressed.connect(action)
	return node

func control(text: String, symbol: String, action: Callable, width: float) -> Button:
	var node := button(text, action, width)
	node.icon = icon(symbol)
	node.expand_icon = true
	node.add_theme_constant_override("icon_max_width", 28)
	node.add_theme_constant_override("h_separation", 12)
	return node

func icon_only(node: Button, size: float, glyph: int = 34) -> void:
	# Keep the button's text for state/tests; draw only its symbol.
	node.custom_minimum_size = Vector2(size, size)
	node.add_theme_font_size_override("font_size", 1)
	for state in ["font_color", "font_hover_color", "font_pressed_color", "font_hover_pressed_color", "font_disabled_color", "font_focus_color"]:
		node.add_theme_color_override(state, Color.TRANSPARENT)
	node.add_theme_constant_override("h_separation", 0)
	node.add_theme_constant_override("icon_max_width", glyph)
	node.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
	node.expand_icon = true
	var radius := int(size / 2)
	node.add_theme_stylebox_override("normal", box(Color.TRANSPARENT, radius, 0))
	node.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 0.14), radius, 0))
	node.add_theme_stylebox_override("pressed", box(Color(1, 1, 1, 0.28), radius, 0))
	node.add_theme_stylebox_override("hover_pressed", box(Color(1, 1, 1, 0.28), radius, 0))
	node.add_theme_stylebox_override("disabled", box(Color.TRANSPARENT, radius, 0))

func row(parent: Node, separation: int = 16) -> HBoxContainer:
	var node := HBoxContainer.new()
	node.add_theme_constant_override("separation", separation)
	parent.add_child(node)
	return node

func spacer(parent: Node) -> void:
	var node := Control.new()
	node.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(node)

func gap(parent: Node, height: float) -> void:
	var node := Control.new()
	node.custom_minimum_size.y = height
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(node)

func glass_rect(size: Vector2, radius: float, opacity: float, shadow: float = 1.0, inset: float = 16.0) -> ColorRect:
	var rect := ColorRect.new()
	rect.size = size
	rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var surface := ShaderMaterial.new()
	surface.shader = load("res://cinema_glass.gdshader")
	surface.set_shader_parameter("panel_size", size)
	surface.set_shader_parameter("inset", inset)
	surface.set_shader_parameter("corner_radius", radius)
	surface.set_shader_parameter("opacity", opacity)
	surface.set_shader_parameter("shadow", shadow)
	rect.material = surface
	return rect

func build(owner_scene: Node3D) -> void:
	scene = owner_scene
	font = FontFile.new()
	font.load_dynamic_font(ProjectSettings.globalize_path("res://InterVariable.ttf"))
	font.oversampling = 2.0
	font.hinting = TextServer.HINTING_LIGHT
	font.subpixel_positioning = TextServer.SUBPIXEL_POSITIONING_AUTO
	scene.ui_viewport = SubViewport.new()
	scene.ui_viewport.transparent_bg = true
	scene.ui_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	scene.ui_viewport.handle_input_locally = true
	scene.ui_viewport.physics_object_picking = false
	scene.add_child(scene.ui_viewport)
	scene.dock = MeshInstance3D.new()
	scene.dock.mesh = QuadMesh.new()
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.albedo_texture = scene.ui_viewport.get_texture()
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	scene.dock.material_override = material
	scene.seat.add_child(scene.dock)
	# Native preview routes input through a transparent SteamVR hit surface.
	# Keep the visible UI in projection so it cannot cover system controllers.
	if scene.xr_active and OS.get_environment("FRAME_CINEMA_UNIFIED_UI") != "1":
		composition_layer = OpenXRCompositionLayerQuad.new()
		composition_layer.visible = false
		# Godot 4.7.2 queries the transform during PARENTED, before ENTER_TREE.
		# A direct XROrigin parent uses its local transform and avoids that query.
		scene.origin.add_child(composition_layer)
		composition_layer.alpha_blend = true
		# The runtime presents the UI directly; the mesh remains for picking and
		# the inspection camera. It must not also appear in the projection image.
		scene.dock.layers = UI_MESH_LAYER
		scene.camera.cull_mask &= ~UI_MESH_LAYER
	show_page("library")

func show_page(next: String) -> void:
	page = next
	focus_hint_age = 0.0
	focus_notice_panel = null
	room_description = null
	for node in scene.ui_viewport.get_children():
		node.free()
	scene.screen_button = null
	scene.environment_button = null
	scene.light_button = null
	scene.media_buttons.clear()
	scene.play_button = null
	scene.fullscreen_button = null
	scene.ambient_button = null
	scene.ambient_brightness_button = null
	var height := 112 if page == "focus" else (650 if page == "library" else (620 if page == "room" else (620 if page == "more" else 186)))
	var width := 400 if page == "focus" else 1600
	scene.ui_viewport.size_2d_override = Vector2i(width, height)
	scene.ui_viewport.size_2d_override_stretch = true
	scene.ui_viewport.size = Vector2i(width, height) * RENDER_SCALE
	var full: Vector2 = scene._ui_size()
	glass = null
	if page in ["library", "room", "more"]:
		glass = glass_rect(full, WINDOW_RADIUS, 0.86 if page == "room" else 0.84)
		scene.ui_viewport.add_child(glass)
	panel = PanelContainer.new()
	panel.position = Vector2(16, 16)
	panel.size = full - Vector2(32, 32)
	var padding := 0
	if page in ["library", "room", "more"]:
		padding = 40
	var background := box(Color.TRANSPARENT, int(WINDOW_RADIUS), padding)
	if page in ["room", "more"]:
		background.content_margin_top = 30
		background.content_margin_bottom = 30
	elif page == "library":
		background.content_margin_top = 36
		background.content_margin_bottom = 34
	panel.add_theme_stylebox_override("panel", background)
	scene.ui_viewport.add_child(panel)
	column = VBoxContainer.new()
	column.add_theme_constant_override("separation", 0 if page in ["library", "room", "more"] else 8)
	panel.add_child(column)
	if page == "library":
		library()
	elif page == "room":
		room()
	elif page == "more":
		more()
	elif page == "focus":
		focus()
	else:
		player()
	scene.dock_cursor = Panel.new()
	scene.dock_cursor.size = Vector2(16, 16)
	scene.dock_cursor.mouse_filter = Control.MOUSE_FILTER_IGNORE
	scene.dock_cursor.visible = false
	scene.dock_cursor.add_theme_stylebox_override("panel", box(Color.WHITE, 8, 0))
	scene.ui_viewport.add_child(scene.dock_cursor)
	scene._position_dock()
	refresh_settings()

func focus() -> void:
	# A compact glass pill: the reminder stays quiet over the picture.
	var pill := glass_rect(Vector2(400, 112), 40.0, 0.80, 0.8, 16.0)
	scene.ui_viewport.add_child(pill)
	scene.ui_viewport.move_child(pill, 0)
	glass = pill
	var return_row := row(column, 0)
	spacer(return_row)
	var restore := control("Controls · B or trigger", "services", scene._show_controls, 360)
	restore.custom_minimum_size.y = 80
	restore.add_theme_stylebox_override("normal", box(Color.TRANSPARENT, 40, 18))
	restore.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 0.12), 40, 18))
	restore.add_theme_font_override("font", face(560, 23))
	restore.add_theme_font_size_override("font_size", 23)
	return_row.add_child(restore)
	spacer(return_row)
	focus_notice_panel = PanelContainer.new()
	var notice := box(Color(0.10, 0.105, 0.12, 0.90), 30, 18)
	notice.border_color = Color(1, 1, 1, 0.10)
	notice.set_border_width_all(1)
	focus_notice_panel.add_theme_stylebox_override("panel", notice)
	focus_notice_panel.visible = false
	column.add_child(focus_notice_panel)
	scene.status_label = label("", 24, INK, 520)
	scene.status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	focus_notice_panel.add_child(scene.status_label)

func update_focus_notice(message: String) -> void:
	if page != "focus":
		return
	# Resize the existing surface, preserving the button and any held GUI press.
	# Its fixed width/center and top anchoring keep its world position unchanged.
	var size := Vector2i(960, 204) if not message.is_empty() else Vector2i(400, 112)
	scene.status_label.text = message
	var was_notice := focus_notice_panel.visible
	focus_notice_panel.visible = not message.is_empty()
	if not message.is_empty() or was_notice:
		focus_hint_age = 0.0
		panel.modulate.a = 1.0
		if is_instance_valid(glass): glass.modulate.a = 1.0
		scene.dock.visible = true
	if scene.ui_viewport.size_2d_override != size:
		scene.ui_viewport.size_2d_override = size
		scene.ui_viewport.size = size * RENDER_SCALE
		panel.size = Vector2(size) - Vector2(32, 32)
		if is_instance_valid(glass):
			# The pill only frames the restore control; notices carry their own plate.
			glass.size = Vector2(400, 112)
			glass.position = Vector2((size.x - 400) / 2.0, 0)
		scene._position_dock()

func tick_focus_hint(delta: float) -> void:
	if page != "focus":
		return
	if focus_notice_panel.visible or scene.pointer_down or scene.browser_keyboard:
		focus_hint_age = 0.0
	elif not scene.xr_active or scene._placement_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED]:
		# Steam's pointer may own input focus while the reminder is visible.
		# Hovering the reminder must not keep it on screen indefinitely.
		focus_hint_age += maxf(delta, 0.0)
	var fade := clampf((focus_hint_age - FOCUS_HINT_HOLD) / FOCUS_HINT_FADE, 0, 1)
	panel.modulate.a = 1.0 - smoothstep(0.0, 1.0, fade)
	if is_instance_valid(glass): glass.modulate.a = panel.modulate.a
	# Remove the hit target as well as its pixels. B still restores the controls;
	# real recovery messages reveal this same surface without leaving Focus.
	scene.dock.visible = fade < 1.0

func service_card(entry: Dictionary, width: float, height: float) -> Button:
	var id := str(entry.id)
	var card := button("", scene._open_service.bind(id), width, Color.TRANSPARENT)
	card.custom_minimum_size.y = height
	card.set_meta("service_id", id)
	card.tooltip_text = str(entry.name)
	card.accessibility_name = str(entry.name)
	for state in ["normal", "hover", "pressed", "hover_pressed", "disabled"]:
		card.add_theme_stylebox_override(state, box(Color.TRANSPARENT, 40, 0))
	card.add_theme_stylebox_override("focus", box(Color.TRANSPARENT, 40, 0))
	var art := ColorRect.new()
	art.name = "ServiceArtwork"
	art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	art.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var surface := ShaderMaterial.new()
	var artwork_path := "res://branding/tvos-%s.%s" % [id, "jpg" if id == "disneyplus" else "png"]
	var has_artwork := ResourceLoader.exists(artwork_path)
	var light_artwork := has_artwork and id == "netflix"
	if has_artwork:
		var artwork: Texture2D = load(artwork_path)
		surface.shader = load("res://cinema_service_art.gdshader")
		surface.set_shader_parameter("artwork", artwork)
		surface.set_shader_parameter("artwork_size", artwork.get_size())
		surface.set_shader_parameter("light_artwork", light_artwork)
	else:
		surface.shader = load("res://cinema_card.gdshader")
		surface.set_shader_parameter("hue", CARD_HUES.get(id, Color(str(entry.color))))
	surface.set_shader_parameter("card_size", Vector2(width, height))
	surface.set_shader_parameter("corner_radius", 40.0)
	art.material = surface
	card.add_child(art)
	art.resized.connect(func(): surface.set_shader_parameter("card_size", art.size))
	# The artwork retains its original colours; only the rim changes on focus.
	var update_highlight := func():
		surface.set_shader_parameter("hover", 1.0 if card.is_hovered() or card.has_focus() else 0.0)
		art.queue_redraw()
	card.mouse_entered.connect(update_highlight)
	card.mouse_exited.connect(update_highlight)
	card.focus_entered.connect(update_highlight)
	card.focus_exited.connect(update_highlight)
	# Five tiles are narrower than the original three. Keep a readable name
	# centred above the open button when no provider-logo asset is available.
	var name_width := width - 48.0
	var name_size := 46
	while name_size > 28 and face(700, name_size, -1).get_string_size(str(entry.name), HORIZONTAL_ALIGNMENT_LEFT, -1, name_size).x > name_width:
		name_size -= 1
	var name := label(str(entry.name), name_size, Color.WHITE, 700, -1)
	name.name = "ServiceName"
	name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	name.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	name.clip_text = true
	name.size = Vector2(name_width, height * 0.46)
	name.position = Vector2(24, (height - name.size.y) * 0.5 - 8)
	name.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.35))
	name.add_theme_constant_override("shadow_offset_y", 2)
	name.add_theme_constant_override("shadow_outline_size", 8)
	card.add_child(name)
	# Use the original Apple TV artwork, including each provider's colours.
	name.visible = not has_artwork
	var open := PanelContainer.new()
	open.mouse_filter = Control.MOUSE_FILTER_IGNORE
	open.size = Vector2(56, 56)
	open.position = Vector2(width - 56 - 28, height - 56 - 30)
	var circle := box(Color(0, 0, 0, 0.08) if light_artwork else Color(1, 1, 1, 0.16), 28, 0)
	circle.border_color = Color(0, 0, 0, 0.13) if light_artwork else Color(1, 1, 1, 0.22)
	circle.set_border_width_all(1)
	open.add_theme_stylebox_override("panel", circle)
	var arrow := TextureRect.new()
	arrow.texture = icon("chevron")
	arrow.modulate = DARK_INK if light_artwork else Color.WHITE
	arrow.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	arrow.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	arrow.custom_minimum_size = Vector2(26, 26)
	arrow.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var center := CenterContainer.new()
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	center.add_child(arrow)
	open.add_child(center)
	card.add_child(open)
	return card

func room_thumbnail(name: String) -> Texture2D:
	if not room_images.has(name):
		var path := ProjectSettings.globalize_path("res://environments/" + name + "-thumb.png")
		var image := Image.load_from_file(path) if FileAccess.file_exists(path) else null
		if image:
			image.generate_mipmaps()
			room_images[name] = ImageTexture.create_from_image(image)
	return room_images.get(name)

func photo(texture: Texture2D, size: Vector2, radius: float, scrim: float) -> TextureRect:
	var picture := TextureRect.new()
	picture.texture = texture
	picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	picture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	picture.mouse_filter = Control.MOUSE_FILTER_IGNORE
	picture.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var treatment := ShaderMaterial.new()
	treatment.shader = load("res://cinema_thumbnail.gdshader")
	treatment.set_shader_parameter("card_size", size)
	treatment.set_shader_parameter("corner_radius", radius)
	treatment.set_shader_parameter("scrim", scrim)
	picture.resized.connect(func(): treatment.set_shader_parameter("card_size", picture.size))
	picture.material = treatment
	return picture

func library() -> void:
	column.add_child(label("FRAME CINEMA", 19, FAINT, 650, 3))
	gap(column, 6)
	var top := row(column)
	var title := label("What would you like to watch?", 46, INK, 660, -1)
	top.add_child(title)
	spacer(top)
	var recenter := control("Recenter", "recenter", scene._recenter, 188)
	recenter.custom_minimum_size.y = 60
	top.add_child(recenter)
	gap(column, 6)
	column.add_child(label("Each service remembers your sign-in on this headset.", 23, MUTED, 480))
	gap(column, 30)
	var cards := row(column, 28)
	var count: int = maxi(scene.services.size(), 1)
	var width := (1488.0 - 28.0 * (count - 1)) / count
	for entry in scene.services:
		cards.add_child(service_card(entry, width, 252))
	gap(column, 30)
	var bottom := row(column, 18)
	var preview: Texture2D = room_thumbnail(scene.ENVIRONMENTS[scene.environment_index]) if scene.environment_index >= 0 else null
	if preview:
		var frame := Control.new()
		frame.custom_minimum_size = Vector2(112, 64)
		frame.mouse_filter = Control.MOUSE_FILTER_IGNORE
		frame.add_child(photo(preview, Vector2(112, 64), 16.0, 0.0))
		bottom.add_child(frame)
	var environment := VBoxContainer.new()
	environment.add_theme_constant_override("separation", 0)
	environment.alignment = BoxContainer.ALIGNMENT_CENTER
	environment.add_child(label("Environment", 19, FAINT, 560))
	environment.add_child(label(scene._environment_name(), 27, INK, 600))
	bottom.add_child(environment)
	spacer(bottom)
	var change := control("Change room", "room", scene._show_room, 236)
	change.custom_minimum_size.y = 60
	bottom.add_child(change)
	scene.status_label = label("", 20, MUTED)
	column.add_child(scene.status_label)

func control_group(parent: Node) -> HBoxContainer:
	var holder := row(parent, 6)
	return holder

# Indeterminate progress: a short arc turning about once a second.
class Spinner extends Control:
	var angle := 0.0
	func _process(delta: float) -> void:
		if not is_visible_in_tree():
			return
		angle = fmod(angle + delta * 6.0, TAU)
		queue_redraw()
	func _draw() -> void:
		var radius := minf(size.x, size.y) * 0.5 - 2.0
		draw_arc(size * 0.5, radius, 0.0, TAU, 40, Color(1, 1, 1, 0.16), 3.0, true)
		draw_arc(size * 0.5, radius, angle, angle + 1.9, 24, Color(1, 1, 1, 0.92), 3.0, true)

var loading_plate: PanelContainer
var loading_label: Label
var status_plate: PanelContainer

func player() -> void:
	# visionOS-style playback ornament: two caption chips and one glass capsule.
	var top := row(column)
	heading = label(scene._service_name(), 23, INK, 640)
	top.add_child(chip(heading))
	spacer(top)
	scene.status_label = label("Opening…", 21, Color(1, 1, 1, 0.80), 520)
	scene.status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	scene.status_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	# Opening a service takes several seconds: say so where the eye already is.
	loading_plate = PanelContainer.new()
	loading_plate.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var loading_fill := box(Color(0.11, 0.115, 0.13, 0.86), 26, 0)
	loading_fill.content_margin_left = 18
	loading_fill.content_margin_right = 24
	loading_fill.content_margin_top = 8
	loading_fill.content_margin_bottom = 8
	loading_fill.border_color = Color(1, 1, 1, 0.12)
	loading_fill.set_border_width_all(1)
	loading_plate.add_theme_stylebox_override("panel", loading_fill)
	var loading_row := HBoxContainer.new()
	loading_row.add_theme_constant_override("separation", 14)
	var spinner := Spinner.new()
	spinner.custom_minimum_size = Vector2(30, 30)
	spinner.mouse_filter = Control.MOUSE_FILTER_IGNORE
	loading_row.add_child(spinner)
	loading_label = label("", 25, INK, 600)
	loading_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	loading_row.add_child(loading_label)
	loading_plate.add_child(loading_row)
	loading_plate.visible = false
	top.add_child(loading_plate)
	spacer(top)
	var status_chip := chip(scene.status_label)
	status_plate = status_chip
	top.add_child(status_chip)
	var bar_holder := Control.new()
	bar_holder.custom_minimum_size = Vector2(1568, 106)
	bar_holder.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(bar_holder)
	var bar_glass := glass_rect(Vector2(1568, 106), 47.0, 0.86, 0.9, 4.0)
	bar_holder.add_child(bar_glass)
	var controls := HBoxContainer.new()
	controls.add_theme_constant_override("separation", 6)
	controls.position = Vector2(18, 7)
	controls.size = Vector2(1532, 92)
	controls.alignment = BoxContainer.ALIGNMENT_CENTER
	bar_holder.add_child(controls)
	var navigation := control_group(controls)
	for entry in [["Services", "services", scene._show_library, 176], ["Back", "back", scene._browser_command.bind(1), 124]]:
		var item := control(entry[0], entry[1], entry[2], entry[3])
		item.custom_minimum_size.y = 72
		item.add_theme_stylebox_override("normal", box(Color.TRANSPARENT, 36, 16))
		item.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 0.12), 36, 16))
		navigation.add_child(item)
	spacer(controls)
	var transport := control_group(controls)
	transport.add_theme_constant_override("separation", 18)
	for entry in [["−10 s", "back_10"], ["Play", "toggle_play"], ["+10 s", "forward_10"]]:
		var media := button(entry[0], scene._media_command.bind(entry[1]), 72)
		media.disabled = not scene._media_enabled(entry[1])
		media.set_meta("media_operation", entry[1])
		media.tooltip_text = "Available when a video is open"
		transport.add_child(media)
		scene.media_buttons.append(media)
		if entry[1] == "toggle_play":
			scene.play_button = media
			media.icon = icon("play")
			icon_only(media, 84, 34)
			# Primary action: a solid white disc with a dark glyph.
			media.add_theme_stylebox_override("normal", box(Color(1, 1, 1, 0.94), 42, 0))
			media.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 1.0), 42, 0))
			media.add_theme_stylebox_override("pressed", box(Color(0.86, 0.87, 0.9, 1.0), 42, 0))
			media.add_theme_stylebox_override("hover_pressed", box(Color(0.86, 0.87, 0.9, 1.0), 42, 0))
			media.add_theme_stylebox_override("disabled", box(Color(1, 1, 1, 0.16), 42, 0))
			for state in ["icon_normal_color", "icon_hover_color", "icon_pressed_color", "icon_hover_pressed_color", "icon_focus_color"]:
				media.add_theme_color_override(state, DARK_INK)
			media.add_theme_color_override("icon_disabled_color", Color(1, 1, 1, 0.35))
		else:
			media.icon = icon("skip_back" if entry[1] == "back_10" else "skip_forward")
			icon_only(media, 72, 42)
	spacer(controls)
	var tools := control_group(controls)
	for entry in [["Keyboard", "keyboard", scene._keyboard, 178], ["Room", "room", scene._show_room, 138], ["Focus", "focus", scene._focus_screen, 140], ["More", "more", scene._show_recovery, 128]]:
		var item := control(entry[0], entry[1], entry[2], entry[3])
		item.custom_minimum_size.y = 72
		item.add_theme_stylebox_override("normal", box(Color.TRANSPARENT, 36, 16))
		item.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 0.12), 36, 16))
		tools.add_child(item)

func update_loading(text: String) -> void:
	if not is_instance_valid(loading_plate):
		return
	loading_plate.visible = not text.is_empty()
	loading_label.text = text
	if is_instance_valid(status_plate):
		status_plate.visible = text.is_empty()

func chip(content: Label) -> PanelContainer:
	var plate := PanelContainer.new()
	plate.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var fill := box(Color(0.11, 0.115, 0.13, 0.78), 20, 0)
	fill.content_margin_left = 18
	fill.content_margin_right = 18
	fill.content_margin_top = 5
	fill.content_margin_bottom = 6
	fill.border_color = Color(1, 1, 1, 0.08)
	fill.set_border_width_all(1)
	plate.add_theme_stylebox_override("panel", fill)
	content.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	plate.add_child(content)
	# Status text is often empty; draw no plate rather than an empty dot.
	var sync_plate := func() -> void: plate.self_modulate.a = 1.0 if content.text != "" else 0.0
	content.minimum_size_changed.connect(sync_plate)
	sync_plate.call()
	return plate

func setting_label(parent: Node, text: String, width: float) -> void:
	var node := label(text, 22, MUTED, 540)
	node.custom_minimum_size.x = width
	node.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	parent.add_child(node)

func room() -> void:
	var top := row(column)
	var titles := VBoxContainer.new()
	titles.add_theme_constant_override("separation", 0)
	titles.add_child(label("Environment", 36, INK, 660, -1))
	top.add_child(titles)
	spacer(top)
	var done := button("Done · B", scene._close_room, 172)
	done.custom_minimum_size.y = 58
	top.add_child(done)
	gap(column, 16)
	var places := row(column, 16)
	var options: Array[int] = scene.room.available_indices()
	var card_width := (1488.0 - 16.0 * (options.size() - 1)) / options.size()
	var card_height := 132.0
	for index in options:
		var selected: bool = index == scene.environment_index
		var card := button("", scene._set_environment.bind(index), card_width, Color.TRANSPARENT)
		card.custom_minimum_size.y = card_height
		card.tooltip_text = scene.NAMES[index]
		card.accessibility_name = scene.NAMES[index]
		card.set_meta("room_id", index)
		for state in ["normal", "hover", "pressed", "hover_pressed"]:
			card.add_theme_stylebox_override(state, box(Color(1, 1, 1, 0.06), 28, 0))
		places.add_child(card)
		var name: String = scene.ENVIRONMENTS[index]
		var preview: Texture2D = room_thumbnail(name)
		if preview:
			card.add_child(photo(preview, Vector2(card_width, card_height), 28.0, 1.0))
		else:
			# Dark Room has no photograph: a deep vignette reads as a theatre.
			var dark := ColorRect.new()
			dark.mouse_filter = Control.MOUSE_FILTER_IGNORE
			dark.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
			var plate := ShaderMaterial.new()
			plate.shader = load("res://cinema_thumbnail.gdshader")
			plate.set_shader_parameter("card_size", Vector2(card_width, card_height))
			plate.set_shader_parameter("corner_radius", 28.0)
			plate.set_shader_parameter("scrim", 1.0)
			plate.set_shader_parameter("dark_room", true)
			dark.material = plate
			card.add_child(dark)
		var caption := label(scene.NAMES[index], 23, Color.WHITE, 620)
		caption.position = Vector2(20, card_height - 44)
		caption.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.5))
		caption.add_theme_constant_override("shadow_outline_size", 6)
		card.add_child(caption)
		var outline := Panel.new()
		outline.mouse_filter = Control.MOUSE_FILTER_IGNORE
		outline.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		var stroke := box(Color.TRANSPARENT, 28, 0)
		stroke.set_border_width_all(3 if selected else 1)
		var resting := Color(1, 1, 1, 0.95 if selected else 0.14)
		stroke.border_color = resting
		outline.add_theme_stylebox_override("panel", stroke)
		card.add_child(outline)
		if selected:
			var badge := PanelContainer.new()
			badge.mouse_filter = Control.MOUSE_FILTER_IGNORE
			badge.size = Vector2(34, 34)
			badge.position = Vector2(card_width - 34 - 14, 14)
			badge.add_theme_stylebox_override("panel", box(Color(1, 1, 1, 0.96), 17, 0))
			var mark := TextureRect.new()
			mark.texture = icon("check")
			mark.modulate = DARK_INK
			mark.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			mark.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
			mark.custom_minimum_size = Vector2(22, 22)
			mark.mouse_filter = Control.MOUSE_FILTER_IGNORE
			var middle := CenterContainer.new()
			middle.mouse_filter = Control.MOUSE_FILTER_IGNORE
			middle.add_child(mark)
			badge.add_child(middle)
			card.add_child(badge)
		card.mouse_entered.connect(func():
			stroke.border_color = Color(1, 1, 1, 1.0 if selected else 0.6)
			outline.queue_redraw())
		card.mouse_exited.connect(func():
			stroke.border_color = resting
			outline.queue_redraw())
	gap(column, 20)
	var settings := row(column, 12)
	setting_label(settings, "Screen", 176)
	var sizes := choices(settings)
	for entry in [["Small", 3.2], ["Medium", 4.2], ["Large", 5.4]]:
		var size_button := choice(entry[0], "screen", entry[1], scene._set_screen_width.bind(entry[1]), 168)
		size_button.tooltip_text = "%.1f m wide" % entry[1]
		sizes.add_child(size_button)
		if entry[1] == 5.4: scene.screen_button = size_button
	var recenter := control("Recenter", "recenter", scene._recenter, 196)
	recenter.custom_minimum_size.y = 68
	settings.add_child(recenter)
	var fit := button("Fit picture · " + ("On" if scene.fit_picture else "Off"), scene._toggle_picture_fit, 300)
	fit.custom_minimum_size.y = 68
	fit.tooltip_text = "Hide black bars in Focus; show the full picture while browsing"
	if scene.fit_picture:
		fit.add_theme_stylebox_override("normal", box(Color(1, 1, 1, 0.92), 32, 18))
		fit.add_theme_stylebox_override("hover", box(Color(1, 1, 1, 1.0), 32, 18))
		fit.add_theme_color_override("font_color", DARK_INK)
		fit.add_theme_color_override("font_hover_color", DARK_INK)
	settings.add_child(fit)
	gap(column, 12)
	var glow := row(column, 12)
	if scene._alpine_room():
		# Alpine's giant screen standing on the far shore, or a little lower.
		setting_label(glow, "Placement", 176)
		var heights := choices(glow)
		for index in scene.ALPINE_HEIGHT_NAMES.size():
			heights.add_child(choice(scene.ALPINE_HEIGHT_NAMES[index], "alpine_height", float(index), scene._set_alpine_height.bind(index), 200))
	else:
		setting_label(glow, "Ambient light", 176)
		var modes := choices(glow)
		for mode in scene.ambient.MODES.size():
			var option := choice(scene.ambient.MODES[mode], "ambient", float(mode), scene._set_ambient_mode.bind(mode), 220)
			option.tooltip_text = scene.ambient.DESCRIPTIONS[mode]
			modes.add_child(option)
			if mode == scene.ambient_mode: scene.ambient_button = option
	gap(column, 12)
	var brightness := row(column, 12)
	setting_label(brightness, "Glow", 176)
	var levels := choices(brightness)
	for value in [0.25, 0.5, 0.75, 1.0]:
		var option := choice("%d%%" % roundi(value * 100), "brightness", value, scene._set_ambient_brightness.bind(value), 96)
		levels.add_child(option)
		if is_equal_approx(value, scene.ambient_brightness): scene.ambient_brightness_button = option
	var divider := Control.new()
	divider.custom_minimum_size.x = 18
	brightness.add_child(divider)
	setting_label(brightness, "Room light", 130)
	var room_levels := choices(brightness)
	for entry in [["Dim", 0.2], ["Soft", 0.55], ["Bright", 1.0]]:
		var option := choice(entry[0], "light", entry[1], scene._set_room_light.bind(entry[1]), 140)
		room_levels.add_child(option)
		if entry[0] == "Soft": scene.light_button = option
	gap(column, 14)
	room_description = label(room_hint(), 21, FAINT, 480)
	room_description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(room_description)
	scene.status_label = label("", 21, INK, 520)
	scene.status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(scene.status_label)

func room_hint() -> String:
	if scene._alpine_room(): return "Screen glow is off in Alpine. Room light adjusts the scenery."
	return scene.ambient.DESCRIPTIONS[scene.ambient_mode] + (". Fit picture hides black bars in Focus." if scene.fit_picture else ". Focus dims the room and hides controls.")

func more() -> void:
	var top := row(column)
	top.add_child(label("Playback options", 36, INK, 660, -1))
	spacer(top)
	var done := button("Done · B", scene._close_room, 172)
	done.custom_minimum_size.y = 58
	top.add_child(done)
	gap(column, 26)
	var stereo_title := row(column, 12)
	stereo_title.add_child(label("2D to 3D", 26, INK, 620))
	var tag := PanelContainer.new()
	tag.add_theme_stylebox_override("panel", box(Color(1, 1, 1, 0.12), 14, 0))
	var tag_text := label("PREVIEW", 15, MUTED, 650, 2)
	tag_text.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	var tag_pad := MarginContainer.new()
	tag_pad.add_theme_constant_override("margin_left", 12)
	tag_pad.add_theme_constant_override("margin_right", 12)
	tag_pad.add_child(tag_text)
	tag.add_child(tag_pad)
	var tag_center := CenterContainer.new()
	tag_center.add_child(tag)
	stereo_title.add_child(tag_center)
	gap(column, 12)
	var stereo_row := row(column, 12)
	var strength_surface := choices(stereo_row)
	strength_surface.get_parent().size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	var strengths := ["Off", "Subtle", "Normal", "Strong"]
	for index in strengths.size():
		var option := choice(strengths[index], "stereo", float(index), scene._set_stereo_mode.bind(index), 200)
		option.size_flags_horizontal = Control.SIZE_FILL
		option.button_pressed = scene._effective_stereo_mode() == index
		option.disabled = index > 0 and not scene._dark_room()
		strength_surface.add_child(option)
	gap(column, 10)
	column.add_child(label("Dark Room only · Full-screen video in Focus. Press B to return to 2D." if scene._dark_room() else "Choose Dark Room in Environment to enable 3D.", 21, FAINT, 480))
	gap(column, 28)
	var actions := row(column, 14)
	var fullscreen := button("Exit full screen", scene._media_command.bind("exit_fullscreen"), 300)
	scene.fullscreen_button = fullscreen
	fullscreen.disabled = not scene._media_enabled("exit_fullscreen")
	actions.add_child(fullscreen)
	actions.add_child(button("Reload service", scene._browser_command.bind(2), 300))
	var reopen := button("Reopen service", scene._reopen_service, 300)
	reopen.tooltip_text = "Restarts the service and keeps your sign-in"
	actions.add_child(reopen)
	# Developer only (FRAME_CINEMA_DEV=1): per-room GPU cost split (IPC folder).
	if OS.get_environment("FRAME_CINEMA_DEV") == "1":
		var profile := button("Profiling…" if scene.profiling else "Profile room", scene._profile_room, 240)
		profile.disabled = scene.profiling
		profile.tooltip_text = "About 25 s; keep your head still"
		actions.add_child(profile)
	gap(column, 12)
	column.add_child(label("Reopen restarts the service and keeps your sign-in.", 21, FAINT, 480))
	gap(column, 6)
	scene.status_label = label("Use the service's player for captions, audio language and profiles.", 21, MUTED, 480)
	scene.status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(scene.status_label)

func sync_composition() -> void:
	if not composition_layer:
		return
	composition_layer.transform = scene.origin.global_transform.affine_inverse() * scene.dock.global_transform
	var xr := XRServer.find_interface("OpenXR")
	var head: XRPositionalTracker = XRServer.get_tracker("head")
	var pose: XRPose = head.get_pose("default") if head else null
	var presenting: bool = scene.dock.visible and xr.get_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED] and pose != null and pose.has_tracking_data and pose.tracking_confidence != XRPose.XR_TRACKING_CONFIDENCE_NONE
	if presenting == (composition_layer.layer_viewport != null):
		return
	# A synchronized/standby session does not submit projection views. Keeping
	# its UI swapchain attached makes Godot acquire images it cannot release.
	composition_layer.layer_viewport = scene.ui_viewport if presenting else null
	composition_layer.visible = presenting
