"""Elapsed-time pixel-wheel easing for the owned browser; no DOM scrolling."""
import json
import math
import time


class ScrollChannel:
    FRAME = 1.0 / 90.0
    TAU = .018
    REVERSE_TAU = .006
    TAIL = .070
    STALL = .100
    MAX_PENDING = 360.0
    MAX_STEP = 48.0
    MAX_INFLIGHT = 2

    def __init__(self, runtime, *, clock=time.monotonic, wall_clock=time.time):
        self.path = runtime / 'browser-scroll.json'
        self.clock, self.wall_clock = clock, wall_clock
        self.producer = None
        self.sequence = 0
        self.epoch = 0
        self.totals = (0.0, 0.0)
        self.metrics = None
        self.metrics_at = 0.0
        self.session = None
        self.pending = [0.0, 0.0]
        self.direction = [0, 0]
        self.fast_until = [0.0, 0.0]
        self.point = (0.0, 0.0)
        self.last_input = 0.0
        self.last_poll = None
        self.next_frame = 0.0
        self.last_dispatch = None
        self.inflight = []
        self.browser = None
        self.first_request = None
        self.target_ready = False
        self.gesture_point = None
        self.submitted = {}

    def cancel(self):
        """Discard an unfinished gesture; never replay it in another page/session."""
        self.pending[:] = (0.0, 0.0)
        self.direction[:] = (0, 0)
        self.fast_until[:] = (0.0, 0.0)
        self.next_frame = 0.0
        self.last_dispatch = None
        self.first_request = None
        self.target_ready = False
        self.gesture_point = None
        # Already submitted input cannot be retracted. Keep its reply slots
        # occupied until acknowledged so repeated focus changes cannot bypass
        # the two-event queue bound. A replacement gesture must drain them.

    def wait_time(self, maximum=.012):
        """Let the bridge wake at the next frame without a catch-up loop."""
        if self.inflight:
            maximum = min(maximum, .002)
        if not any(self.pending):
            return maximum
        if self.inflight and (not self.target_ready or len(self.inflight) >= self.MAX_INFLIGHT):
            return maximum
        if not any(self.pending[a] and self._credit(a) > 1e-9 for a in (0, 1)):
            return maximum
        return max(0.0, min(maximum, self.next_frame-self.clock()))

    def _credit(self, axis):
        # Pipeline small updates without increasing submitted travel beyond
        # the previous single-event bound, including across cancellation.
        return max(0.0, self.MAX_STEP-sum(abs(v[axis]) for v in self.submitted.values()))

    def busy(self):
        return bool(self.inflight) or any(self.pending) or self.clock()-self.last_input < .09

    def _ingest(self, now, discard):
        if not self.path.exists() or self.path.stat().st_size > 1024:
            return
        value = json.loads(self.path.read_text())
        producer, sequence = value['producer'], value['sequence']
        numbers = [float(value[k]) for k in ('created', 'x', 'y', 'total_x', 'total_y')]
        if (type(producer) is not int or producer <= 0 or type(sequence) is not int
                or sequence < 1 or not all(math.isfinite(n) for n in numbers)):
            self.cancel()
            return
        created, x, y, tx, ty = numbers
        if producer != self.producer:
            self.cancel()
            self.producer, self.sequence, self.totals = producer, 0, (0.0, 0.0)
            self.epoch = 0
        if sequence <= self.sequence:
            return
        epoch, cancelled = value.get('epoch', 0), value.get('cancelled', False)
        if type(epoch) is not int or epoch < 0 or type(cancelled) is not bool:
            self.cancel()
            return
        if epoch != self.epoch:
            self.cancel()
            self.epoch, self.totals = epoch, (0.0, 0.0)
        delta = (tx-self.totals[0], ty-self.totals[1])
        self.sequence, self.totals = sequence, (tx, ty)
        # Consume expired/invalid snapshots as baselines so they cannot replay.
        if (cancelled or discard or not 0 <= self.wall_clock()-created < .25
                or not (0 <= x <= 1 and 0 <= y <= 1)):
            self.cancel()
            return
        if not any(delta):
            return
        if not any(self.pending) and now >= self.next_frame:
            self.next_frame = now
            if now-self.last_input > self.TAIL:
                self.last_dispatch = None
                self.first_request = None
                self.target_ready = False
                self.gesture_point = None
        for axis, amount in enumerate(delta):
            if not math.isfinite(amount):
                self.cancel()
                return
            sign = (amount > 0)-(amount < 0)
            if sign and self.direction[axis] and sign != self.direction[axis]:
                # Net signed distance, then settle a reversal quickly; do not
                # throw away the old residual or invent inertial wheel travel.
                self.fast_until[axis] = now + 2*self.FRAME
            if sign:
                self.direction[axis] = sign
            self.pending[axis] = max(-self.MAX_PENDING, min(self.MAX_PENDING,
                                                         self.pending[axis]+amount))
        self.point = (x, y)
        self.last_input = now

    def poll(self, browser, session):
        self.browser = browser
        now = self.clock()
        changed = self.session is not None and self.session != session
        stalled = self.last_poll is not None and now-self.last_poll > self.STALL
        self.last_poll, self.session = now, session
        if changed or stalled:
            self.cancel()
            self.metrics = None
        try:
            self._ingest(now, changed or stalled)
            for request_id in self.inflight[:]:
                if browser.poll_response(request_id) is not None:
                    self.inflight.remove(request_id)
                    self.submitted.pop(request_id, None)
                    if request_id == self.first_request:
                        self.target_ready = True
                        self.first_request = None
            if not any(self.pending) or now+1e-9 < self.next_frame:
                return
            if len(self.inflight) >= self.MAX_INFLIGHT:
                return
            # Establish the new hit-test target before overlapping updates.
            # Old/cancelled replies must drain before the first new event.
            if self.inflight and not self.target_ready:
                return
            if self.metrics is None or now-self.metrics_at > 2:
                metrics = browser.request('Page.getLayoutMetrics', session=session,
                                          timeout=.1)['cssLayoutViewport']
                if not all(math.isfinite(float(metrics[k])) and float(metrics[k]) > 0
                           for k in ('clientWidth', 'clientHeight')):
                    raise ValueError('invalid viewport')
                self.metrics, self.metrics_at = metrics, now
                if self.clock()-now > self.STALL:
                    self.cancel()
                    return
            # Browser wheel acknowledgement already consumes time (often a
            # display interval). Easing must follow elapsed time, not pretend
            # every acknowledgement took exactly 1/90 second.
            dispatch_at = self.clock()
            elapsed = (self.FRAME if self.last_dispatch is None else
                       min(self.STALL, max(0.0, dispatch_at-self.last_dispatch)))
            delta = []
            for axis, remaining in enumerate(self.pending):
                tau = self.REVERSE_TAU if now < self.fast_until[axis] else self.TAU
                amount = remaining*(1-math.exp(-elapsed/tau))
                if now-self.last_input >= self.TAIL or abs(remaining) < .01:
                    amount = remaining
                credit = self._credit(axis)
                delta.append(max(-credit, min(credit, amount)))
            if not any(delta):
                return
            if self.gesture_point is None:
                self.gesture_point = self.point
            request_id = browser.begin_request('Input.dispatchMouseEvent', {
                'type': 'mouseWheel', 'x': self.gesture_point[0]*self.metrics['clientWidth'],
                'y': self.gesture_point[1]*self.metrics['clientHeight'],
                'deltaX': delta[0], 'deltaY': delta[1], 'pointerType': 'mouse'},
                session=session, timeout=.1)
            self.inflight.append(request_id)
            self.submitted[request_id] = tuple(delta)
            if not self.target_ready:
                self.first_request = request_id
            for axis in (0, 1):
                self.pending[axis] -= delta[axis]
                if abs(self.pending[axis]) < 1e-9:
                    self.pending[axis] = 0.0
            # Pace start-to-start: never add a full sleep AFTER Chrome's ack.
            # No historical deadlines and no catch-up loop; at most one bounded
            # event per poll and two outstanding replies, never an unbounded queue.
            self.last_dispatch = dispatch_at
            self.next_frame = dispatch_at+self.FRAME
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError):
            # A timed-out dispatch may have happened. Never retry its old delta.
            self.cancel()
            for request_id in self.inflight:
                browser.abandon(request_id)
            self.inflight.clear()
            self.submitted.clear()
            self.metrics = None
