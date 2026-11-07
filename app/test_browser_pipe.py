"""Frame-only pipe/DOM test in a disposable profile; no account pages or credentials."""
import json
import base64
from pathlib import Path
import tempfile
import time
import subprocess
from unittest.mock import patch
from browser_pipe import BrowserPipe
from media_control import operation, state, supported_url, PREFIX


def main():
    config = Path.home() / '.var/app/com.google.Chrome/config'
    control_root = config / 'frame-cinema-control'
    before_sessions = set(control_root.glob('session-*'))
    before_fds = len(list(Path('/proc/self/fd').iterdir()))
    with patch('browser_pipe.subprocess.Popen', side_effect=OSError('synthetic launch failure')):
        try:
            BrowserPipe([])
            raise AssertionError('Expected launch failure')
        except OSError:
            pass
    assert set(control_root.glob('session-*')) == before_sessions
    assert len(list(Path('/proc/self/fd').iterdir())) == before_fds
    with tempfile.TemporaryDirectory(prefix='cinema-pipe-test-', dir=config) as profile:
        movie = Path(profile) / 'fixture.webm'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=12',
                        '-t', '25', '-c:v', 'libvpx', '-an', '-y', str(movie)], check=True)
        media = 'data:video/webm;base64,' + base64.b64encode(movie.read_bytes()).decode()
        with BrowserPipe(['--headless=new', '--no-first-run', '--no-default-browser-check',
                          '--user-data-dir=' + profile, 'about:blank']) as browser:
            version = browser.request('Browser.getVersion', timeout=12)['product']
            target = next(t for t in browser.request('Target.getTargets')['targetInfos'] if t['type'] == 'page')
            session = browser.request('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True})['sessionId']
            result = browser.request('Runtime.evaluate', {'expression': '21*2', 'returnByValue': True}, session)
            assert result['result']['value'] == 42
            checks = ['launch_failure_resource_cleanup', 'pipe_roundtrip', 'page_evaluation']
            assert supported_url('https://www.netflix.com/watch/test') and not supported_url('https://netflix.com.evil.test/')
            assert state(browser, session)['page_ready'] is False
            checks.append('reject_unrelated_origin')
            assert operation(browser, session, 'browser_back') == {'ok': False, 'reason': 'unavailable'}
            # The only history in this disposable browser is our blank fixture.
            with patch('media_control.supported_url', lambda url: url.startswith('about:blank')):
                assert operation(browser, session, 'browser_back') == {'ok': False, 'reason': 'no_history'}
                browser.request('Runtime.evaluate', {'expression': "history.pushState({},'', '#one');history.pushState({},'', '#two');window.addEventListener('keydown',e=>e.preventDefault())"}, session)
                assert operation(browser, session, 'browser_back')['ok']
                assert operation(browser, session, 'browser_back')['ok']
                history = browser.request('Page.getNavigationHistory', session=session)
                assert history['currentIndex'] == 0
                checks.append('two_back_actions_traverse_two_real_history_entries')
                assert operation(browser, session, 'browser_back') == {'ok': False, 'reason': 'no_history'}
                checks.append('empty_history_returns_explicit_refusal')
                browser.request('Runtime.evaluate', {'expression': 'window.fixtureMarker=1'}, session)
                assert operation(browser, session, 'browser_reload')['ok']
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    marker = browser.request('Runtime.evaluate', {'expression': 'typeof window.fixtureMarker', 'returnByValue': True}, session)
                    if marker['result']['value'] == 'undefined': break
                    time.sleep(.05)
                else: raise AssertionError('Reload did not replace the document')
                checks.append('reload_replaces_document')
            setup = "(async()=>{document.body.innerHTML='<video muted></video>';const v=document.querySelector('video');v.muted=true;v.src=" + json.dumps(media) + ";await new Promise((ok,bad)=>{v.onloadedmetadata=ok;v.onerror=bad;setTimeout(bad,5000)});return v.duration})()"
            browser.request('Runtime.evaluate', {'expression':setup, 'awaitPromise':True, 'returnByValue':True}, session, timeout=8)
            # Synthetic about:blank document with real local video. Shadow only
            # the evaluated location as an HBO title; retain the empty host for
            # the real same-origin blank iframe. Production guards are unchanged.
            fixture_prefix = 'const location={hostname:"play.hbomax.com",pathname:"/video/watch/fixture"};' + PREFIX
            with patch('media_control.HOSTS', ('', 'hbomax.com')), patch('media_control.PREFIX', fixture_prefix):
                assert state(browser, session)['duration'] >= 24
                assert operation(browser, session, 'toggle_play')['ok']
                time.sleep(.5)
                playing = state(browser, session)
                assert not playing['paused'] and playing['current'] > 0 and playing['width'] == 320
                checks.append('actual_video_playback_and_dimensions')
                assert operation(browser, session, 'toggle_play')['ok'] and state(browser, session)['paused']
                before = state(browser, session)['current']
                assert operation(browser, session, 'forward_10')['ok']
                assert abs(state(browser, session)['current']-before-10) < .5
                assert operation(browser, session, 'back_10')['ok']
                assert abs(state(browser, session)['current']-before) < .5
                checks.append('pause_and_bidirectional_seek')
                hidden = "(()=>{const preview=document.createElement('video');preview.id='hidden-preview';preview.style.cssText='width:1920px;height:1080px;visibility:hidden';document.body.append(preview)})()"
                browser.request('Runtime.evaluate', {'expression':hidden}, session)
                assert state(browser, session)['width'] == 320, 'Hidden preview replaced the visible player'
                browser.request('Runtime.evaluate', {'expression':"document.getElementById('hidden-preview').remove()"}, session)
                checks.append('hidden_preview_cannot_replace_visible_player')
                browser.request('Runtime.evaluate', {'expression':'document.documentElement.requestFullscreen()', 'awaitPromise':True, 'userGesture':True}, session)
                assert state(browser, session)['fullscreen']
                assert operation(browser, session, 'exit_fullscreen')['ok'] and not state(browser, session)['fullscreen']
                checks.append('real_dom_fullscreen_exit')
                styled = browser.request('Runtime.evaluate', {'expression':'getComputedStyle(document.documentElement).scrollbarWidth','returnByValue':True},session)
                assert styled['result']['value']=='none'
                checks.append('hidden_page_scrollbar')
                shadow = "(()=>{const v=document.querySelector('video');const host=document.createElement('div');document.body.append(host);host.attachShadow({mode:'open'}).append(v);return document.querySelector('video')===null})()"
                assert browser.request('Runtime.evaluate', {'expression':shadow,'returnByValue':True},session)['result']['value']
                assert state(browser, session)['video'] and state(browser, session)['width']==320
                assert operation(browser, session, 'toggle_play')['ok']
                assert not state(browser, session)['paused']
                checks.append('open_shadow_player_discovery_and_control')
                framed = "(async()=>{const host=[...document.querySelectorAll('div')].find(e=>e.shadowRoot);const v=host.shadowRoot.querySelector('video');v.pause();const frame=document.createElement('iframe');document.body.append(frame);frame.contentDocument.body.append(v);await v.play();return !document.querySelector('video') && !host.shadowRoot.querySelector('video')})()"
                assert browser.request('Runtime.evaluate', {'expression':framed,'awaitPromise':True,'userGesture':True,'returnByValue':True},session)['result']['value']
                assert state(browser, session)['video'] and state(browser, session)['width']==320
                assert operation(browser, session, 'toggle_play')['ok'] and state(browser, session)['paused']
                checks.append('same_origin_frame_discovery_and_control')
                editor = "(()=>{const d=document.querySelector('iframe').contentDocument;const host=d.createElement('div');d.body.append(host);const shadow=host.attachShadow({mode:'open'});const input=d.createElement('input');shadow.append(input);input.focus()})()"
                browser.request('Runtime.evaluate', {'expression':editor}, session)
                editing = state(browser, session)
                assert not editing['can_control'] and not editing['can_seek'], 'Embedded text field left media controls enabled'
                for command in ['toggle_play', 'forward_10', 'back_10']:
                    assert operation(browser, session, command) == {'ok':False, 'reason':'editor_focused'}
                assert state(browser, session)['paused']
                checks.append('nested_frame_shadow_editor_blocks_media_commands')
                browser.request('Runtime.evaluate', {'expression':"document.querySelector('iframe').style.display='none'"}, session)
                assert not state(browser, session)['video'], 'A hidden frame must not expose a visible player'
                checks.append('hidden_frame_player_is_not_selected')
            print(json.dumps({'browser': version, 'pipe_roundtrip': True, 'page_evaluation': True,
                              'network_debug_port': False, 'profile': 'disposable', 'checks': checks}))


if __name__ == '__main__':
    main()
