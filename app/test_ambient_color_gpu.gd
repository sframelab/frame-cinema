extends SceneTree

class Host extends Node3D:
	var screen_width := 4.2
	var ambient_mode := 3
	var environment_index := 5
	var picture_top := 0.0
	func _screen_center() -> Vector3: return Vector3(0, 2.1, -4.5)

var view: SubViewport
var glow: Node3D
var results := []
var failures := 0

func _initialize() -> void: call_deferred("run")

func measure(color: Color) -> Vector3:
	glow.colors.fill(color)
	glow.target = glow.colors.duplicate()
	glow.advance(0.0, 3, 0.75)
	for frame in 4: await process_frame
	await RenderingServer.frame_post_draw
	var picture := view.get_texture().get_image()
	var total := Vector3.ZERO
	for y in picture.get_height():
		for x in picture.get_width():
			# HDR SubViewport readback retains linear light without SDR's
			# quantization of the faint tail into black.
			var pixel := picture.get_pixel(x,y)
			total += Vector3(pixel.r, pixel.g, pixel.b)
	return total

func run() -> void:
	view = SubViewport.new()
	view.size = Vector2i(512,384)
	view.own_world_3d = true
	view.use_hdr_2d = true
	view.msaa_3d = Viewport.MSAA_4X
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	var world := WorldEnvironment.new()
	world.environment = Environment.new()
	world.environment.background_mode = Environment.BG_COLOR
	world.environment.background_color = Color.BLACK
	world.environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	view.add_child(world)
	var host := Host.new()
	view.add_child(host)
	glow = load("res://cinema_ambient.gd").new()
	glow.host = host
	host.add_child(glow)
	var eye := Camera3D.new()
	eye.projection = Camera3D.PROJECTION_ORTHOGONAL
	eye.size = 11.0
	eye.position = Vector3(0,2.1,0)
	view.add_child(eye)
	eye.current = true
	var black: Vector3 = await measure(Color.BLACK)
	if black.length() > 0.001: failures += 1
	for color in [Color(.16,.04,.016), Color(.016,.04,.16), Color(.16,.16,.16)]:
		var bright: Vector3 = await measure(color)
		var dim: Vector3 = await measure(color * 0.1)
		var ratios := dim / bright
		var ok := bright.length() > 1
		for channel in 3:
			ok = ok and absf(ratios[channel]-.1) < .012
		if not ok: failures += 1
		results.append({"input": [color.r,color.g,color.b], "bright": [bright.x,bright.y,bright.z], "dim": [dim.x,dim.y,dim.z], "ratios": [ratios.x,ratios.y,ratios.z], "passed": ok})
		print(("PASS " if ok else "FAIL ") + "tenfold dimming preserves RGB energy: " + str(ratios))
	var report := {"renderer": RenderingServer.get_video_adapter_name(), "black_energy": black.length(), "failures": failures, "cases": results}
	var output := OS.get_environment("FRAME_CINEMA_TEST_OUT")
	var file := FileAccess.open(output.path_join("color-gpu.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "  "))
	print("AMBIENT_COLOR_GPU failures=%d" % failures)
	quit(failures)
