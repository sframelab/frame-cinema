"""Linux pipe regressions: concurrent replies, timeout, cleanup, byte bounds."""
import json
import os
import sys
import time
import unittest
from unittest.mock import Mock
from browser_pipe import BrowserPipe


@unittest.skipUnless(sys.platform == 'linux', 'Linux FIFO/select transport')
class TransportTests(unittest.TestCase):
    def setUp(self):
        self.browser = BrowserPipe.__new__(BrowserPipe)
        self.browser.sequence = 0
        self.browser.buffer = b''
        self.browser.discarding = False
        self.browser.pending = {}
        self.browser.process = Mock()
        self.browser.process.poll.return_value = None
        self.request_reader, self.browser.writer = os.pipe()
        self.browser.reader, self.response_writer = os.pipe()
        for fd in (self.request_reader, self.browser.writer, self.browser.reader, self.response_writer):
            os.set_blocking(fd, False)
            self.addCleanup(os.close, fd)

    def send(self, method='Input.dispatchMouseEvent', **kwargs):
        return self.browser.begin_request(method, timeout=.1, **kwargs)

    def reply(self, request_id, result=None, **extra):
        os.write(self.response_writer, json.dumps(dict(id=request_id,result=result or {},**extra)).encode()+b'\0')

    def test_nonblocking_poll_does_not_wait(self):
        request_id=self.send()
        start=time.monotonic()
        self.assertIsNone(self.browser.poll_response(request_id))
        self.assertLess(time.monotonic()-start,.02)

    def test_out_of_order_reply_survives_other_waiter(self):
        wheel=self.send();other=self.send('Page.getLayoutMetrics')
        self.reply(other, {'viewport':72});self.reply(wheel)
        self.assertEqual(self.browser.poll_response(wheel),{})
        self.assertEqual(self.browser.poll_response(other),{'viewport':72})
        self.assertFalse(self.browser.pending)

    def test_sync_request_preserves_async_response(self):
        wheel=self.send()
        self.reply(wheel);self.reply(wheel+1,{'answer':42})
        self.assertEqual(self.browser.request('Runtime.evaluate'),{'answer':42})
        self.assertEqual(self.browser.poll_response(wheel),{})

    def test_partial_reply_is_assembled(self):
        request_id=self.send()
        os.write(self.response_writer,b'{"id":1,')
        self.assertIsNone(self.browser.poll_response(request_id))
        os.write(self.response_writer,b'"result":{"ok":true}}\0')
        self.assertEqual(self.browser.poll_response(request_id),{'ok':True})

    def test_abandoned_reply_never_satisfies_next_request(self):
        old=self.send();self.browser.abandon(old)
        new=self.send();self.reply(old,{'stale':True})
        self.assertIsNone(self.browser.poll_response(new))
        self.reply(new,{'fresh':True})
        self.assertEqual(self.browser.poll_response(new),{'fresh':True})

    def test_timeout_cleans_up_sync_request(self):
        with self.assertRaises(TimeoutError):
            self.browser.request('Runtime.evaluate',timeout=.005)
        self.assertFalse(self.browser.pending)

    def test_error_is_routed_to_correct_request(self):
        bad=self.send();good=self.send()
        self.reply(bad,error={'message':'rejected'});self.reply(good,{'ok':True})
        self.assertEqual(self.browser.poll_response(good),{'ok':True})
        with self.assertRaises(RuntimeError):self.browser.poll_response(bad)
        self.assertFalse(self.browser.pending)

    def test_response_limit_is_per_request(self):
        small=self.send(max_response_bytes=40);large=self.send(max_response_bytes=1000)
        self.reply(small,{'data':'a'*100});self.reply(large,{'data':'b'*100})
        self.assertEqual(self.browser.poll_response(large),{'data':'b'*100})
        with self.assertRaises(RuntimeError):self.browser.poll_response(small)

    def test_request_backpressure_is_bounded(self):
        for _ in range(4):self.send()
        with self.assertRaises(RuntimeError):self.send()
        self.assertEqual(len(self.browser.pending),4)


if __name__ == '__main__':unittest.main()
