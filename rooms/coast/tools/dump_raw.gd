extends SceneTree
# Dump Godot Image resources to raw RGBA float32 (+ a preview PNG).
func _initialize() -> void:
	var list := OS.get_environment("DUMP_LIST").split(";")
	for entry in list:
		var parts := entry.split("|")
		var image: Image = load(parts[0]).duplicate()
		var fmt := image.get_format()
		if image.is_compressed():
			image.decompress()
		image.clear_mipmaps()
		var w := image.get_width()
		var h := image.get_height()
		image.convert(Image.FORMAT_RGBAF)
		var f := FileAccess.open(parts[1] + ".raw", FileAccess.WRITE)
		f.store_buffer(image.get_data())
		f.close()
		var preview := image.duplicate()
		preview.convert(Image.FORMAT_RGBA8)
		preview.resize(1024, 1024)
		preview.save_png(parts[1] + ".png")
		print("DUMP ", parts[0], " fmt ", fmt, " ", w, "x", h)
	quit()
