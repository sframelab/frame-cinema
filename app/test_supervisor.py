import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

if sys.platform == 'linux':
    from supervisor import Session, panel_command


@unittest.skipUnless(sys.platform == 'linux', 'Native Frame supervisor uses Linux process groups')
class SupervisorTests(unittest.TestCase):
    def test_local_uses_a_dedicated_profile_without_debug_port(self):
        command = panel_command('local', {})
        self.assertIn('--backend', command)
        self.assertTrue(any(part.endswith('/browser_bridge.py') for part in command))
        self.assertEqual(sum(x.startswith('--user-data-dir=') for x in command), 1)
        self.assertFalse(any('remote-debugging' in x for x in command))
        self.assertIn('--force-renderer-accessibility', command)

    def test_pc_capture_scope_is_explicit(self):
        with self.assertRaises(ValueError):
            panel_command('pc', {'host': '192.168.1.10', 'application': 'Netflix'})
        with self.assertRaises(ValueError):
            panel_command('pc', {'host': '192.168.1.10', 'application': 'Desktop',
                                 'display_capture_acknowledged': True})

    def test_five_services_have_isolated_profiles_and_fixed_destinations(self):
        commands = [panel_command('local', {}, name) for name in ['netflix', 'hbomax', 'disneyplus', 'primevideo', 'plex']]
        profiles = [next(part for part in command if part.startswith('--user-data-dir=')) for command in commands]
        self.assertEqual(len(set(profiles)), 5)
        self.assertTrue(profiles[0].endswith('/frame-cinema'))
        self.assertIn('--app=https://www.disneyplus.com/', commands[2])
        self.assertIn('--app=https://www.primevideo.com/', commands[3])
        self.assertIn('--app=https://app.plex.tv/desktop/', commands[4])
        self.assertTrue(all('--kiosk' in command for command in commands))
        with self.assertRaises(ValueError):
            panel_command('local', {}, '../../foreign-profile')

    def test_switching_service_replaces_panel_and_preserves_selected_service(self):
        session = Session()
        session.source = 'local'
        session.panel = Mock()
        session.panel.poll.return_value = None
        with patch.object(session, 'stop_panel', return_value=True) as stop, patch('supervisor.ProcessGroup') as spawn:
            session.select('local', service_id='hbomax')
            stop.assert_called_once()
            self.assertEqual(session.service_id, 'hbomax')
            self.assertIn('--app=https://hbomax.com/login', spawn.call_args.args[0])

    def test_invalid_service_does_not_stop_existing_playback(self):
        session = Session()
        with patch.object(session, 'stop_panel') as stop:
            with self.assertRaises(ValueError):
                session.select('local', service_id='https://example.com')
            stop.assert_not_called()

    def test_library_stops_playback_and_does_not_restart_automatically(self):
        session = Session(no_browser=True)
        with patch.object(session, 'stop_panel') as stop:
            session.home()
            session.tick()
            stop.assert_called_once()
            self.assertTrue(session.library)
            self.assertEqual(session.source, '')

    def test_resolution_request_is_not_a_quality_claim(self):
        session = Session(no_browser=True)
        session.config = {'host': '192.168.1.10', 'application': 'Netflix',
                          'display_capture_acknowledged': True, 'verified_4k': True}
        session.select('auto')
        self.assertEqual(session.source, 'local')
        self.assertFalse(session.status()['pc_verified_4k'])
        self.assertEqual(session.status()['quality'], 'Quality not measured')

    def test_auto_retains_existing_browser_process(self):
        session = Session()
        session.source = 'local'
        session.panel = Mock()
        session.panel.poll.return_value = None
        with patch.object(session, 'stop_panel') as stop:
            session.select('auto')
            stop.assert_not_called()

    def test_pc_disconnect_reopens_local_without_retry_loop(self):
        session = Session(no_browser=True)
        session.mode, session.source = 'pc', 'pc'
        session.panel = Mock()
        session.panel.poll.return_value = 1
        session.panel.returncode = 1
        with patch.object(session, 'stop_panel', side_effect=lambda: (setattr(session, 'panel', None), True)[1]):
            session.tick()
            self.assertEqual(session.source, 'local')
            self.assertEqual(session.mode, 'pc')
            session.tick()
            self.assertEqual(session.source, 'local')

    def test_bad_pc_config_preserves_live_browser(self):
        session = Session()
        session.source = 'local'
        session.panel = Mock()
        session.panel.poll.return_value = None
        session.config = {'host': 'bad host!', 'application': 'Netflix', 'display_capture_acknowledged': True}
        with patch.object(session, 'stop_panel') as stop:
            session.select('pc')
            stop.assert_not_called()
            self.assertEqual(session.source, 'local')

    def test_pc_spawn_error_falls_back_to_local(self):
        session = Session()
        session.config = {'host': '192.168.1.10', 'application': 'Netflix', 'display_capture_acknowledged': True}
        with patch('supervisor.ProcessGroup', side_effect=[OSError('unavailable'), Mock()]) as spawn:
            session.select('pc')
            self.assertEqual(session.source, 'local')
            self.assertEqual(spawn.call_count, 2)

    def test_explicit_reopen_restarts_same_source(self):
        session = Session()
        session.source = 'local'
        session.panel = Mock()
        session.panel.poll.return_value = None
        with patch.object(session, 'stop_panel', return_value=True) as stop, patch('supervisor.ProcessGroup') as spawn:
            session.select('local', restart=True)
            stop.assert_called_once()
            spawn.assert_called_once()

    def test_stop_discards_commands_that_must_not_replay(self):
        with tempfile.TemporaryDirectory() as location:
            runtime = Path(location)
            (runtime / 'input').mkdir()
            (runtime / 'media').mkdir()
            files = ['pointer.txt', 'keyboard.request', 'browser-command.txt', 'panel-status.json', 'media-status.json',
                     'browser-capture-request.json', 'browser-capture-request.tmp', 'browser-capture-result.json',
                     'browser-capture-result.tmp', 'browser-capture.png', 'browser-capture.tmp',
                     'input/1.evt', 'input/2.nav', 'media/1.json']
            for name in files:
                (runtime / name).write_text('synthetic')
            session = Session(runtime=runtime)
            session.stop_panel()
            self.assertFalse(any((runtime / name).exists() for name in files))

    def test_incomplete_cleanup_preserves_source_and_prevents_overlap(self):
        session = Session()
        session.library = False
        session.source = 'local'
        session.panel = Mock()
        session.panel.poll.return_value = None
        session.panel.stop.side_effect = TimeoutError('fixture')
        with patch('supervisor.ProcessGroup') as spawn:
            session.select('local', service_id='disneyplus')
            spawn.assert_not_called()
            self.assertEqual(session.service_id, 'netflix')
            self.assertTrue(session.status()['cleanup_pending'])
            self.assertFalse(session.status()['panel_running'])
            self.assertFalse(session.library)
            session.tick()
            self.assertEqual(session.panel.stop.call_count, 1)

    def test_library_does_not_claim_browser_closed_when_cleanup_failed(self):
        session = Session()
        session.library = False
        session.source = 'local'
        session.panel = Mock()
        session.panel.stop.side_effect = TimeoutError('fixture')
        session.home()
        self.assertFalse(session.library)
        self.assertEqual(session.source, 'local')
        self.assertTrue(session.cleanup_pending)

    def test_explicit_retry_can_finish_cleanup_and_start_new_source(self):
        session = Session()
        session.library = False
        session.source = 'local'
        session.cleanup_pending = True
        session.panel = Mock()
        session.panel.poll.return_value = None
        session.panel.stop.return_value = {'complete': True, 'forced': True}
        with patch('supervisor.ProcessGroup') as spawn:
            session.select('local', restart=True, service_id='hbomax')
            spawn.assert_called_once()
        self.assertFalse(session.cleanup_pending)
        self.assertEqual(session.service_id, 'hbomax')


@unittest.skipUnless(sys.platform == 'linux', 'Native Frame supervisor uses Linux process groups')
class LaunchDashboardTests(unittest.TestCase):
    def test_waits_for_the_app_controls_to_report_the_dashboard(self):
        from supervisor import launch_dashboard_open
        for state in ({}, {'native_ui': {}}, {'native_ui': None}, [], None):
            self.assertIsNone(launch_dashboard_open(state))
        self.assertTrue(launch_dashboard_open({'native_ui': {'borrowed': True, 'dashboard_visible': True}}))
        self.assertFalse(launch_dashboard_open({'native_ui': {'borrowed': True, 'dashboard_visible': False}}))

    def test_a_closed_reading_counts_only_once_the_controls_reach_steamvr(self):
        # 0.5.17 in the headset: the scene went live before the controls had SteamVR's overlay interfaces, they
        # read the dashboard as closed, and the Resume page stayed up.
        from supervisor import launch_dashboard_open
        for borrowed in ({}, {'borrowed': False}, {'borrowed': None}):
            self.assertIsNone(launch_dashboard_open({'native_ui': dict(borrowed, dashboard_visible=False)}))
            self.assertIsNone(launch_dashboard_open({'native_ui': dict(borrowed, dashboard_visible=True)}))

    def test_settles_on_closed_only_after_a_few_seconds(self):
        from supervisor import launch_dashboard_verdict
        self.assertEqual(launch_dashboard_verdict(True, 0, 0), 'close')
        self.assertEqual(launch_dashboard_verdict(True, 12, 4), 'close')  # opened soon after a closed reading
        self.assertIsNone(launch_dashboard_verdict(False, 3, 3))
        self.assertEqual(launch_dashboard_verdict(False, 6, 5.5), 'not_open')
        self.assertIsNone(launch_dashboard_verdict(None, 19, 0))
        self.assertEqual(launch_dashboard_verdict(None, 21, 0), 'unknown')

    def test_closes_the_dashboard_with_steamvrs_tool(self):
        from supervisor import hide_dashboard
        with tempfile.TemporaryDirectory() as folder:
            calls = Path(folder) / 'calls'
            tool = Path(folder) / 'vrcmd'
            tool.write_text(f'#!/bin/sh\necho "$@" >> {calls}\nexit 0\n')
            tool.chmod(0o755)
            self.assertTrue(hide_dashboard(tool))
            self.assertEqual(calls.read_text(), '--hidedashboard\n')
            tool.write_text('#!/bin/sh\nexit 1\n')
            self.assertFalse(hide_dashboard(tool))
            self.assertFalse(hide_dashboard(Path(folder) / 'missing'))


if __name__ == '__main__':
    unittest.main()
