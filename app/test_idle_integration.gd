extends SceneTree
class Page extends RefCounted:
	var page := "player"
class Cinema extends "res://cinema.gd":
	func _ready() -> void: set_process(false)
	func _apply_room_light() -> void: pass
	func _browser_command(_command: int) -> void: pass
	func _hover_dock(_hit: Variant) -> void: pass
	func _render_ui(page: String) -> void: ui.page = page
var failures := 0
var checks := 0
func check(value: bool,label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("FAIL ",label)
func _initialize() -> void: run.call_deferred()
func run() -> void:
	var scene := Cinema.new()
	root.add_child(scene)
	scene.ui = Page.new()
	scene.dock = MeshInstance3D.new()
	scene.add_child(scene.dock)
	scene.library_open = false
	scene.panel_fresh = true
	scene.panel_aligned = true
	scene.media_state = {"available":true,"title_player":true,"video":true,"paused":false,"ended":false,"updated":Time.get_unix_time_from_system()}
	var activity := {"available":true,"hands":[]}
	scene._apply_viewing_idle(activity,0)
	scene._apply_viewing_idle(activity,.1)
	scene._apply_viewing_idle(activity,10.2)
	check(scene.focused_view and scene.viewing_idle.hidden and scene.automatic_focus_entries==1,"real Focus path entered and controllers hidden")
	await process_frame
	check(scene.ui.page=="focus","same integrated Focus page")
	check(scene._pointer_kind(null)==7 and scene._pointer_kind(Vector2(1,1))==7,"idle hides the native beam")
	scene._show_controls()
	await process_frame
	check(not scene.focused_view and not scene.viewing_idle.hidden and scene.ui.page=="player","existing wake path restores player")
	check(scene._pointer_kind(null)==0 and scene._pointer_kind(Vector2(1,1))==6,"wake restores the native beam")
	scene.ui.page="room"
	scene._apply_viewing_idle(activity,100)
	check(not scene.focused_view,"room settings do not auto-close")
	scene.ui.page="player"
	scene.browser_keyboard=true
	scene._apply_viewing_idle(activity,120)
	check(not scene.viewing_idle.hidden and not scene.focused_view,"typing keeps controller and menu")
	scene.browser_keyboard=false
	scene.media_state.paused=true
	scene._apply_viewing_idle(activity,140)
	check(not scene.focused_view,"pause does not force Focus")
	var manager := Node3D.new()
	var model := MeshInstance3D.new()
	manager.add_child(model)
	var fallback := MeshInstance3D.new()
	scene.add_child(manager)
	scene.add_child(fallback)
	load("res://controller_foreground.gd").sync_models(manager,{"/user/hand/right":fallback},{"right":true},{},false)
	check(model.layers==0 and not fallback.visible,"idle culls geometry and fallback, not tracking parent")
	scene.free()
	print(JSON.stringify({"idle_integration_checks":checks,"failures":failures}))
	quit(1 if failures else 0)
