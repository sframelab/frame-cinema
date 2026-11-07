"""Steam library registration in install.py: binary VDF round trip, add/update/remove.

Runs anywhere (no Steam needed): HOME points at a temporary Steam layout and the
Steam process controls are stubbed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install  # noqa: E402

# A devkit shortcut in the exact layout found on Frame (root key "Shortcuts").
EXISTING = {'Shortcuts': {'0': {
    'appid': 3607142701, 'AppName': 'Devkit Game: FrameCinema', 'Exe': '"/home/steamos/devkit-game/FrameCinema/start.sh"',
    'StartDir': '/home/steamos/devkit-game/FrameCinema', 'icon': '', 'ShortcutPath': '', 'LaunchOptions': '', 'IsHidden': 0,
    'AllowDesktopConfig': 1, 'AllowOverlay': 1, 'OpenVR': 0, 'Devkit': 1, 'DevkitGameID': 'FrameCinema',
    'DevkitOverrideAppID': 0, 'LastPlayTime': 1791681238, 'FlatpakAppID': '', 'sortas': '', 'tags': {}}}}


class SteamShortcutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = self.home / '.local/share/Steam/userdata/12345678/config'
        self.config.mkdir(parents=True)
        (self.config / 'shortcuts.vdf').write_bytes(install.vdf_dump(EXISTING))
        self.root = self.home / '.local/share/frame-cinema/app'
        self.root.mkdir(parents=True)
        self.art = self.home / 'art'
        self.art.mkdir()
        for name in ('capsule.png', 'header.png', 'hero.png', 'logo.png', 'icon.png'):
            (self.art / name).write_bytes(b'\x89PNG' + name.encode())
        patches = [mock.patch.object(Path, 'home', return_value=self.home),
                   mock.patch.object(install, 'steam_pids', return_value=set()),
                   mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(self.home / 'data')})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.temp.cleanup()

    def shortcuts(self):
        data = install.vdf_load((self.config / 'shortcuts.vdf').read_bytes())
        return data['Shortcuts']

    def test_round_trip_is_byte_exact(self):
        blob = install.vdf_dump(EXISTING)
        self.assertEqual(install.vdf_load(blob), EXISTING)
        self.assertEqual(install.vdf_dump(install.vdf_load(blob)), blob)
        self.assertTrue(blob.endswith(b'\x08\x08'))

    def test_register_keeps_other_shortcuts_and_writes_art(self):
        result = install.register_steam(self.root, self.art)
        items = self.shortcuts()
        self.assertEqual(len(items), 2)
        self.assertEqual(items['0']['AppName'], 'Devkit Game: FrameCinema')
        entry = items['1']
        self.assertEqual(entry['AppName'], 'Frame Cinema')
        self.assertEqual(entry['Exe'], '"' + str(self.root / 'launch') + '"')
        self.assertEqual(entry['appid'], result['steam_appid'])
        self.assertTrue(entry['appid'] & 0x80000000)
        self.assertEqual(entry['appid'], install.steam_shortcut_id(entry['Exe']))
        grid = self.config / 'grid'
        appid = entry['appid']
        for name in (f'{appid}p.png', f'{appid}.png', f'{appid}_hero.png', f'{appid}_logo.png'):
            self.assertTrue((grid / name).is_file(), name)
        self.assertEqual((grid / f'{appid}p.png').read_bytes(), b'\x89PNGcapsule.png')
        self.assertTrue(Path(entry['icon']).is_file())
        self.assertTrue((self.config / 'shortcuts.vdf.frame-cinema-backup').is_file())

    def test_reinstall_replaces_rather_than_duplicates(self):
        install.register_steam(self.root, self.art)
        install.register_steam(self.root, self.art)
        names = [item['AppName'] for item in self.shortcuts().values()]
        self.assertEqual(names.count('Frame Cinema'), 1)

    def test_unregister_removes_only_ours(self):
        appid = install.register_steam(self.root, self.art)['steam_appid']
        self.assertTrue(install.unregister_steam(self.root))
        items = self.shortcuts()
        self.assertEqual([item['AppName'] for item in items.values()], ['Devkit Game: FrameCinema'])
        self.assertFalse(any((self.config / 'grid').glob(f'{appid}*')))
        self.assertFalse((self.root / 'steam.json').exists())
        self.assertFalse(install.unregister_steam(self.root))

    def test_first_backup_is_never_overwritten(self):
        original = (self.config / 'shortcuts.vdf').read_bytes()
        install.register_steam(self.root, self.art)
        after_first = (self.config / 'shortcuts.vdf').read_bytes()
        install.register_steam(self.root, self.art)
        self.assertEqual((self.config / 'shortcuts.vdf.frame-cinema-backup').read_bytes(), original)
        self.assertEqual((self.config / 'shortcuts.vdf.frame-cinema-previous').read_bytes(), after_first)
        self.assertEqual(sorted(p.name for p in self.config.glob('.shortcuts-*')), [])

    def test_unregister_keeps_a_copy_first(self):
        install.register_steam(self.root, self.art)
        registered = (self.config / 'shortcuts.vdf').read_bytes()
        install.unregister_steam(self.root)
        self.assertEqual((self.config / 'shortcuts.vdf.frame-cinema-previous').read_bytes(), registered)

    def test_a_failed_write_leaves_the_file_alone(self):
        original = (self.config / 'shortcuts.vdf').read_bytes()
        with mock.patch.object(install.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                install.register_steam(self.root, self.art)
        self.assertEqual((self.config / 'shortcuts.vdf').read_bytes(), original)
        self.assertEqual(sorted(p.name for p in self.config.glob('.shortcuts-*')), [])

    def test_creates_file_when_none_exists(self):
        (self.config / 'shortcuts.vdf').unlink()
        install.register_steam(self.root, self.art)
        data = install.vdf_load((self.config / 'shortcuts.vdf').read_bytes())
        self.assertEqual([item['AppName'] for item in data['shortcuts'].values()], ['Frame Cinema'])

    def test_no_steam_user_is_an_error(self):
        for user in (self.home / '.local/share/Steam/userdata').iterdir():
            os.rename(user, self.home / 'moved')
        with self.assertRaises(ValueError):
            install.register_steam(self.root, self.art)


class DesktopAndDataTest(SteamShortcutTest):
    def test_desktop_entry_round_trip(self):
        install.register_desktop(self.root, self.art / 'icon.png')
        entry = install.desktop_entry()
        text = entry.read_text()
        self.assertIn('Name=Uninstall Frame Cinema', text)
        self.assertIn(f'--root "{self.root}"', text)
        self.assertTrue((self.root / 'icon.png').is_file())
        install.unregister_desktop(self.home / 'elsewhere')
        self.assertTrue(entry.exists(), 'another root must not remove our entry')
        install.unregister_desktop(self.root)
        self.assertFalse(entry.exists())

    def test_user_data_folders_are_only_ours(self):
        names = [p.name for p in install.user_data_folders()]
        self.assertEqual(names, ['FrameCinema', 'frame-cinema', 'frame-cinema-hbomax', 'frame-cinema-disneyplus', 'frame-cinema-primevideo', 'frame-cinema-plex', 'frame-cinema-control'])
        for folder in install.user_data_folders():
            self.assertTrue(str(folder).startswith(str(self.home)))


if __name__ == '__main__':
    unittest.main()
