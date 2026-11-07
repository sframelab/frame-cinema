extends RefCounted

var check: Callable
var tracker: RefCounted
var clock := 1000
var sample := {}

func tick(extra: Dictionary = {}, elapsed_ms: int = 1000) -> String:
	clock += elapsed_ms
	sample.merge(extra, true)
	sample.updated = clock / 1000.0
	return tracker.observe(sample, clock)

func start() -> void:
	tracker = load("res://playback_health.gd").new()
	clock = 1000
	sample = {"available": true, "page_ready": true, "video": true, "title_player": true,
		"player_generation": "document:1", "current_valid": true, "current": 40.0,
		"paused": false, "ended": false, "seeking": false, "playback_rate": 1.0, "error_code": 0}
	tick()

func stall() -> String:
	var result := ""
	for index in range(21):
		result = tick()
	return result

func run(assertion: Callable) -> void:
	check = assertion
	start()
	var clean := true
	for index in range(25):
		clean = tick({"current": 41.0 + index}).is_empty() and clean
	check.call(clean, "advancing video never receives a stall warning")
	start()
	for index in range(4): tick()
	check.call(tracker.message.is_empty(), "short startup or buffering keeps a grace period")
	check.call(tick() == "Waiting for video…", "stationary playback receives neutral waiting feedback after five seconds")
	for index in range(15): tick()
	check.call(tracker.message.begins_with("Playback not advancing"), "fresh static samples eventually offer manual Reload")
	check.call(tick({"current": 41.0}).is_empty(), "advancing playback clears the warning immediately")
	stall()
	check.call(tick({"current": 2.0}).is_empty(), "backward seeks and MSE timeline rebases reset progress")
	stall()
	check.call(tick({"player_generation": "document:2"}).is_empty(), "replacement player at the same time starts a new grace period")
	start()
	for index in range(3): tracker.observe(sample, clock + 1000)
	check.call(tracker.last_sample_at == clock and tracker.message.is_empty(), "duplicate records and UI redraws do not become fresh progress samples")
	check.call(tick({}, 4000).is_empty(), "a gap in local observation discards pre-gap progress history")
	stall()
	sample.updated += 20.0
	check.call(tracker.observe(sample, clock + 1000).is_empty(), "large telemetry clock jumps cannot carry a warning across resume")
	start()
	stall()
	sample.updated -= 10.0
	check.call(tracker.observe(sample, clock + 1000).is_empty(), "backward telemetry clock changes start a new observation")
	start()
	stall()
	check.call(tick({}, -1000).is_empty(), "backward local clocks discard stale progress history")
	for case in [{"paused": true}, {"ended": true}, {"title_player": false}, {"video": false}, {"available": false}, {"page_ready": false}, {"current_valid": false}, {"current": NAN}, {"current": INF}, {"playback_rate": 0.0}, {"player_generation": ""}]:
		start()
		stall()
		check.call(tick(case).is_empty(), "non-playing or unknown state clears progress warning: " + str(case.keys()[0]) + "=" + str(case.values()[0]))
	start()
	tick({"seeking": true})
	for index in range(5): tick()
	check.call(tracker.message == "Seeking…", "a stationary seek is described without diagnosing a failure")
	check.call(stall().begins_with("Playback not advancing"), "a permanently seeking player cannot hide a stall forever")
	check.call(tick({"seeking": false, "current": 100.0}).is_empty(), "a completed seek clears its warning")
	start()
	check.call(tick({"paused": true, "error_code": 3}).begins_with("Playback error"), "a reported media error remains visible even if the player paused itself")
	check.call(tick({"error_code": 0}).is_empty(), "cleared media error restores ordinary paused status")
	start()
	stall()
	tracker.reset()
	check.call(tick().is_empty(), "explicit navigation or source reset drops old progress history")
