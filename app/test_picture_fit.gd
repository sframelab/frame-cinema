extends SceneTree
# picture_fit.gd (0.5.5 harsh detector): acquire a steady crop, ignore brief or
# shallow intrusions and the player's own overlay, hold through telemetry gaps,
# and stop cropping a title that keeps using the bars. Samples arrive at 5 Hz.
var failures := 0
var checks := 0
var fit: RefCounted
var media := {"player_generation": "g1", "fit_identity": "g1:s:7:[1920, 1080]", "fit_eligible": true}
var seq := 0
var t := 100.0

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("FAIL ", label, " target=", fit.target, " top=", fit.top, " reason=", fit.reason)

func feed(count: int, fit_top: float, safe: float, overlay := false, dark := false, known := true) -> void:
	for i in count:
		seq += 1
		t += 0.2
		fit.update(0.2, true, media, {"sequence": seq, "updated": t, "fit_top": fit_top, "fit_safe_top": safe, "fit_known": known and not dark, "fit_dark": dark}, true, overlay)

func _initialize() -> void:
	fit = load("res://picture_fit.gd").new()
	feed(4, 0.12, 0.13)
	check(fit.target == 0.0, "under a second of bars does not crop yet")
	feed(4, 0.12, 0.13)
	check(fit.target > 0.11, "a steady bound for over a second crops")
	for i in 50:
		fit.update(0.05, true, media, {}, false)
	check(fit.target > 0.11 and fit.top > 0.11, "2.5 s of stale sampling holds the crop")
	fit.update(0.05, true, {"fit_identity": "::0:[]"}, {}, false)
	check(fit.target > 0.11, "unreadable media status holds the crop")
	feed(1, 0.02, 0.03)
	check(fit.target > 0.11, "one sample with content in the bars no longer restores them")
	feed(5, 0.02, 0.03)
	check(fit.target > 0.11, "a second of intrusion (a caption flash, a button) keeps the crop")
	feed(2, 0.12, 0.13)
	feed(30, 0.02, 0.03, true)
	check(fit.target == 0.0 and fit.top == 0.0 and fit.reason.ends_with("controls in use"), "using the controllers shows the whole picture, so the player's controls are visible")
	feed(1, 0.12, 0.13)
	check(fit.target > 0.11 and fit.releases == 0, "the learned crop returns at once when the controllers go idle")
	feed(30, 0.115, 0.115)
	check(fit.target > 0.11, "content within the guard margin of the crop keeps it")
	feed(30, 0.0, 0.20, false, true)
	check(fit.target > 0.11, "dark scenes hold the crop")
	feed(9, 0.02, 0.03)
	check(fit.target == 0.0 and fit.top == 0.0 and fit.releases == 1, "content in the bars for 1.5 s restores the picture")
	feed(10, 0.12, 0.13)
	check(fit.target == 0.0, "after a release, clean bars must hold for three seconds")
	feed(10, 0.12, 0.13)
	check(fit.target > 0.11, "the crop returns after three clean seconds")
	feed(9, 0.02, 0.03)
	check(fit.target == 0.0 and fit.releases == 2, "a second sustained intrusion restores the picture")
	feed(40, 0.12, 0.13)
	check(fit.target == 0.0 and fit.reason.ends_with("uses the bars"), "a title that keeps using the bars stays whole instead of flapping")
	for i in 220:
		fit.update(0.05, true, media, {}, false)
	feed(1, 0.12, 0.13)
	check(fit.releases == 2 and fit.target == 0.0, "a telemetry gap does not forget that the title uses the bars")
	var other := media.duplicate()
	other["player_generation"] = "g2"
	other["fit_identity"] = "g2:s:7:[1920, 1080]"
	media = other
	feed(8, 0.12, 0.13)
	check(fit.target > 0.11 and fit.releases == 0, "a new title starts fresh and can crop again")
	for i in 220:
		fit.update(0.05, true, media, {}, false)
	check(fit.target == 0.0 and fit.top == 0.0, "more than ten seconds without telemetry restores the picture")
	feed(8, 0.12, 0.13)
	media = media.duplicate()
	media["player_generation"] = "g3"
	media["fit_identity"] = "g3:s:7:[1920, 1080]"
	feed(1, 0.12, 0.13)
	check(fit.target == 0.0 and fit.top == 0.0, "a new title restores the picture immediately")
	print(JSON.stringify({"picture_fit_checks": checks, "failures": failures}))
	quit(1 if failures else 0)
