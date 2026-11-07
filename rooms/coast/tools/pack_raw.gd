extends SceneTree
# Raw RGBA float32 -> BC6H (BPTC_RGBFU) Godot Image resource with mipmaps.
func _initialize() -> void:
	for entry in OS.get_environment("PACK_LIST").split(";"):
		var parts := entry.split("|")
		var size := int(parts[2])
		var data := FileAccess.get_file_as_bytes(parts[0])
		var image := Image.create_from_data(size, size, false, Image.FORMAT_RGBAF, data)
		image.convert(Image.FORMAT_RGBH)
		image.generate_mipmaps()
		var err := image.compress(Image.COMPRESS_BPTC)
		print("PACK ", parts[1], " fmt ", image.get_format(), " compress ", err, " save ", ResourceSaver.save(image, parts[1]))
	quit()
