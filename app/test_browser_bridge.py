import time
import unittest
from unittest.mock import patch
from browser_bridge import developer_hooks, dispatch, keep_page_focused


class DeveloperHookTests(unittest.TestCase):
    def test_page_screenshots_are_off_unless_asked_for(self):
        self.assertFalse(developer_hooks({}))
        self.assertFalse(developer_hooks({'FRAME_CINEMA_DEVELOPER': '0'}))
        self.assertTrue(developer_hooks({'FRAME_CINEMA_DEVELOPER': '1'}))


class FocusTests(unittest.TestCase):
    class Browser:
        def __init__(self, error=None):
            self.calls, self.error = [], error

        def request(self, method, params=None, session=None, timeout=4):
            self.calls.append((method, params, session))
            if self.error:
                raise self.error
            return {}

    def test_page_session_keeps_focus_through_window_focus_churn(self):
        browser = self.Browser()
        self.assertTrue(keep_page_focused(browser, 'page-session'))
        self.assertEqual(browser.calls, [('Emulation.setFocusEmulationEnabled', {'enabled': True}, 'page-session')])

    def test_a_browser_without_focus_emulation_still_runs_the_service(self):
        for error in (RuntimeError('unsupported'), TimeoutError()):
            self.assertFalse(keep_page_focused(self.Browser(error), 'page-session'))


class CommandTests(unittest.TestCase):
    def command(self, **overrides):
        return dict({'id': 12, 'op': 'toggle_play', 'created': time.time()}, **overrides)

    def test_rejects_bad_or_expired_commands_without_page_execution(self):
        with patch('browser_bridge.operation') as operation:
            for command in [[], {}, self.command(op='arbitrary_script'), self.command(created=0),
                            self.command(created='invalid'), self.command(id=True)]:
                self.assertFalse(dispatch(None, None, command)['ok'])
            operation.assert_not_called()

    def test_preserves_request_id_when_page_refuses_command(self):
        with patch('browser_bridge.operation', return_value={'ok': False, 'reason': 'not_seekable'}):
            self.assertEqual(dispatch(None, None, self.command()), {'id': 12, 'ok': False, 'reason': 'not_seekable'})

    def test_errors_are_generic_and_do_not_lose_acknowledgement(self):
        with patch('browser_bridge.operation', side_effect=RuntimeError('page detail must not leak')):
            self.assertEqual(dispatch(None, None, self.command()), {'id': 12, 'ok': False, 'reason': 'unavailable'})

    def test_accepts_only_explicit_success_and_known_reason(self):
        with patch('browser_bridge.operation', return_value={'ok': True, 'reason': 'unexpected page detail'}):
            self.assertEqual(dispatch(None, None, self.command()), {'id': 12, 'ok': True, 'reason': ''})


if __name__ == '__main__':
    unittest.main()
