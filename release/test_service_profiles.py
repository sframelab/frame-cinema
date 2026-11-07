"""Fixed service destinations and sign-in cleanup; no real user profiles."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import install


PROJECT = Path(__file__).resolve().parent.parent / 'app'
spec = importlib.util.spec_from_file_location('catalog_fixture', PROJECT / 'service_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class ServiceProfilesTests(unittest.TestCase):
    def test_five_fixed_destinations_have_distinct_contained_profiles(self):
        services = json.loads((PROJECT / 'services.json').read_text())
        self.assertEqual({'netflix', 'hbomax', 'disneyplus', 'primevideo', 'plex'}, set(catalog.SERVICES))
        self.assertEqual(5, len({item['profile'] for item in services}))
        for item in services:
            with self.subTest(service=item['id']):
                self.assertEqual(item, catalog.service(item['id']))
                self.assertEqual('https', urlparse(item['url']).scheme)
                self.assertEqual(item['profile'], Path(item['profile']).name)
                self.assertTrue(item['profile'].startswith('frame-cinema'))
        self.assertEqual('https://www.primevideo.com/', catalog.service('primevideo')['url'])
        self.assertEqual('https://app.plex.tv/desktop/', catalog.service('plex')['url'])

    def test_ipc_cannot_supply_an_arbitrary_url_or_profile(self):
        for value in ('https://example.com', '../../personal', 'http://192.168.1.2:32400/web', '', None, {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                catalog.service(value)

    def test_cleanup_covers_every_service_and_preserves_other_browser_data(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            chrome = home / '.var/app/com.google.Chrome/config'
            with patch.object(Path, 'home', return_value=home), \
                 patch.dict(os.environ, {'XDG_DATA_HOME': str(home / '.local/share')}):
                profiles = [chrome / item['profile'] for item in catalog.SERVICES.values()]
                self.assertTrue(set(profiles) <= set(install.user_data_folders()))
                for folder in profiles:
                    folder.mkdir(parents=True)
                    (folder / 'Cookies').write_text('fixture only')
                personal = chrome / 'google-chrome'
                personal.mkdir()
                marker = personal / 'Cookies'
                marker.write_text('leave alone')
                install.clear_user_data()
                self.assertFalse(any(folder.exists() for folder in profiles))
                self.assertEqual('leave alone', marker.read_text())


if __name__ == '__main__':
    unittest.main()
