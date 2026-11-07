extends RefCounted

const TIMEOUT := 10.0
const MOVE_METRES := 0.015
const TURN_RADIANS := 0.05235988 # Three degrees, above resting tracking noise.
# A resting controller can drop out of tracking and come back with its pose a
# little off. Only a real relocation while untracked counts as activity.
const REACQUIRE_METRES := 0.10
const REACQUIRE_RADIANS := 0.34906585 # Twenty degrees.
# Motion must persist across two polls (~66 ms): a hand movement does, a single
# tracking hiccup does not.
const CONFIRM_SAMPLES := 2
var last_activity := -1.0
var eligible_since := -1.0
var hidden := false
var hands := {}
var lost := {}
var moving := {}
var seen := {}

func touch(now: float) -> void:
	last_activity = now
	hidden = false

func _moved(prior: Transform3D, pose: Transform3D, metres: float, radians: float) -> bool:
	return prior.origin.distance_to(pose.origin) >= metres or prior.basis.get_rotation_quaternion().angle_to(pose.basis.get_rotation_quaternion()) >= radians

func observe(samples: Array, now: float) -> void:
	var present := {}
	for sample in samples:
		var id: int = sample.id
		var pose: Transform3D = sample.pose
		present[id] = true
		if sample.get("pressed", false): touch(now)
		if not hands.has(id):
			# A controller switched on (or first seen) is activity.
			hands[id] = pose
			moving[id] = 0
			touch(now)
			continue
		if lost.has(id):
			lost.erase(id)
			moving[id] = 0
			if _moved(hands[id], pose, REACQUIRE_METRES, REACQUIRE_RADIANS): touch(now)
			hands[id] = pose
			continue
		if _moved(hands[id], pose, MOVE_METRES, TURN_RADIANS):
			# Consecutive polls only (the poll runs every ~33 ms).
			moving[id] = int(moving.get(id, 0)) + 1 if now - float(seen.get(id, -1.0)) <= 0.1 else 1
			seen[id] = now
			if moving[id] >= CONFIRM_SAMPLES:
				hands[id] = pose
				moving[id] = 0
				touch(now)
		else:
			moving[id] = 0
	# Keep the last pose of a controller that dropped out of tracking.
	for id in hands.keys():
		if not present.has(id): lost[id] = true

func advance(now: float, eligible: bool, suspended: bool) -> bool:
	if last_activity < 0.0 or suspended:
		touch(now)
		eligible_since = -1.0
		return false
	if not eligible: eligible_since = -1.0
	elif eligible_since < 0.0: eligible_since = now
	hidden = now - last_activity >= TIMEOUT
	return hidden and eligible_since >= 0.0 and now - eligible_since >= TIMEOUT
