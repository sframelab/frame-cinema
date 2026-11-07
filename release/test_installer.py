import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import install


def fixture(path, version='1.0.0-pre.1', fail_import=False, corrupt=False, extra=None, preflight=b'pass\n'):
    files = {'start.sh': b'#!/bin/sh\nexit 0\n', 'godot': b'#!/bin/sh\n' + (b'exit 1\n' if fail_import else b'exit 0\n'),
             'preflight.py': preflight, 'project.godot': b'config_version=5\n',
             '.godot/extension_list.cfg': b'', 'asset.txt': b'movie room'}
    manifest = {'schema': 1, 'product': 'frame-cinema', 'platform': 'linux-arm64', 'channel': 'review',
                'public_release': False, 'version': version,
                'files': {n: {'sha256': hashlib.sha256(b).hexdigest(), 'size': len(b),
                              'mode': 0o755 if n in ('start.sh', 'godot') else 0o644} for n, b in files.items()}}
    if corrupt:
        files['asset.txt'] = b'wrong room'
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in {**{'app/' + n: b for n, b in files.items()}, 'package.json': json.dumps(manifest).encode(), 'install.py': b'# fixture'}.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        if extra:
            archive.addfile(extra)
    return path


class PackageInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def inspect(self, **kwargs):
        path = fixture(self.base / 'test.tgz', **kwargs)
        with tarfile.open(path) as archive:
            return install.inspect_package(archive, True)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.inspect(extra=tarfile.TarInfo('../outside'))

    def test_symlink_rejected(self):
        member = tarfile.TarInfo('app/link')
        member.type, member.linkname = tarfile.SYMTYPE, '/outside'
        with self.assertRaises(ValueError):
            self.inspect(extra=member)

    def test_duplicate_member_rejected(self):
        with self.assertRaises(ValueError):
            self.inspect(extra=tarfile.TarInfo('app/asset.txt'))

    def test_requires_review_opt_in(self):
        path = fixture(self.base / 'test.tgz')
        with tarfile.open(path) as archive, self.assertRaisesRegex(ValueError, 'allow-review'):
            install.inspect_package(archive, False)

    def test_bad_version_rejected(self):
        with self.assertRaises(ValueError):
            self.inspect(version='../other')


@unittest.skipUnless(os.name == 'posix', 'Installer filesystem/locking tests require Linux')
class LifecycleTests(PackageInputTests):
    def setUp(self):
        super().setUp()
        self.root = self.base / 'install'
        self.archive = fixture(self.base / 'v1.tgz')
        # Uninstall and fresh installs delete sign-ins: never touch the real home.
        self.home = self.base / 'home'
        self.home.mkdir()
        for patcher in (patch.object(Path, 'home', return_value=self.home),
                        patch.dict(os.environ, {'XDG_DATA_HOME': str(self.home / '.local/share')})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def install(self):
        return install.install(self.root, self.archive, True)

    def sign_in(self):
        """Fixture sign-ins in the exact places Frame Cinema keeps them."""
        for folder in install.user_data_folders():
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'Cookies').write_bytes(b'private-fixture')
        return install.user_data_folders()

    def test_signins_survive_updates_but_not_uninstall_or_fresh_install(self):
        leftovers = self.sign_in()
        self.install()
        self.assertFalse(any(f.exists() for f in leftovers), 'a fresh install must not inherit sign-ins')
        self.sign_in()
        install.install(self.root, fixture(self.base / 'v2.tgz', '1.0.0-pre.2'), True)
        self.assertTrue(all((f / 'Cookies').exists() for f in leftovers), 'an update keeps sign-ins')
        result = install.uninstall(self.root)
        self.assertEqual('removed', result['saved_data'])
        self.assertFalse(any(f.exists() for f in leftovers), 'uninstall signs out of every service')

    def test_uninstall_leaves_other_chrome_profiles(self):
        self.install()
        personal = self.home / '.var/app/com.google.Chrome/config/google-chrome'
        personal.mkdir(parents=True)
        (personal / 'Cookies').write_bytes(b'personal')
        install.uninstall(self.root)
        self.assertEqual(b'personal', (personal / 'Cookies').read_bytes())

    def test_fresh_update_rollback_uninstall_retains_saved_data(self):
        saved = self.base / 'saved-signins'
        saved.write_bytes(b'private-fixture')
        self.assertEqual('1.0.0-pre.1', self.install()['current'])
        v2 = fixture(self.base / 'v2.tgz', '1.0.0-pre.2')
        self.assertEqual({'current': '1.0.0-pre.2', 'previous': '1.0.0-pre.1'}, install.install(self.root, v2, True))
        self.assertEqual(0, install.run(self.root, []))
        self.assertEqual('1.0.0-pre.1', install.rollback(self.root)['current'])
        self.assertEqual(0, install.run(self.root, []))
        install.uninstall(self.root)
        self.assertFalse((self.root / 'versions').exists())
        self.assertFalse((self.root / 'launch').exists())
        self.assertEqual(b'private-fixture', saved.read_bytes())
        self.assertEqual('1.0.0-pre.1', self.install()['current'])

    def test_failed_import_keeps_current_and_previous(self):
        before = self.install()
        package = fixture(self.base / 'bad.tgz', '1.0.0-pre.2', fail_import=True)
        with self.assertRaises(Exception):
            install.install(self.root, package, True)
        self.assertEqual(before, install.state(self.root))

        self.assertEqual(['1.0.0-pre.1'], [p.name for p in (self.root / 'versions').iterdir()])

    def test_running_the_same_installer_again_repairs(self):
        before = self.install()
        (self.root / 'launch').unlink()
        result = self.install()
        self.assertTrue(result['repaired'])
        self.assertEqual(before['current'], result['current'])
        self.assertTrue((self.root / 'launch').is_file(), 'the launcher is rewritten')
        self.assertEqual(before, install.state(self.root))
        self.assertEqual(0, install.run(self.root, []))

    def test_repair_refuses_a_damaged_installation(self):
        self.install()
        (self.root / 'versions/1.0.0-pre.1/asset.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'damaged'):
            self.install()

    def test_older_installed_version_is_still_refused(self):
        self.install()
        install.install(self.root, fixture(self.base / 'v2.tgz', '1.0.0-pre.2'), True)
        before = install.state(self.root)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.install()
        self.assertEqual(before, install.state(self.root))

    def test_main_reports_a_missing_steam_entry(self):
        argv = ['install.py', 'install', str(self.archive), '--root', str(self.root), '--allow-review']
        user = patch.object(install.os, 'getuid', return_value=1000)  # main() refuses root
        user.start()
        self.addCleanup(user.stop)
        with patch.object(install.sys, 'argv', argv), patch.object(install, 'register_desktop'), \
                patch.object(install, 'register_steam', side_effect=ValueError('Steam did not close.')), \
                patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(3, install.main())
        self.assertEqual('1.0.0-pre.1', install.state(self.root)['current'])
        with patch.object(install.sys, 'argv', argv), patch.object(install, 'register_desktop'), \
                patch.object(install, 'register_steam', return_value={'steam_appid': 1}), patch('sys.stdout'):
            self.assertEqual(0, install.main(), 'a second run repairs the entry')

    def test_corrupt_payload_never_activates(self):
        before = self.install()
        bad = fixture(self.base / 'bad.tgz', '1.0.0-pre.2', corrupt=True)
        with self.assertRaises(ValueError):
            install.install(self.root, bad, True)
        self.assertEqual(before, install.state(self.root))

    def test_activation_failure_preserves_current(self):
        before = self.install()
        v2 = fixture(self.base / 'v2.tgz', '1.0.0-pre.2')
        original = install.atomic
        def fail(path, text, mode=0o600):
            if path.name == 'state.json':
                raise OSError('fixture disk failure')
            original(path, text, mode)
        with patch.object(install, 'atomic', side_effect=fail), self.assertRaises(OSError):
            install.install(self.root, v2, True)
        self.assertEqual(before, install.state(self.root))
        self.assertFalse((self.root / 'versions/1.0.0-pre.2').exists())
        self.assertEqual('1.0.0-pre.2', install.install(self.root, v2, True)['current'])

    def test_update_and_uninstall_refuse_active_lock(self):
        self.install()
        v2 = fixture(self.base / 'v2.tgz', '1.0.0-pre.2')
        with install.locked(self.root):
            with self.assertRaisesRegex(ValueError, 'running'):
                install.install(self.root, v2, True)
            with self.assertRaisesRegex(ValueError, 'running'):
                install.uninstall(self.root)

    def test_corrupted_rollback_is_refused(self):
        self.install()
        v2 = fixture(self.base / 'v2.tgz', '1.0.0-pre.2')
        before = install.install(self.root, v2, True)
        (self.root / 'versions/1.0.0-pre.1/asset.txt').write_text('changed')
        with self.assertRaises(ValueError):
            install.rollback(self.root)
        self.assertEqual(before, install.state(self.root))

    def test_unrecognized_directory_is_untouched(self):
        self.root.mkdir()
        (self.root / 'keep').write_text('personal file')
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(['keep'], [p.name for p in self.root.iterdir()])

    def test_symlinked_versions_is_untouched(self):
        self.install()
        install.uninstall(self.root)
        outside = self.base / 'other'
        outside.mkdir()
        (outside / 'keep').write_text('personal file')
        (self.root / 'versions').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            install.uninstall(self.root)
        self.assertTrue((outside / 'keep').exists())

    def test_prerequisites_use_real_user_installation_environment(self):
        self.archive = fixture(self.base / 'env.tgz', preflight=b'import os\nassert os.environ["XDG_DATA_HOME"] == os.environ["FIXTURE_DATA_HOME"]\n')
        data = str(self.base / 'user-flatpak-installation')
        with patch.dict(os.environ, {'XDG_DATA_HOME': data, 'FIXTURE_DATA_HOME': data}):
            self.install()


if __name__ == '__main__':
    unittest.main()
