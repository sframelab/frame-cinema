extends SceneTree
var failed := false
func check(ok: bool, title: String) -> void:
	print(("PASS " if ok else "FAIL ") + title)
	failed = failed or not ok
func _initialize() -> void:
	var control := preload("res://stereo/stereo_control.gd").new()
	var media := {"updated": 100.0, "current": 20.0, "source_session": "source", "scene_session": "scene", "player_generation": "one", "fit_eligible": true, "seeking": false, "playback_rate": 1.0}
	control.update(media, "scene", true, 1, 0.0, 100.0)
	check(control.allowed, "current full-screen video allowed in Focus")
	var revision: int = control.revision
	media.updated = 100.4
	media.current = 20.4
	control.update(media, "scene", true, 1, 0.0, 100.4)
	check(control.revision == revision, "ordinary playback retains depth history")
	media.updated = 100.8
	media.current = 60.0
	control.update(media, "scene", true, 1, 0.0, 100.8)
	check(control.revision > revision, "seek invalidates depth history")
	control.update(media, "scene", false, 1, 0.0, 100.8)
	check(not control.allowed, "B leaving Focus returns to 2D")
	control.update(media, "scene", true, 0, 0.0, 100.8)
	check(not control.allowed, "Off returns to 2D")
	control.update(media, "scene", true, 1, 0.0, 102.0)
	check(not control.allowed, "stale media returns to 2D")
	control.update(media, "foreign", true, 1, 0.0, 100.8)
	check(not control.allowed, "another scene's media is rejected")
	media.seeking = true
	control.update(media, "scene", true, 1, 0.0, 100.8)
	check(not control.allowed, "seeking suspends conversion")
	quit(1 if failed else 0)
