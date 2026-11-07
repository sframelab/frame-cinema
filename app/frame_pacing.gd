extends RefCounted

# Presentation-only timing; standby's retained GPU query is not a fresh sample.
var samples: Array[Vector3] = []
var previous_usec := 0
var last_usec := 0
# 0.5.1: rare "fake head movement" jitter hunt. A frame interval beyond 1.5x
# the refresh interval is a dropped frame (SteamVR reprojects the old one);
# reference-space changes and recenters are logged beside them, with times.
const HITCH_FACTOR := 1.5
var refresh_hz := 90.0
var hitches := 0
var events: Array[Dictionary] = []
var log_path := ""

func note(kind: String, detail: Dictionary = {}) -> void:
	var event := {"t": snappedf(Time.get_unix_time_from_system(), 0.001), "kind": kind}
	event.merge(detail)
	events.append(event)
	if events.size() > 40:
		events.pop_front()
	if not log_path.is_empty():
		var file := FileAccess.open(log_path, FileAccess.READ_WRITE) if FileAccess.file_exists(log_path) else FileAccess.open(log_path, FileAccess.WRITE)
		if file:
			if file.get_length() > 256 * 1024:
				file.close()
				file = FileAccess.open(log_path, FileAccess.WRITE)
			file.seek_end()
			file.store_line(JSON.stringify(event))
			file.close()

func record(presenting: bool, now_usec: int, gpu_ms: float, cpu_ms: float) -> void:
	if not presenting:
		samples.clear()
		previous_usec = 0
		last_usec = 0
		return
	if previous_usec > 0:
		var interval := float(now_usec - previous_usec) / 1000.0
		samples.append(Vector3(interval, gpu_ms, cpu_ms))
		if samples.size() > 180:
			samples.pop_front()
		if interval > HITCH_FACTOR * 1000.0 / maxf(refresh_hz, 30.0):
			hitches += 1
			note("dropped_frame", {"interval_ms": snappedf(interval, 0.1), "gpu_ms": snappedf(gpu_ms, 0.1), "cpu_ms": snappedf(cpu_ms, 0.01)})
	previous_usec = now_usec
	last_usec = now_usec

func metrics() -> Dictionary:
	if samples.is_empty():
		return {"presenting": false, "samples": 0, "hitches": hitches, "recent_events": events.slice(-8)}
	var intervals: Array[float] = []
	var gpu: Array[float] = []
	var total := 0.0
	for sample in samples:
		intervals.append(sample.x)
		gpu.append(sample.y)
		total += sample.x
	intervals.sort()
	gpu.sort()
	var p95 := mini(int(ceil(samples.size() * 0.95)) - 1, samples.size() - 1)
	return {"presenting": true, "samples": samples.size(), "last_usec": last_usec,
		"interval_ms_median": intervals[samples.size() / 2], "interval_ms_p95": intervals[p95],
		"gpu_ms_median": gpu[samples.size() / 2], "gpu_ms_p95": gpu[p95],
		"process_fps": samples.size() * 1000.0 / maxf(total, 0.001),
		"hitches": hitches, "recent_events": events.slice(-8)}
