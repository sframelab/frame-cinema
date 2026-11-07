extends Node

var scene: Node3D
var native: Object
var position := Vector2(-1, -1)
var inside := false
var pressed := false
var last_page := ""
var texture_dirty := true
var texture_pending := false
var next_texture_msec := 0
var last_surface: Array = []
var uploaded_size := Vector2i.ZERO
const UI_MESH_LAYER := 1 << 18

func mark_texture_dirty() -> void:
	texture_dirty = true
	# Native mode reads pixels only after a change: render the UI viewport once per
	# change instead of every frame (its glass/card shaders cover up to 3200x1300).
	if native and is_instance_valid(scene) and is_instance_valid(scene.ui_viewport):
		scene.ui_viewport.render_target_update_mode = SubViewport.UPDATE_ONCE

func watch_canvas(node: Variant) -> void:
	if not is_instance_valid(node):
		return
	if not is_instance_valid(scene) or not is_instance_valid(scene.ui_viewport):
		return
	if node != scene.ui_viewport and not scene.ui_viewport.is_ancestor_of(node):
		return
	if node is CanvasItem:
		if not node.draw.is_connected(mark_texture_dirty):
			node.draw.connect(mark_texture_dirty)
		if not node.visibility_changed.is_connected(mark_texture_dirty):
			node.visibility_changed.connect(mark_texture_dirty)
	for child in node.get_children():
		watch_canvas(child)
	mark_texture_dirty()

func node_added(node: Node) -> void:
	watch_canvas.call_deferred(node)

func capture_ui() -> void:
	texture_pending = true
	texture_dirty = false
	await RenderingServer.frame_post_draw
	if not is_instance_valid(scene) or not is_instance_valid(scene.ui_viewport) or not native:
		texture_pending = false
		return
	var texture: Texture2D = scene.ui_viewport.get_texture()
	var picture: Image = texture.get_image() if texture else null
	if picture and not picture.is_empty():
		if picture.get_format() != Image.FORMAT_RGBA8:
			picture.convert(Image.FORMAT_RGBA8)
		var pixels: PackedByteArray = picture.get_data()
		# Retain the GPU image; C++ skips uploads when rendered pixels are unchanged.
		if native.upload_ui(pixels, picture.get_width(), picture.get_height()):
			uploaded_size = Vector2i(picture.get_width(), picture.get_height())
		else:
			texture_dirty = true
	else:
		texture_dirty = true
	next_texture_msec = Time.get_ticks_msec() + 67
	texture_pending = false

func _ready() -> void:
	process_priority = 10
	if not Engine.has_singleton("FrameNativeUI"):
		set_process(false)
		return
	native = Engine.get_singleton("FrameNativeUI")
	set_meta("native_input", true)
	# Keep this mesh for the independent observer only; native pixels are sharp
	# and in the same compositor ownership group as the successful checker.
	scene.dock.layers = UI_MESH_LAYER
	scene.camera.cull_mask &= ~UI_MESH_LAYER
	scene.ui_viewport.render_target_update_mode = SubViewport.UPDATE_ONCE
	watch_canvas(scene.ui_viewport)
	get_tree().node_added.connect(node_added)

func motion(next: Vector2) -> void:
	# CanvasItem.draw marks actual hover redraws. Ray movement within the same
	# button must not force a full-resolution GPU readback every capture interval.
	var event := InputEventMouseMotion.new()
	event.position = next
	event.global_position = next
	event.relative = next - position
	event.button_mask = MOUSE_BUTTON_MASK_LEFT if pressed else 0
	position = next
	scene.ui_viewport.push_input(event, true)

func button(down: bool, next: Vector2) -> void:
	if down and scene.has_method("_note_activity"): scene._note_activity()
	mark_texture_dirty()
	motion(next)
	pressed = down
	scene.pointer_down = down
	var event := InputEventMouseButton.new()
	event.position = next
	event.global_position = next
	event.button_index = MOUSE_BUTTON_LEFT
	event.button_mask = MOUSE_BUTTON_MASK_LEFT if down else 0
	event.pressed = down
	scene.ui_viewport.push_input(event, true)

func leave() -> void:
	if pressed:
		button(false, Vector2(-1, -1))
	if inside:
		scene.ui_viewport.notify_mouse_exited()
	inside = false
	scene.mouse_inside = false
	motion(Vector2(-1, -1))

func _process(_delta: float) -> void:
	if not native or not scene or not scene.ui_viewport or not scene.dock:
		return
	var surface: Array = [scene.ui.page, scene.ui_viewport.size, scene.dock.visible,
		scene.ui.panel.modulate if is_instance_valid(scene.ui.panel) else Color.WHITE]
	if surface != last_surface:
		last_surface = surface
		mark_texture_dirty()
	if texture_dirty and not texture_pending and scene.dock.visible and Time.get_ticks_msec() >= next_texture_msec:
		capture_ui()
	if last_page != scene.ui.page:
		mark_texture_dirty()
		uploaded_size = Vector2i.ZERO
		leave()
		last_page = scene.ui.page
	var xr := XRServer.find_interface("OpenXR")
	var scene_visible: bool = scene.xr_active and xr.get_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED]
	# Poll even after the dock disappears. Consume the wake press before any
	# queued mouse/shortcut events can act on the newly revealed controls.
	if consume_focus_wake(scene_visible):
		return
	var showing: bool = scene.xr_active and scene.placed and not scene.placement_pending and scene.dock.visible
	# A stale layout must not receive input while its replacement is still uploading.
	showing = showing and uploaded_size == scene.ui_viewport.size
	showing = showing and xr.get_session_state() in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED]
	var screen: Transform3D = scene.seat.global_transform * Transform3D(Basis.IDENTITY, scene._screen_center())
	var relative: Transform3D = screen.affine_inverse() * scene.dock.global_transform
	var events: Array = native.update_ui(relative, scene.dock.mesh.size, scene._ui_size(), showing)
	consume_events(events)
	if not showing:
		leave()
	# SteamVR draws the cursor; avoid a second application cursor underneath it.
	scene.dock_cursor.visible = false

func _exit_tree() -> void:
	if native:
		native.close()

func consume_focus_wake(scene_visible: bool) -> bool:
	var idle: bool = scene.get("viewing_idle") != null and scene.viewing_idle.hidden
	if native.poll_focus_wake(scene_visible and (scene.focused_view or idle) and not scene.browser_keyboard):
		scene._show_controls()
		leave()
		return true
	return false

func consume_events(events: Array) -> void:
	for item in events:
		var kind: String = item.get("kind", "")
		if kind == "shortcut":
			if scene.has_method("_note_activity"): scene._note_activity()
			if scene.focused_view and not scene.browser_keyboard:
				scene._show_controls()
				return
			match int(item.get("index", -1)):
				0: scene._cycle_environment()
				1: scene._toggle_controls()
				2, 4, 5: scene._recenter("controller shortcut")
				3: scene._browser_command(1)
				6, 7: scene._keyboard()
		elif kind == "texture_lost":
			mark_texture_dirty()
			uploaded_size = Vector2i.ZERO
		elif kind in ["move", "click"]:
			if not inside:
				scene.ui_viewport.notify_mouse_entered()
			inside = true
			scene.mouse_inside = true
			var point: Vector2 = item.position
			if kind == "move":
				motion(point)
			else:
				button(true, point)
				button(false, point)
				# The action may rebuild the page; discard the old-page event batch.
				return
		elif kind in ["cancel", "leave"]:
			leave()
		elif kind == "hover" and not item.get("inside", false):
			leave()
		elif kind == "scroll" and inside:
			var amount: float = float(item.get("delta", 0.0))
			if not is_finite(amount) or is_zero_approx(amount):
				continue
			if scene.has_method("_note_activity"): scene._note_activity()
			var wheel := InputEventMouseButton.new()
			wheel.position = position
			wheel.global_position = position
			wheel.button_index = MOUSE_BUTTON_WHEEL_UP if amount > 0 else MOUSE_BUTTON_WHEEL_DOWN
			wheel.factor = absf(amount)
			wheel.pressed = true
			scene.ui_viewport.push_input(wheel, true)
