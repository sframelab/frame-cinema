extends RefCounted

# Observe only fresh media samples. A stopped clock is not a network diagnosis.
const GAP_MS := 3000
const WAIT_MS := 5000
const STALL_MS := 20000
var last_sample_at := -1
var last_updated := -1.0
var last_progress_at := -1
var last_position := 0.0
var generation := ""
var message := ""
var needs_attention := false

func reset() -> void:
	last_sample_at = -1
	last_updated = -1.0
	last_progress_at = -1
	generation = ""
	message = ""
	needs_attention = false

func _number(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value))

func observe(state: Dictionary, now: int) -> String:
	if state.get("available") != true or state.get("page_ready") != true or state.get("video") != true or state.get("title_player") != true:
		reset()
		return ""
	var token: Variant = state.get("player_generation")
	var stamp: Variant = state.get("updated")
	if not token is String or token.is_empty() or token.length() > 96 or not _number(stamp):
		reset()
		return ""
	if token != generation or (last_sample_at >= 0 and (now < last_sample_at or now - last_sample_at > GAP_MS or float(stamp) < last_updated or float(stamp) - last_updated > 3.0)):
		reset()
	# Redrawing a panel or polling the same record is not fresh playback evidence.
	if float(stamp) == last_updated:
		return message
	generation = token
	last_sample_at = now
	last_updated = float(stamp)
	if _number(state.get("error_code")) and int(state.error_code) in [1, 2, 3, 4]:
		last_progress_at = -1
		message = "Playback error · More → Reload"
		needs_attention = true
		return message
	if state.get("paused") != false or state.get("ended") != false or state.get("current_valid") != true or not _number(state.get("current")) or not _number(state.get("playback_rate")) or float(state.playback_rate) == 0.0:
		last_progress_at = -1
		message = ""
		needs_attention = false
		return ""
	var position := float(state.current)
	# Seeks and Disney's MSE timeline rebases both count as a new observation.
	if last_progress_at < 0 or absf(position - last_position) > 0.025:
		last_position = position
		last_progress_at = now
	var waiting := now - last_progress_at
	message = ""
	needs_attention = waiting >= STALL_MS
	if waiting >= STALL_MS:
		message = "Playback not advancing · More → Reload"
	elif waiting >= WAIT_MS:
		message = "Seeking…" if state.get("seeking") == true else "Waiting for video…"
	return message
