"""Provider command safety/routing; no service connection or account data."""
import unittest
from unittest.mock import Mock, patch

from media_control import operation, supported_url


class ServiceOrigins(unittest.TestCase):
    def test_prime_and_hosted_plex_navigation(self):
        for url in ('https://www.primevideo.com/', 'https://www.primevideo.com/detail/example',
                    'https://www.amazon.com/gp/video/detail/example',
                    'https://www.amazon.co.uk/gp/video/storefront',
                    'https://www.amazon.de/hz/video/detail/example',
                    'https://www.amazon.co.jp/gp/video/detail/example',
                    'https://app.plex.tv/desktop', 'https://app.plex.tv/desktop/#!/server/example/details'):
            with self.subTest(url=url):
                self.assertTrue(supported_url(url))

    def test_shopping_auth_untrusted_and_non_hosted_plex_are_not_media_pages(self):
        for url in ('https://www.amazon.com/dp/example', 'https://www.amazon.com/ap/signin',
                    'https://www.amazon.com/gp/videoish/example', 'https://www.primevideo.com.evil.test/',
                    'https://amazon.com.evil.test/gp/video/detail/example',
                    'https://app.plex.tv.evil.test/desktop/', 'https://evil.app.plex.tv/desktop/',
                    'https://plex.tv/auth', 'https://app.plex.tv/account',
                    'http://app.plex.tv/desktop/', 'https://192.168.1.2:32400/web/',
                    'https://user:password@app.plex.tv/desktop/', 'https://[bad'):
            with self.subTest(url=url):
                self.assertFalse(supported_url(url))


class NetflixCommands(unittest.TestCase):
    def test_shortcuts_are_paired_and_never_mutate_media_time(self):
        for name, code in [('toggle_play', 'Space'), ('back_10', 'ArrowLeft'), ('forward_10', 'ArrowRight')]:
            browser = Mock()
            with patch('media_control.evaluate', return_value=dict(shortcut=True)) as evaluate:
                self.assertTrue(operation(browser, 'owned', name)['ok'])
            self.assertEqual(evaluate.call_count, 1)
            calls = browser.request.call_args_list
            self.assertEqual([call.args[0] for call in calls], ['Input.dispatchKeyEvent'] * 2)
            self.assertEqual([call.args[1]['type'] for call in calls], ['keyDown', 'keyUp'])
            self.assertEqual([call.args[1]['code'] for call in calls], [code] * 2)

    def test_no_shortcuts_into_editor_or_browsing_preview(self):
        for reason in ['editor_focused', 'no_video']:
            browser = Mock()
            with patch('media_control.evaluate', return_value=dict(ok=False, reason=reason)):
                for name in ['toggle_play', 'back_10', 'forward_10']:
                    self.assertFalse(operation(browser, 'owned', name)['ok'])
            browser.request.assert_not_called()

    def test_other_services_use_their_video_without_injecting_keys(self):
        browser = Mock()
        with patch('media_control.evaluate', return_value=dict(ok=True)) as evaluate:
            self.assertTrue(operation(browser, 'owned', 'forward_10')['ok'])
        self.assertEqual(evaluate.call_count, 1)
        self.assertIn('v.currentTime=', evaluate.call_args.args[2])
        browser.request.assert_not_called()

    def test_fullscreen_exit_does_not_inject_escape(self):
        browser = Mock()
        with patch('media_control.evaluate', return_value=dict(ok=True)) as evaluate:
            self.assertTrue(operation(browser, 'owned', 'exit_fullscreen')['ok'])
        self.assertIn('document.exitFullscreen()', evaluate.call_args.args[2])
        browser.request.assert_not_called()

    def test_disney_wakes_player_before_paired_shortcut(self):
        browser = Mock()
        with patch('media_control.evaluate', return_value=dict(shortcut=True, wake_pointer=dict(x=960,y=540))):
            self.assertTrue(operation(browser, 'owned', 'forward_10')['ok'])
        calls = browser.request.call_args_list
        self.assertEqual(calls[0].args, ('Input.dispatchMouseEvent', dict(type='mouseMoved', x=960, y=540), 'owned'))
        self.assertEqual([call.args[1]['type'] for call in calls[1:]], ['keyDown', 'keyUp'])
        self.assertTrue(all(call.args[1]['code'] == 'ArrowRight' for call in calls[1:]))


if __name__ == '__main__':
    unittest.main()
