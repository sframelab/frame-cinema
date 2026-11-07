"""Offline Chrome launch and public-package regression checks (no real browser)."""
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import build_public


APP = Path(__file__).resolve().parent.parent
LATEST = APP / 'app'


def load_browser(path):
    spec = importlib.util.spec_from_file_location('chrome_launch_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChromeLaunchTests(unittest.TestCase):
    def test_user_system_and_mixed_architecture_installations_can_launch(self):
        # Model Flatpak's documented user-first lookup, applying the actual
        # launch arguments. A forced user scope reproduces the reported bug.
        cases = [({('user', 'aarch64')}, 'user'),
                 ({('system', 'aarch64')}, 'system'),
                 ({('user', 'aarch64'), ('system', 'aarch64')}, 'user'),
                 ({('user', 'x86_64'), ('system', 'aarch64')}, 'system')]
        for source in (LATEST / 'browser_pipe.py',):
            module = load_browser(source)
            for installed, expected_scope in cases:
                with self.subTest(source=source, installed=installed):
                    browser = module.BrowserPipe.__new__(module.BrowserPipe)
                    browser.incoming = Path('fixture session/to-browser')
                    browser.outgoing = Path('fixture session/from-browser')
                    selected = []

                    def launch(args, **kwargs):
                        arch = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--arch=')), None)
                        self.assertEqual('aarch64', arch)
                        scopes = ['user', 'system']
                        if '--user' in args:
                            scopes = ['user']
                        elif '--system' in args:
                            scopes = ['system']
                        matches = [scope for scope in scopes if (scope, arch) in installed]
                        if not matches:
                            raise OSError('Chrome not installed in the requested scope')
                        selected.append(matches[0])
                        self.assertIn('com.google.Chrome', args)
                        self.assertIn('--remote-debugging-pipe', args)
                        self.assertFalse(any(arg.startswith('--remote-debugging-port') for arg in args))
                        self.assertEqual(['--user-data-dir=fixture profile', 'about:blank'], args[-2:])
                        self.assertIn(str(browser.incoming), args)
                        self.assertIn(str(browser.outgoing), args)
                        return object()

                    with patch.object(module.os, 'mkfifo', create=True), \
                         patch.object(module.os, 'O_NONBLOCK', 0x800, create=True), \
                         patch.object(module.os, 'open', side_effect=[10, 11]), \
                         patch.object(module.subprocess, 'Popen', side_effect=launch):
                        browser._start(['--user-data-dir=fixture profile', 'about:blank'])
                    self.assertEqual([expected_scope], selected)

    def test_public_package_contains_updated_preflight_and_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            fixtures = {
                'cinema.gd': b'{"version": "0.5.9-test"}',
                'project.godot': b'[application]\n',
                'start.sh': b'#!/bin/sh\nexec python3 supervisor.py "$@"\n',
                '.godot/extension_list.cfg': b'',
                'godot': b'fixture', 'panel_host': b'fixture', 'ambient_sampler': b'fixture',
                'browser_pipe.py': (LATEST / 'browser_pipe.py').read_bytes(),
            }
            for name, data in fixtures.items():
                path = project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            result = build_public.build(project, root / 'output')
            with tarfile.open(root / 'output' / result['archive']) as archive:
                for name, source in [('preflight.py', build_public.RELEASE / 'preflight.py'),
                                     ('browser_pipe.py', LATEST / 'browser_pipe.py')]:
                    self.assertEqual(source.read_bytes(), archive.extractfile('app/' + name).read())
                manifest = json.load(archive.extractfile('package.json'))
                self.assertIn('browser_pipe.py', manifest['files'])
                self.assertIn(b'python3 preflight.py || exit $?', archive.extractfile('app/start.sh').read())


if __name__ == '__main__':
    unittest.main()
