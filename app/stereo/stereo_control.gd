extends RefCounted

var revision := 1
var identity := ""
var last_stamp := 0.0
var last_current := 0.0
var allowed := false
var source := "-"

func update(media: Dictionary, session: String, focused: bool, mode: int, crop: float, now: float) -> void:
	var stamp := float(media.get("updated", 0.0))
	var current := float(media.get("current", 0.0))
	source = str(media.get("source_session", "-"))
	var next_identity := source + ":" + str(media.get("player_generation", "")) + ":" + str(snappedf(crop, 0.002))
	var fresh := is_finite(stamp) and now >= stamp - 0.01 and now - stamp < 0.85
	var eligible: bool = focused and mode > 0 and fresh and media.get("scene_session") == session and source != "-" and not source.is_empty() and media.get("fit_eligible") == true and media.get("seeking") == false
	if identity != next_identity or eligible != allowed:
		revision += 1
	elif stamp != last_stamp and last_stamp > 0.0 and is_finite(current):
		var expected := maxf(0.0, stamp - last_stamp) * float(media.get("playback_rate", 1.0))
		if current < last_current - 0.5 or current - last_current > expected + 1.0:
			revision += 1
	identity = next_identity
	last_stamp = stamp
	last_current = current
	allowed = eligible

func packet(session: String, mode: int, now: float) -> String:
	return "FCST1 %s %s %.6f %d %d %d" % [session, source, now, mode, int(allowed), revision]
