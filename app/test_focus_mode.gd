extends SceneTree

class Host extends Node3D:
	var xr_active := true
	var session_state := OpenXRInterface.SESSION_STATE_VISIBLE
	var mouse_inside := false
	var pointer_down := false
	var browser_keyboard := false
	var focused_view := true
	var dock := MeshInstance3D.new()
	var ui_viewport := SubViewport.new()
	var calls: Array = []
	func _input_available() -> bool: return not xr_active or session_state == OpenXRInterface.SESSION_STATE_FOCUSED
	func _placement_session_state() -> int: return session_state
	func _show_controls() -> void:
		focused_view = false
		calls.append("show")
	func _cycle_environment() -> void: calls.append("room")
	func _toggle_controls() -> void: calls.append("toggle")
	func _recenter(_reason: String) -> void: calls.append("recenter")
	func _browser_command(_command: int) -> void: calls.append("back")
	func _keyboard() -> void: calls.append("keyboard")

class Wake extends RefCounted:
	var requested := false
	var enabled := false
	func poll_focus_wake(value: bool) -> bool:
		enabled = value
		return enabled and requested

var checks := 0
var failures := 0
func check(ok: bool, title: String) -> void:
	checks += 1
	if not ok: failures += 1
	print(("PASS " if ok else "FAIL ") + title)
func _initialize() -> void: run.call_deferred()
func run() -> void:
	var host := Host.new()
	root.add_child(host)
	host.add_child(host.dock)
	host.add_child(host.ui_viewport)
	host.ui_viewport.size = Vector2i(400,112)
	var ui: RefCounted = load("res://cinema_ui.gd").new()
	ui.scene = host
	ui.page = "focus"
	ui.panel = PanelContainer.new()
	ui.focus_notice_panel = PanelContainer.new()
	ui.focus_notice_panel.visible = false
	for state in [OpenXRInterface.SESSION_STATE_VISIBLE, OpenXRInterface.SESSION_STATE_FOCUSED]:
		for hover in [false, true]:
			host.session_state = state
			host.mouse_inside = hover
			ui.focus_hint_age = 0.0
			ui.tick_focus_hint(0.35)
			check(ui.panel.modulate.a > 0.0 and ui.panel.modulate.a < 1.0, "reminder fades while visible, state=%d hover=%s" % [state,hover])
			ui.tick_focus_hint(0.5)
			check(not host.dock.visible and ui.panel.modulate.a == 0.0, "reminder and hit target disappear, state=%d hover=%s" % [state,hover])
	host.session_state = OpenXRInterface.SESSION_STATE_SYNCHRONIZED
	ui.focus_hint_age = 0.0
	ui.tick_focus_hint(5.0)
	check(ui.focus_hint_age == 0.0, "standby does not consume the reminder")
	host.session_state = OpenXRInterface.SESSION_STATE_VISIBLE
	ui.focus_notice_panel.visible = true
	ui.tick_focus_hint(5.0)
	check(host.dock.visible and ui.panel.modulate.a == 1.0, "recovery notice remains readable")
	ui.focus_notice_panel.visible = false
	ui.tick_focus_hint(1.0)
	check(not host.dock.visible, "cleared recovery notice can fade again")
	host.xr_active = false
	ui.focus_hint_age = 0.0
	ui.tick_focus_hint(1.0)
	check(not host.dock.visible, "non-XR preview reminder fades")
	var driver: Node = load("res://native-ui/native_ui.gd").new()
	driver.scene = host
	for index in 8:
		host.focused_view = true
		host.calls.clear()
		driver.consume_events([{"kind":"shortcut","index":index},{"kind":"shortcut","index":0}])
		check(host.calls == ["show"], "shortcut %d wakes once without a second action" % index)
	var normal := ["room","toggle","recenter","back","recenter","recenter","keyboard","keyboard"]
	for index in 8:
		host.calls.clear()
		driver.consume_events([{"kind":"shortcut","index":index}])
		check(host.calls == [normal[index]], "normal shortcut %d unchanged" % index)
	if driver.has_method("consume_focus_wake"):
		var wake := Wake.new()
		driver.native = wake
		wake.requested = true
		host.focused_view = true
		host.calls.clear()
		check(not driver.consume_focus_wake(false) and not wake.enabled, "hidden XR session cannot wake")
		host.browser_keyboard = true
		check(not driver.consume_focus_wake(true) and not wake.enabled, "keyboard retains trigger ownership")
		host.browser_keyboard = false
		check(driver.consume_focus_wake(true) and host.calls == ["show"], "native trigger wakes hidden controls")
		check(not driver.consume_focus_wake(true) and not wake.enabled, "native wake polling disables outside Focus")
	else:
		check(false, "native trigger wake path exists")
	ui.panel.free()
	ui.focus_notice_panel.free()
	driver.free()
	host.free()
	print(JSON.stringify({"focus_checks":checks,"failures":failures}))
	quit(1 if failures else 0)
