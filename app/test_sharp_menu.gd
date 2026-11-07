extends SceneTree

class MenuHost extends Node3D:
	var ui_viewport: SubViewport
	var mouse_inside := false
	var pointer_down := false

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var host := MenuHost.new()
	root.add_child(host)
	var helper: Node = load("res://native-ui/native_ui.gd").new()
	helper.scene = host
	var checks := 0
	for logical in [Vector2i(1600, 650), Vector2i(1600, 186)]:
		var view := SubViewport.new()
		view.size = logical * 2
		view.size_2d_override = logical
		view.size_2d_override_stretch = true
		view.handle_input_locally = true
		host.add_child(view)
		host.ui_viewport = view
		var hits := [0]
		var buttons: Array[Button] = []
		for uv in [Vector2(0.1, 0.2), Vector2(0.72, 0.2), Vector2(0.1, 0.65), Vector2(0.72, 0.65)]:
			var button := Button.new()
			button.position = Vector2(logical) * uv
			button.size = Vector2(150, 40)
			button.text = "Test"
			button.pressed.connect(func(): hits[0] += 1)
			view.add_child(button)
			buttons.append(button)
		await process_frame
		await process_frame
		for button in buttons:
			var before: int = hits[0]
			helper.consume_events([{"kind":"move", "position":button.get_global_rect().get_center()}, {"kind":"click", "position":button.get_global_rect().get_center()}])
			if hits[0] != before + 1:
				push_error("Native menu click failed at logical dimensions " + str(logical))
				quit(1)
				return
			checks += 1
		helper.leave()
		view.queue_free()
		await process_frame
	helper.free()
	host.queue_free()
	print(JSON.stringify({"native_menu_button_checks": checks, "full_resolution_scale": 2, "failures": 0}))
	quit(0)
