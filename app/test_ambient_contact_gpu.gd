extends SceneTree

class Host extends Node3D:
	var screen_width := 5.4
	var ambient_mode := 3
	var environment_index := 3
	var picture_top := 0.0
	func _screen_center() -> Vector3:return Vector3(0,2.1,-4.5)
	func _dark_room() -> bool:return false

var checks := 0
var failures := 0
var view: SubViewport
var host: Host
var glow: Node3D
var camera: Camera3D
var output: String
func _initialize() -> void:call_deferred("run")
func check(ok: bool,label: String) -> void:
	checks+=1
	print(("PASS " if ok else "FAIL ")+label)
	if not ok:failures+=1
func capture(name: String) -> Image:
	for frame in 3:await process_frame
	await RenderingServer.frame_post_draw
	var image := view.get_texture().get_image()
	if not output.is_empty():image.save_png(output.path_join(name+".png"))
	return image
func intensity(image: Image,point: Vector3) -> float:
	var pixel := Vector2i(camera.unproject_position(host.to_global(point)))
	var total := 0.0
	for y in range(pixel.y-1,pixel.y+2):
		for x in range(pixel.x-1,pixel.x+2):total+=image.get_pixel(x,y).srgb_to_linear().g/9.0
	return total
func run() -> void:
	output=OS.get_environment("FRAME_CINEMA_TEST_OUT")
	view=SubViewport.new();view.size=Vector2i(640,640);view.own_world_3d=true;view.msaa_3d=Viewport.MSAA_4X;view.use_debanding=true
	view.render_target_update_mode=SubViewport.UPDATE_ALWAYS
	root.add_child(view)
	var world:=WorldEnvironment.new();world.environment=Environment.new();world.environment.background_mode=Environment.BG_COLOR;world.environment.background_color=Color.BLACK
	view.add_child(world)
	host=Host.new();view.add_child(host)
	var plane:=MeshInstance3D.new();plane.mesh=PlaneMesh.new();plane.mesh.size=Vector2(40,40)
	var ground:=StandardMaterial3D.new();ground.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED;ground.albedo_color=Color.BLACK
	plane.material_override=ground;host.add_child(plane)
	glow=load("res://cinema_ambient.gd").new();glow.host=host;host.add_child(glow)
	var flat:=Image.create(2,2,false,Image.FORMAT_RGF);flat.fill(Color(0,1,0,1))
	glow.contact_cache[3]=ImageTexture.create_from_image(flat);glow.contact_room=-1
	glow.colors.fill(Color(.1,.7,.2));glow.target=glow.colors.duplicate();glow.advance(0,3,.75)
	for light in glow.lights:light.light_energy=0
	camera=Camera3D.new();view.add_child(camera);camera.current=true
	for side in [-1,1]:
		# Frustum offsets deliberately differ between eyes.
		camera.set_frustum(.16,Vector2(side*.009,0),.1,100)
		camera.position=Vector3(side*.032,1.65,0)
		camera.look_at(Vector3(0,2.1,-4.5))
		var pose:=camera.transform
		for material in [glow.material,glow.haze_material]:material.set_shader_parameter("terrain_contact_enabled",false)
		var hard:Image=await capture("eye%d-hard"%side)
		for material in [glow.material,glow.haze_material]:material.set_shader_parameter("terrain_contact_enabled",true)
		var soft:Image=await capture("eye%d-soft"%side)
		var low:=intensity(soft,Vector3(0,.045,-4.56));var raw:=intensity(hard,Vector3(0,.045,-4.56))
		check(raw>.015 and low<raw*.55,"eye %d contact fades continuously above the actual floor (%.5f / %.5f)"%[side,low,raw])
		var high:=intensity(soft,Vector3(0,.32,-4.56));var high_raw:=intensity(hard,Vector3(0,.32,-4.56))
		check(absf(high-high_raw)<.02,"eye %d retains glow away from floor contact"%side)
		host.transform=Transform3D(Basis(Vector3.UP,2.1),Vector3(-3,.3,4))
		camera.transform=host.transform*pose
		glow.advance(0,3,.75)
		for light in glow.lights:light.light_energy=0
		var recentered:Image=await capture("eye%d-recentered"%side)
		var sum:=0.0;var count:=0
		for y in range(360,520,2):
			for x in range(120,520,2):
				sum+=absf(soft.get_pixel(x,y).g-recentered.get_pixel(x,y).g);count+=1
		check(sum/count<.004,"eye %d recenter retains room-relative contact (mean delta %.6f)"%[side,sum/count])
		host.transform=Transform3D.IDENTITY
		camera.transform=pose
	host.environment_index=999
	glow.advance(0,3,.75)
	for light in glow.lights:light.light_energy=0
	var missing:Image=await capture("missing-map-fallback")
	check(intensity(missing,Vector3(0,.045,-4.56))>.15,"missing contact map retains ordinary depth-tested glow")
	glow.colors.fill(Color.BLACK);glow.target=glow.colors.duplicate();glow.advance(0,3,.75)
	var black:Image=await capture("solid-black")
	var black_peak:=0.0
	for y in range(0,640,8):
		for x in range(0,640,8):
			var pixel:=black.get_pixel(x,y)
			black_peak=maxf(black_peak,maxf(pixel.r,maxf(pixel.g,pixel.b)))
	check(not glow.visible and black_peak<.004,"solid black removes cached haze rather than exposing the previous palette")
	glow.colors.fill(Color(.8,.02,.5));glow.target=glow.colors.duplicate();glow.advance(0,3,.75)
	for light in glow.lights:light.light_energy=0
	var resumed:Image=await capture("resumed-magenta")
	var pixel:=Vector2i(camera.unproject_position(Vector3(0,.32,-4.56)))
	var resumed_color:=resumed.get_pixelv(pixel).srgb_to_linear()
	check(resumed_color.r>resumed_color.g*3 and resumed_color.b>resumed_color.g*3,"resuming after black uses the fresh colour field")
	var result:={"checks":checks,"failures":failures,"renderer":RenderingServer.get_video_adapter_name()}
	if not output.is_empty():
		var file:=FileAccess.open(output.path_join("ambient-contact-tests.json"),FileAccess.WRITE);file.store_string(JSON.stringify(result,"  "))
	print("AMBIENT_CONTACT_GPU_OK" if failures==0 else "AMBIENT_CONTACT_GPU_FAILED")
	quit(failures)
