extends RefCounted

# Visit the small runtime tree each frame: model creation and path changes need
# ownership before the next draw, not at the one-second diagnostics interval.
static func sync_models(manager: Node3D, fallbacks: Dictionary, tracked: Dictionary, foreground: Dictionary, focused: bool) -> Dictionary:
	var present := {}
	var pending := [[manager, ""]] if is_instance_valid(manager) else []
	while not pending.is_empty():
		var item: Array = pending.pop_back()
		var node: Node = item[0]
		var path: String = item[1]
		if node.has_method("get_top_level_path"):
			path = node.get_top_level_path()
			if path in ["/user/hand/left", "/user/hand/right"]:
				present[path] = true
		if node is GeometryInstance3D:
			var side := path.get_file()
			var show_model: bool = focused and tracked.get(side, false) and not foreground.get(side, false)
			# The runtime owns model transforms/animation/visibility. Culling the
			# child geometry avoids its pose updates undoing our ownership.
			node.layers = 2 if show_model else 0
		for child in node.get_children(true): pending.append([child, path])
	for path in fallbacks:
		var side: String = str(path).get_file()
		fallbacks[path].visible = focused and tracked.get(side, false) and not foreground.get(side, false) and not present.has(path)
	return present

# A stale or foreign worker must never suppress the scene's controller models.
static func accepted(value: Dictionary, session: String, scene_pid: int, now: float) -> Dictionary:
	if value.get("session") != session or value.get("scene_pid") != scene_pid:
		return {}
	var stamp: Variant = value.get("updated")
	if not (stamp is int or stamp is float) or not is_finite(float(stamp)):
		return {}
	if now < float(stamp) or now - float(stamp) > 0.2:
		return {}
	for key in ["active", "left", "right"]:
		if not value.get(key) is bool:
			return {}
	if not value.active:
		return {}
	return {"left": value.left, "right": value.right}

static func read(ipc: String, session: String) -> Dictionary:
	var path := ipc.path_join("controller-layer.json")
	if ipc.is_empty() or not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if not file or file.get_length() > 4096:
		return {}
	var parser := JSON.new()
	if parser.parse(file.get_as_text()) != OK or not parser.data is Dictionary:
		return {}
	return accepted(parser.data, session, OS.get_process_id(), Time.get_unix_time_from_system())
