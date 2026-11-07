extends SceneTree

# Actual library controls + native-menu event route, without XR, service login,
# browser processes, preferences or production IPC. Assets/font must be present.
class LibraryHost extends Node3D:
	var services: Array
	var ui_viewport: SubViewport
	var dock: MeshInstance3D
	var dock_cursor: Panel
	var seat := Node3D.new()
	var xr_active := false
	var mouse_inside := false
	var pointer_down := false
	var environment_index := -1
	var ENVIRONMENTS: Array = []
	var status_label: Label
	var screen_button: Button
	var environment_button: Button
	var light_button: Button
	var media_buttons: Array = []
	var play_button: Button
	var fullscreen_button: Button
	var ambient_button: Button
	var ambient_brightness_button: Button
	var selected: Array = []
	func _ui_size() -> Vector2: return Vector2(ui_viewport.size_2d_override)
	func _position_dock() -> void: pass
	func _open_service(id: String) -> void: selected.append(id)
	func _recenter() -> void: pass
	func _show_room() -> void: pass
	func _environment_name() -> String: return "Dark Room"

var failures := 0
var checks := 0

func _initialize() -> void:
	run.call_deferred()

func check(ok: bool, message: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(message)

func run() -> void:
	var host := LibraryHost.new()
	host.services = JSON.parse_string(FileAccess.get_file_as_string("res://services.json"))
	root.add_child(host)
	host.add_child(host.seat)
	var ui = load("res://cinema_ui.gd").new()
	ui.build(host)
	await process_frame
	await process_frame
	var native_input: Node = load("res://native-ui/native_ui.gd").new()
	native_input.scene = host
	var cards: Array[Button] = []
	for button in host.ui_viewport.find_children("*", "Button", true, false):
		check(Rect2(Vector2.ZERO, host._ui_size()).encloses(button.get_global_rect()), "Library button is outside the viewport")
		if button.has_meta("service_id"):
			cards.append(button)
	check(cards.size() == 5, "Library must show all five providers")
	var ids: Array = []
	var previous: Button
	for card in cards:
		var id: String = card.get_meta("service_id")
		ids.append(id)
		check(card.size.x >= 270 and card.size.y >= 250, "Provider target is too small: " + id)
		check(not card.accessibility_name.is_empty(), "Missing accessible provider name: " + id)
		check(card.focus_mode == Control.FOCUS_ALL, "Provider card cannot receive controller/keyboard focus: " + id)
		if previous:
			check(not previous.get_global_rect().intersects(card.get_global_rect()), "Provider hit targets overlap")
			check(previous.find_valid_focus_neighbor(SIDE_RIGHT) == card, "Right-navigation must reach the next provider")
			check(card.find_valid_focus_neighbor(SIDE_LEFT) == previous, "Left-navigation must reach the previous provider")
		previous = card
		var name: Label = card.get_node("ServiceName")
		var art: ColorRect = card.get_node("ServiceArtwork")
		var artwork: Texture2D = art.material.get_shader_parameter("artwork")
		var artwork_path := "res://branding/tvos-%s.%s" % [id, "jpg" if id == "disneyplus" else "png"]
		if ResourceLoader.exists(artwork_path):
			check(artwork != null and artwork.resource_path == artwork_path, "Provider artwork did not load: " + id)
			check(not name.visible, "Provider artwork unexpectedly fell back to plain text: " + id)
		else:
			check(name.visible, "No artwork and no visible name: " + id)
		if name.visible:
			var measured := name.get_theme_font("font").get_string_size(name.text, HORIZONTAL_ALIGNMENT_LEFT, -1, name.get_theme_font_size("font_size"))
			check(measured.x <= name.size.x, "Provider name is clipped: " + id)
			check(Rect2(Vector2.ZERO, card.size).encloses(name.get_rect()), "Provider name overflows its tile: " + id)
		var point := card.get_global_rect().get_center()
		native_input.consume_events([{"kind":"move", "position":point}, {"kind":"click", "position":point}])
		check(host.selected.size() == ids.size() and host.selected[-1] == id, "Native pointer activates wrong service: " + id)
	check(ids == ["netflix", "hbomax", "disneyplus", "primevideo", "plex"], "Provider IDs/order differ from catalog")
	check(host._ui_size() == Vector2(1600, 650) and host.ui_viewport.size == Vector2i(3200, 1300), "Library changes native texture or hit-target geometry")
	var output := OS.get_environment("FRAME_CINEMA_LIBRARY_PROOF")
	if not output.is_empty() and DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		var image := host.ui_viewport.get_texture().get_image()
		check(image != null and not image.is_empty(), "No library preview image")
		if image: image.save_png(output)
	native_input.leave()
	native_input.free()
	host.free()
	print(JSON.stringify({"service_library_checks": checks, "failures": failures, "services": ids, "native_input_fixture": true}))
	quit(1 if failures else 0)
