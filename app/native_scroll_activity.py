"""Defer browser telemetry during native input; never dispatch a second wheel."""
import json
import math
import time


class NativeScrollActivity:
    def __init__(self, runtime, *, clock=time.monotonic, wall_clock=time.time):
        self.path=runtime/'browser-scroll.json'
        self.clock,self.wall_clock=clock,wall_clock
        self.identity=None
        self.until=0.0

    def cancel(self):
        self.until=0.0

    def busy(self):
        return self.clock()<self.until

    def wait_time(self, maximum=.012):
        return maximum

    def poll(self, browser, session):
        # browser/session deliberately unused: native input owns wheel delivery.
        try:
            if self.path.stat().st_size>1024:
                self.cancel();return
            value=json.loads(self.path.read_text())
            producer,sequence=value['producer'],value['sequence']
            created=float(value['created']);cancelled=value.get('cancelled',False)
            if (type(producer) is not int or producer<1 or type(sequence) is not int
                    or sequence<1 or type(cancelled) is not bool or not math.isfinite(created)):
                self.cancel();return
            identity=(producer,sequence)
            if identity==self.identity:return
            self.identity=identity
            age=self.wall_clock()-created
            self.until=self.clock()+max(0.0,.120-age) if not cancelled and 0<=age<.120 else 0.0
        except (OSError,ValueError,TypeError,KeyError):
            self.cancel()
