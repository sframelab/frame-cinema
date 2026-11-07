"""First run on a fresh headset: folders that do not exist yet must not stop a service.

- Chrome's ~/.var/app/com.google.Chrome appears only after Chrome first runs.
- The scene's logs folder may be missing, or live under another XDG_DATA_HOME.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

if sys.platform == 'linux':
    import browser_pipe
    import supervisor


@unittest.skipUnless(sys.platform == 'linux', 'FIFOs and process groups need Linux')
class FirstRunFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        patcher = patch.object(Path, 'home', return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_browser_pipe_starts_when_chrome_was_never_opened(self):
        self.assertFalse((self.home / '.var').exists())
        chrome = Mock()
        chrome.poll.return_value = 0  # already gone: close() has nothing to stop
        with patch.object(browser_pipe.subprocess, 'Popen', return_value=chrome) as start:
            pipe = browser_pipe.BrowserPipe(['--app=https://www.netflix.com/browse'])
        start.assert_called_once()
        root = self.home / '.var/app/com.google.Chrome/config/frame-cinema-control'
        self.assertTrue(pipe.directory.is_dir())
        self.assertEqual(pipe.directory.parent, root)
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        pipe.close()
        self.assertFalse(pipe.directory.exists())

    def test_session_folder_is_removed_even_if_closing_chrome_fails(self):
        chrome = Mock()
        chrome.poll.return_value = None
        chrome.wait.side_effect = KeyboardInterrupt  # a second stop signal during cleanup
        with patch.object(browser_pipe.subprocess, 'Popen', return_value=chrome):
            pipe = browser_pipe.BrowserPipe([])
        with patch.object(pipe, 'request', side_effect=TimeoutError), self.assertRaises(KeyboardInterrupt):
            pipe.close()
        self.assertFalse(pipe.directory.exists())
        self.assertIsNone(pipe.reader)

    def test_service_opens_without_a_logs_folder(self):
        data = self.home / 'elsewhere'
        with patch.dict(os.environ, {'FRAME_CINEMA_PREVIEW_GODOT_DATA': str(data)}), \
                patch('supervisor.ProcessGroup') as spawn:
            session = supervisor.Session(runtime=self.home / 'run')
            session.select('local', service_id='netflix')
        spawn.assert_called_once()
        self.assertEqual(session.reason, 'Opening Netflix')
        logs = data / 'FrameCinema/logs'
        self.assertTrue(logs.is_dir())
        self.assertEqual(len(list(logs.glob('panel-*.log'))), 1)

    def test_service_opens_when_the_log_cannot_be_written(self):
        blocked = self.home / 'blocked'
        blocked.write_text('a file where the data folder should be')
        with patch.dict(os.environ, {'FRAME_CINEMA_PREVIEW_GODOT_DATA': str(blocked)}), \
                patch('supervisor.ProcessGroup') as spawn:
            session = supervisor.Session(runtime=self.home / 'run')
            session.select('local', service_id='netflix')
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.kwargs['stdout'], supervisor.subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
