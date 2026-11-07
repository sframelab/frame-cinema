extends RefCounted

# Learn from distinct captured frames, including while the uncropped browser is
# visible. Only Focus presents a crop. An uncertain dark scene may retain an
# established shape within its measured clear rows, but cannot acquire a crop.
#
# 0.4.47: a confirmed crop survives brief telemetry interruptions.
# 0.5.5, a much harsher detector: the sampler marks a bar row unclear when any
# sampled pixel in it is lit, so one sample with Netflix's control overlay, a
# "skip intro" button, a caption or encoder noise used to restore the bars at
# once, and they came straight back. Now:
# - acquiring needs a steady bound for ACQUIRE_SECONDS (RECOVER after a release);
# - only content reaching clearly past the crop (INTRUSION_MARGIN) for
#   INTRUSION_SECONDS in a row restores the picture;
# - 0.5.6: while the controllers are in use the whole picture shows, so the
#   player's own controls in the bars stay visible; the learned crop is kept
#   and returns as soon as the controllers go idle (no re-acquisition);
# - telemetry gaps hold the crop for HOLD_SECONDS;
# - a title that keeps using the bars (captions placed there, changing aspect
#   ratios) stops being cropped after MAX_RELEASES, instead of flapping.
# A new title still restores the whole picture immediately.
const ACQUIRE_SECONDS := 1.0
const ACQUIRE_SAMPLES := 5
const RECOVER_SECONDS := 3.0
const MAX_SAMPLE_GAP := 0.5
const HOLD_SECONDS := 10.0
const CANDIDATE_TOLERANCE := 0.002
const INTRUSION_MARGIN := 0.012
const INTRUSION_SECONDS := 1.5
const MAX_RELEASES := 2
var top := 0.0
var target := 0.0
var pending := 0.0
var stable := 0.0
var identity := ""
var blocked := false
var reason := "Full screen"
var held := 0.0
var intrusion := 0.0
var releases := 0
var _confirmed := 0.0
var _overlay := false
var _samples := 0
var _sequence := 0.0
var _updated := 0.0

func _reset_candidate() -> void:
	pending = 0.0
	stable = 0.0
	_samples = 0

func _clear_history() -> void:
	top = 0.0
	target = 0.0
	_confirmed = 0.0
	held = 0.0
	intrusion = 0.0
	_reset_candidate()

func _number(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value))

# Telemetry is briefly unusable: keep a confirmed crop for HOLD_SECONDS.
func _interrupted(delta: float, enabled: bool, why: String) -> void:
	_reset_candidate()
	held += maxf(delta, 0.0)
	if _confirmed <= 0.0 or held > HOLD_SECONDS:
		_clear_history()
		reason = why
		return
	_present(delta, enabled, "Fit picture · holding")

# overlay: the controllers are in use, so the player may be showing its own
# controls over the bars; show the whole picture, and never count them as
# picture content.
func update(delta: float, enabled: bool, media: Dictionary, sample: Dictionary, fresh: bool, overlay := false) -> void:
	_overlay = overlay
	# An unreadable or stale media status says nothing about the title: it must
	# not count as an identity change.
	if media.is_empty() or str(media.get("player_generation", "")).is_empty():
		_interrupted(delta, enabled, "Full screen · no eligible title")
		return
	var key := str(media.get("fit_identity", media.get("player_generation", "")))
	if key != identity:
		identity = key
		_clear_history()
		_sequence = 0.0
		_updated = 0.0
		blocked = false
		releases = 0
	if not media.get("fit_eligible", false):
		_interrupted(delta, enabled, "Full screen · no eligible title")
		return
	if not fresh:
		_interrupted(delta, enabled, "Full screen · sampling stale or identity changed")
		return
	var eligible := true
	for field in ["sequence", "updated", "fit_top", "fit_safe_top"]:
		eligible = eligible and _number(sample.get(field))
	eligible = eligible and sample.get("fit_known") is bool and sample.get("fit_dark") is bool
	if eligible:
		eligible = float(sample.sequence) > 0 and float(sample.sequence) == floor(float(sample.sequence)) and float(sample.updated) > 0
		eligible = eligible and float(sample.fit_top) >= 0 and float(sample.fit_top) <= 0.20 and float(sample.fit_safe_top) >= 0 and float(sample.fit_safe_top) <= 0.20
		eligible = eligible and float(sample.fit_top) <= float(sample.fit_safe_top)
	if not eligible:
		_interrupted(delta, enabled, "Full screen · invalid sample")
		return
	var sequence := float(sample.sequence)
	var updated := float(sample.updated)
	if sequence < _sequence or updated < _updated:
		_interrupted(delta, enabled, "Full screen · reordered sample")
		return
	if sequence > _sequence:
		held = 0.0
		var elapsed := updated - _updated if _updated > 0 else 0.0
		if elapsed > MAX_SAMPLE_GAP:
			# A gap restarts acquisition and intrusion timing; it does not drop the crop.
			_reset_candidate()
			intrusion = 0.0
			elapsed = 0.0
		_sequence = sequence
		_updated = updated
		var safe := float(sample.fit_safe_top)
		if _confirmed > 0.0:
			# Content must reach clearly past the crop, continuously, with the
			# controllers idle. Dark frames report the full safe band and reset it.
			if overlay or safe >= _confirmed - INTRUSION_MARGIN:
				intrusion = 0.0
			else:
				intrusion += elapsed
				if intrusion >= INTRUSION_SECONDS:
					_clear_history()
					blocked = true
					releases += 1
					reason = "Full screen · picture or captions extend into bars"
		var candidate := float(sample.fit_top)
		var known: bool = sample.fit_known and not sample.fit_dark and candidate > 0.001
		if releases >= MAX_RELEASES:
			# This title keeps using the bars: show it whole until the title changes.
			_reset_candidate()
			_confirmed = 0.0
			blocked = true
			reason = "Full screen · this title uses the bars"
		elif known and _confirmed > 0.0 and candidate < _confirmed - INTRUSION_MARGIN:
			# A clearly smaller bound under a held crop is content in the bars:
			# only the intrusion timing above may act on it.
			_reset_candidate()
		elif known:
			if _samples == 0 or absf(candidate - pending) > CANDIDATE_TOLERANCE:
				pending = candidate
				stable = 0.0
				_samples = 1
			else:
				# Never retain the larger member of a slightly varying measured bound.
				pending = minf(pending, candidate)
				stable += maxf(0.0, elapsed)
				_samples += 1
			if _samples >= ACQUIRE_SAMPLES and stable >= (RECOVER_SECONDS if blocked else ACQUIRE_SECONDS):
				_confirmed = minf(pending, safe)
				blocked = false
		else:
			_reset_candidate()
	_present(delta, enabled, "Fit picture")

func _present(delta: float, enabled: bool, fitted: String) -> void:
	if not enabled or _overlay:
		top = 0.0
		target = 0.0
		if enabled and _confirmed > 0.0:
			reason = "Full screen · controls in use"
		elif not blocked:
			reason = "Full screen"
		return
	target = _confirmed
	if target > 0:
		reason = fitted
	elif not blocked:
		reason = "Full screen"
	# Short, gentle entry; every safety restore above is immediate, not eased.
	top = lerpf(top, target, 1.0 - exp(-clampf(delta, 0.0, 0.1) / 0.12))
	if absf(top - target) < 0.0001:
		top = target
	if target == 0.0 and top < 0.0005:
		top = 0.0

func height_fraction() -> float:
	return 1.0 - 2.0 * top
