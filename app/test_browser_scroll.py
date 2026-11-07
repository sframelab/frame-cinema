import json
from pathlib import Path
import tempfile
import unittest
from browser_scroll import ScrollChannel


class Clock:
    def __init__(self):
        self.now = 10.0
    def monotonic(self):
        return self.now
    def wall(self):
        return self.now+1700000000
    def advance(self, seconds):
        self.now += seconds


class Browser:
    def __init__(self, clock):
        self.clock = clock
        self.events = []
        self.calls = []
        self.fail = False
        self.delay = 0.0
        self.layout_delay = 0.0
        self.replies = {}
        self.sequence = 0
    def request(self, method, params=None, **kwargs):
        self.calls.append(method)
        if method == 'Page.getLayoutMetrics':
            self.clock.advance(self.layout_delay)
            return {'cssLayoutViewport': {'clientWidth': 1600, 'clientHeight': 900}}
        if self.fail:
            raise TimeoutError('ambiguous delivery')
        self.events.append((self.clock.now, params, kwargs.get('session')))
        self.clock.advance(self.delay)
        return {}

    def begin_request(self, method, params=None, **kwargs):
        self.calls.append(method)
        if self.fail:
            raise TimeoutError('ambiguous delivery')
        self.sequence += 1
        self.events.append((self.clock.now, params, kwargs.get('session')))
        self.replies[self.sequence] = (self.clock.now+self.delay, self.clock.now+kwargs['timeout'])
        return self.sequence

    def poll_response(self, request_id):
        ready, deadline = self.replies[request_id]
        if self.clock.now >= deadline and ready > deadline:
            self.abandon(request_id)
            raise TimeoutError('ambiguous delivery')
        if self.clock.now < ready:
            return None
        self.abandon(request_id)
        return {}

    def abandon(self, request_id):
        self.replies.pop(request_id, None)


class ScrollTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.channel = ScrollChannel(Path(self.temp.name), clock=self.clock.monotonic,
                                     wall_clock=self.clock.wall)
        self.browser = Browser(self.clock)

    def poll(self, session='owned-session'):
        self.channel.poll(self.browser, session)

    def packet(self, sequence, total, **extra):
        value = dict(producer=25, sequence=sequence, created=self.clock.wall(),
                     x=.25, y=.5, total_x=0, total_y=total)
        value.update(extra)
        self.channel.path.write_text(json.dumps(value))
        self.poll()

    def tick(self, seconds=ScrollChannel.FRAME):
        self.clock.advance(seconds)
        self.poll()

    def settle(self):
        for _ in range(100):
            if not any(self.channel.pending) and not self.channel.inflight:
                return
            self.tick()
        self.fail('gesture did not settle')

    def total(self, axis='deltaY'):
        return sum(event[1][axis] for event in self.browser.events)

    def test_small_delta_preserved_with_css_coordinates(self):
        self.packet(1, 1.25)
        self.assertGreater(len(self.browser.events), 0)
        self.assertLess(self.total(), 1.25)
        self.settle()
        self.assertAlmostEqual(self.total(), 1.25)
        self.assertTrue(all((e['x'], e['y']) == (400, 450) for _, e, _ in self.browser.events))

    def test_discrete_pulse_spreads_over_frames_and_stops(self):
        start = self.clock.now
        self.packet(1, 120)
        self.settle()
        values = [e['deltaY'] for _, e, _ in self.browser.events]
        self.assertGreaterEqual(len(values), 5)
        self.assertTrue(all(0 < value <= ScrollChannel.MAX_STEP for value in values))
        self.assertAlmostEqual(sum(values), 120)
        self.assertLessEqual(self.clock.now-start, .09)
        count = len(values)
        self.tick(.05)
        self.assertEqual(len(self.browser.events), count)

    def test_coalesced_sequence_preserves_total(self):
        self.packet(1, 2)
        self.tick()
        self.packet(5, 9.5)
        self.settle()
        self.assertAlmostEqual(self.total(), 9.5)

    def test_duplicates_do_not_change_gesture(self):
        self.packet(1, 4)
        self.packet(1, 4)
        self.settle()
        self.assertAlmostEqual(self.total(), 4)

    def test_reversal_is_prompt_and_preserves_signed_distance(self):
        self.packet(1, 120)
        before = len(self.browser.events)
        self.clock.advance(ScrollChannel.FRAME)
        self.packet(2, -40)
        self.assertLess(self.browser.events[before][1]['deltaY'], 0)
        self.settle()
        self.assertAlmostEqual(self.total(), -40)

    def test_small_reversal_nets_residual_without_distance_loss(self):
        self.packet(1, 120)
        self.clock.advance(ScrollChannel.FRAME)
        self.packet(2, 110)
        self.settle()
        self.assertAlmostEqual(self.total(), 110)

    def test_expired_packet_consumed_not_replayed(self):
        self.packet(1, 100, created=self.clock.wall()-2)
        self.packet(2, 103)
        self.settle()
        self.assertAlmostEqual(self.total(), 3)

    def test_stall_discards_old_tail_and_accumulated_packet(self):
        self.packet(1, 120)
        before = self.total()
        self.clock.advance(.3)
        self.packet(3, 300)
        self.assertEqual(self.total(), before)
        self.tick()
        self.packet(4, 302)
        self.settle()
        self.assertAlmostEqual(self.total()-before, 2)

    def test_no_catchup_dispatch_loop_after_short_stall(self):
        self.packet(1, 300)
        count = len(self.browser.events)
        self.tick(.06)
        self.assertEqual(len(self.browser.events), count+1)
        self.assertLessEqual(self.browser.events[-1][1]['deltaY'], ScrollChannel.MAX_STEP)
        self.poll()
        self.assertEqual(len(self.browser.events), count+1)

    def test_new_producer_cancels_prior_tail(self):
        self.packet(1, 120)
        before = self.total()
        self.packet(1, -2, producer=26)
        self.settle()
        self.assertAlmostEqual(self.total()-before, -2)

    def test_session_change_cancels_tail(self):
        self.packet(1, 120)
        before = self.total()
        self.poll('replacement-session')
        self.assertFalse(any(self.channel.pending))
        self.assertEqual(self.total(), before)

    def test_failure_never_retries_ambiguous_dispatch(self):
        self.packet(1, 120)
        self.browser.fail = True
        self.tick()
        self.browser.fail = False
        before = self.total()
        self.tick()
        self.assertEqual(self.total(), before)
        self.packet(2, 122)
        self.settle()
        self.assertAlmostEqual(self.total()-before, 2)

    def test_invalid_packet_cancels_and_nonfinite_is_rejected(self):
        self.packet(1, 1, x=5)
        self.packet(2, float('nan'))
        self.assertFalse(self.browser.events)
        self.assertFalse(any(self.channel.pending))

    def test_extreme_input_and_each_frame_are_bounded(self):
        self.packet(1, 999999)
        self.settle()
        self.assertAlmostEqual(self.total(), ScrollChannel.MAX_PENDING)
        self.assertTrue(all(abs(e['deltaY']) <= ScrollChannel.MAX_STEP for _, e, _ in self.browser.events))

    def test_two_axes_and_nested_hit_test_coordinates(self):
        self.packet(1, 30, total_x=-7.5, x=.8, y=.25)
        self.settle()
        self.assertAlmostEqual(self.total('deltaX'), -7.5)
        self.assertAlmostEqual(self.total(), 30)
        self.assertTrue(all((e['x'], e['y']) == (1280, 225) for _, e, _ in self.browser.events))
        self.assertEqual(set(self.browser.calls), {'Page.getLayoutMetrics', 'Input.dispatchMouseEvent'})
        self.assertTrue(all(e['type'] == 'mouseWheel' for _, e, _ in self.browser.events))

    def test_cadence_wait_and_slow_replies_do_not_burst(self):
        self.browser.delay = .025
        self.packet(1, 120)
        self.assertGreater(self.channel.wait_time(), 0)
        count = len(self.browser.events)
        self.poll()
        self.assertEqual(len(self.browser.events), count)
        self.settle()
        times = [t for t, _, _ in self.browser.events]
        self.assertTrue(all(b-a >= ScrollChannel.FRAME-1e-8 for a, b in zip(times, times[1:])))
        self.assertLess(times[1]-times[0], .025+ScrollChannel.FRAME)
        self.assertAlmostEqual(self.total(), 120)

    def test_fast_ack_only_waits_remaining_interval(self):
        self.browser.delay = .004
        self.packet(1, 120)
        self.clock.advance(.004)
        self.poll()
        self.assertAlmostEqual(self.channel.wait_time(), ScrollChannel.FRAME-.004)
        count = len(self.browser.events)
        self.poll()
        self.assertEqual(len(self.browser.events), count)

    def test_easing_uses_elapsed_time_when_browser_is_slow(self):
        import math
        self.browser.delay = .025
        self.packet(1, 50)
        remaining = 50-self.total()
        self.clock.advance(.025)
        self.poll()
        self.assertAlmostEqual(self.browser.events[-1][1]['deltaY'],
                               remaining*(1-math.exp(-.025/self.channel.TAU)))

    def test_blocked_browser_bounds_outstanding_events(self):
        self.browser.delay = .09
        self.packet(1, 300)
        for _ in range(6):
            self.tick()
        self.assertEqual(len(self.browser.events), 1)
        self.assertEqual(len(self.channel.inflight), 1)
        self.assertGreater(self.channel.wait_time(), 0)
        self.settle()
        self.assertAlmostEqual(self.total(), 300)

    def test_cancel_does_not_bypass_outstanding_bound(self):
        self.browser.delay = .09
        self.packet(1, 300)
        self.tick()
        self.channel.cancel()
        self.packet(2, 600)
        self.tick()
        self.assertEqual(len(self.browser.events), 1)

    def test_timeout_drops_tail_without_retry(self):
        self.browser.delay = .2
        self.packet(1, 300)
        for _ in range(12):
            self.tick()
        self.assertEqual(len(self.browser.events), 1)
        self.assertFalse(self.channel.inflight)
        self.assertFalse(any(self.channel.pending))
        self.assertFalse(self.browser.replies)

    def test_cancel_stops_without_tail(self):
        self.packet(1, 120)
        before = self.total()
        self.channel.cancel()
        self.tick()
        self.assertEqual(self.total(), before)

    def test_slow_layout_reply_does_not_dispatch_old_input(self):
        self.browser.layout_delay = .2
        self.packet(1, 120)
        self.assertFalse(self.browser.events)
        self.assertFalse(any(self.channel.pending))

    def test_focus_leave_packet_discards_tail_and_starts_fresh(self):
        self.packet(1, 120, epoch=0)
        before = self.total()
        self.packet(2, 0, epoch=1, cancelled=True)
        self.tick()
        self.assertEqual(self.total(), before)
        self.packet(3, 2, epoch=1)
        self.settle()
        self.assertAlmostEqual(self.total()-before, 2)

    def test_coalesced_cancel_and_next_gesture_preserve_only_new_distance(self):
        self.packet(1, 120, epoch=0)
        before = self.total()
        self.packet(3, 2, epoch=1)
        self.settle()
        self.assertAlmostEqual(self.total()-before, 2)

    def test_pipeline_opens_only_after_first_target_acknowledgement(self):
        self.browser.delay = .03
        self.packet(1, 80)
        self.tick()
        self.tick()
        self.assertEqual(len(self.browser.events), 1)
        self.tick()
        self.assertTrue(self.channel.target_ready)
        self.tick()
        self.assertEqual(len(self.channel.inflight), 2)
        self.assertEqual(len(self.browser.events), 3)
        self.poll()
        self.assertEqual(len(self.channel.inflight), 2)
        self.settle()
        self.assertAlmostEqual(self.total(), 80)

    def test_cancelled_pipeline_must_drain_before_new_target(self):
        self.browser.delay = .03
        self.packet(1, 80)
        self.tick(.03)
        self.tick()
        self.assertEqual(len(self.channel.inflight), 2)
        self.channel.cancel()
        count = len(self.browser.events)
        self.packet(2, 110, x=.8)
        self.assertEqual(len(self.browser.events), count)
        self.tick(.02) # Only the older of the two acknowledgements is ready.
        self.assertEqual(len(self.browser.events), count)
        self.assertFalse(self.channel.target_ready)
        self.tick(.02)
        self.assertEqual(len(self.browser.events), count+1)
        self.assertEqual(self.browser.events[-1][1]['x'], 1280)
        self.assertFalse(self.channel.target_ready)

    def test_target_latches_for_gesture_then_changes_after_idle(self):
        self.packet(1, 10, x=.25)
        self.tick()
        self.packet(2, 20, x=.8)
        self.settle()
        self.assertTrue(all(e['x'] == 400 for _, e, _ in self.browser.events))
        count = len(self.browser.events)
        # Avoid simulating a consumer stall: poll throughout the idle gap.
        for _ in range(10):
            self.tick()
        self.packet(3, 30, x=.8)
        self.settle()
        self.assertTrue(all(e['x'] == 1280 for _, e, _ in self.browser.events[count:]))

    def test_timeout_in_pipeline_abandons_all_submitted_slots(self):
        self.packet(1, 80)
        self.browser.delay = .2
        self.tick()
        self.tick()
        self.assertEqual(len(self.channel.inflight), 2)
        count = len(self.browser.events)
        for _ in range(12):
            self.tick()
        self.assertFalse(self.channel.inflight)
        self.assertFalse(self.browser.replies)
        self.assertFalse(any(self.channel.pending))
        self.assertEqual(len(self.browser.events), count)

    def test_pipeline_total_submitted_distance_keeps_single_event_bound(self):
        self.browser.delay = .03
        self.packet(1, 360, total_x=-360)
        for _ in range(120):
            self.tick(.002)
            self.assertLessEqual(len(self.channel.inflight), 2)
            for axis in (0, 1):
                self.assertLessEqual(sum(abs(v[axis]) for v in self.channel.submitted.values()), 48+1e-9)
            if self.channel.inflight and any(self.channel.pending):
                self.assertGreater(self.channel.wait_time(), 0)
        self.settle()
        self.assertAlmostEqual(self.total(), 360)
        self.assertAlmostEqual(self.total('deltaX'), -360)

    def test_tiny_fractional_input_does_not_leave_busy_tail(self):
        self.packet(1, 1e-12)
        self.settle()
        self.assertFalse(any(self.channel.pending))
        self.assertFalse(self.channel.inflight)


if __name__ == '__main__':
    unittest.main()
