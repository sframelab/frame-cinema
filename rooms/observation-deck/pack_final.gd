extends SceneTree
# Compressed maps. args: file w h kind out. kind: glow (raw RGBF to RGBH, mips, BC6H, as pack_earth.gd does for galaxy.exr) or dust (raw RG8, mips, BC5).
func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	var kind: String = a[3]
	var image: Image
	var err := 0
	if kind == "glow":
		image = Image.create_from_data(int(a[1]), int(a[2]), false, Image.FORMAT_RGBF, FileAccess.get_file_as_bytes(a[0]))
		image.convert(Image.FORMAT_RGBH)
		image.generate_mipmaps()
		err = image.compress(Image.COMPRESS_BPTC, Image.COMPRESS_SOURCE_GENERIC)
	else:
		image = Image.create_from_data(int(a[1]), int(a[2]), false, Image.FORMAT_RG8, FileAccess.get_file_as_bytes(a[0]))
		image.generate_mipmaps()
		err = image.compress(Image.COMPRESS_S3TC, Image.COMPRESS_SOURCE_GENERIC)
	var serr := ResourceSaver.save(image, a[4])
	print("PACK_FINAL ", a[4], " compress=", err, " save=", serr, " format=", image.get_format(), " mips=", image.has_mipmaps(), " bytes=", image.get_data().size())
	quit()
