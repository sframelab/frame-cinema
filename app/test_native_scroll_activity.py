import json
from pathlib import Path
import tempfile
import unittest
from native_scroll_activity import NativeScrollActivity

class NoBrowserCalls:
    def __getattr__(self, name):raise AssertionError('Native activity must never call browser')

class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.now=10.
        self.channel=NativeScrollActivity(self.root,clock=lambda:self.now,wall_clock=lambda:self.now)
        self.browser=NoBrowserCalls()
    def tearDown(self):self.temp.cleanup()
    def publish(self,sequence=1,created=10.,cancelled=False):
        (self.root/'browser-scroll.json').write_text(json.dumps(dict(producer=1,sequence=sequence,created=created,cancelled=cancelled)))
        self.channel.poll(self.browser,'fixture')
    def test_activity_expires_without_inventing_input(self):
        self.publish();self.assertTrue(self.channel.busy())
        self.now=10.13;self.channel.poll(self.browser,'fixture');self.assertFalse(self.channel.busy())
    def test_cancel_does_not_reactivate_same_packet(self):
        self.publish();self.channel.cancel();self.channel.poll(self.browser,'fixture');self.assertFalse(self.channel.busy())
        self.publish(sequence=2);self.assertTrue(self.channel.busy())
    def test_focus_cancel_clears_activity(self):
        self.publish();self.publish(sequence=2,cancelled=True);self.assertFalse(self.channel.busy())
    def test_expired_and_future_packets_are_ignored(self):
        self.publish(created=9.);self.assertFalse(self.channel.busy())
        self.publish(sequence=2,created=11.);self.assertFalse(self.channel.busy())
    def test_invalid_packet_cannot_keep_activity_alive(self):
        self.publish();(self.root/'browser-scroll.json').write_text('{')
        self.channel.poll(self.browser,'fixture');self.assertFalse(self.channel.busy())

if __name__=='__main__':unittest.main()
