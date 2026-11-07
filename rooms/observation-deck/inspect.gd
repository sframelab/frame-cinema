extends SceneTree

class Inspector extends Node3D:
	var camera: Camera3D
	var room: Node3D
	var yaw := 0.0
	var pitch := 0.0
	var width := 4.2
	var focused := false
	var screen: MeshInstance3D
	func _unhandled_input(event: InputEvent) -> void:
		if event is InputEventMouseMotion and Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
			yaw -= event.relative.x * 0.003
			pitch = clampf(pitch - event.relative.y * 0.003, -1.48, 1.48)
			camera.rotation = Vector3(pitch, yaw, 0)
		if event is InputEventKey and event.pressed and not event.echo:
			if event.keycode == KEY_ESCAPE:
				get_tree().quit()
			elif event.keycode == KEY_R:
				camera.position = Vector3(0, 1.65, 0)
				yaw = 0.0
				pitch = 0.0
				camera.rotation = Vector3.ZERO
			elif event.keycode == KEY_F:
				focused = not focused
				room.set_light(0.12 if focused else 0.55)
			elif event.keycode in [KEY_1, KEY_2, KEY_3]:
				width = 3.2 if event.keycode == KEY_1 else 4.2 if event.keycode == KEY_2 else 5.4
				room.follow_screen(Vector3(0, 2.1, -4.5), width)
				screen.mesh.size = Vector2(width, width * 0.5625)
	func _process(delta: float) -> void:
		var movement := Vector3.ZERO
		if Input.is_physical_key_pressed(KEY_W): movement.z -= 1
		if Input.is_physical_key_pressed(KEY_S): movement.z += 1
		if Input.is_physical_key_pressed(KEY_A): movement.x -= 1
		if Input.is_physical_key_pressed(KEY_D): movement.x += 1
		if Input.is_physical_key_pressed(KEY_Q): movement.y -= 1
		if Input.is_physical_key_pressed(KEY_E): movement.y += 1
		camera.position += camera.basis * movement * delta * 0.65

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	DisplayServer.window_set_title("Observation Deck — desktop inspection")
	root.msaa_3d = Viewport.MSAA_4X
	var rig := Inspector.new()
	root.add_child(rig)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	rig.add_child(environment)
	rig.room = load("res://starship/starship_room.gd").new()
	rig.add_child(rig.room)
	rig.room.setup("res://starship/", environment.environment)
	rig.camera = Camera3D.new()
	rig.camera.position = Vector3(0, 1.65, 0)
	rig.camera.fov = 78
	rig.camera.near = 0.04
	rig.camera.far = 100
	rig.add_child(rig.camera)
	rig.camera.current = true
	rig.screen = MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(4.2, 4.2 * 0.5625)
	rig.screen.mesh = quad
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(0.008, 0.012, 0.02)
	rig.screen.material_override = material
	rig.screen.position = Vector3(0, 2.1, -4.5)
	rig.room.add_child(rig.screen)
	var title := Label3D.new()
	title.text = "FRAME CINEMA\nObservation Deck"
	title.font_size = 60
	title.pixel_size = 0.004
	title.modulate = Color(0.56, 0.63, 0.73)
	title.outline_size = 0
	title.position = Vector3(0, 2.1, -4.48)
	rig.room.add_child(title)
	var canvas := CanvasLayer.new()
	rig.add_child(canvas)
	var help := Label.new()
	help.text = "Desktop inspection · Right-drag: look · WASD / Q / E: move · R: return to seat · F: Focus · 1 / 2 / 3: screen size · Esc: close"
	help.position = Vector2(20, 18)
	help.add_theme_font_size_override("font_size", 15)
	canvas.add_child(help)
