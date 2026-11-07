"""Private-capture refusal tests and fresh pixels from disposable Frame Chrome."""
import json
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import Mock, patch

from browser_capture import capture_pending
from browser_pipe import BrowserPipe


def request(runtime, age=0):
    identity = uuid.uuid4().hex
    (runtime / 'browser-capture-request.json').write_text(json.dumps({
        'id': identity, 'created': time.time() - age}))
    return identity


def main():
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        runtime = Path(directory)
        fake = Mock()
        capture_pending(fake, 'session', runtime)
        fake.request.assert_not_called()
        checks.append('no_background_capture_without_request')
        request(runtime, age=10)
        (runtime / 'browser-capture.png').write_bytes(b'old screenshot')
        capture_pending(fake, 'session', runtime)
        fake.request.assert_not_called()
        assert not (runtime / 'browser-capture.png').exists()
        assert json.loads((runtime / 'browser-capture-result.json').read_text())['ok'] is False
        checks.append('expired_request_refused_and_stale_pixels_removed')
        (runtime / 'browser-capture-request.json').write_text('{"id":"../../outside"}')
        capture_pending(fake, 'session', runtime)
        fake.request.assert_not_called()
        checks.append('malformed_request_refused')
        request(runtime)
        fake.request.side_effect = TimeoutError()
        capture_pending(fake, 'session', runtime)
        assert json.loads((runtime / 'browser-capture-result.json').read_text())['ok'] is False
        checks.append('timeout_reported_without_old_image')

        config = Path.home() / '.var/app/com.google.Chrome/config'
        with tempfile.TemporaryDirectory(prefix='cinema-capture-test-', dir=config) as profile:
            with BrowserPipe(['--headless=new', '--no-first-run', '--no-default-browser-check',
                              '--window-size=800,600', '--user-data-dir=' + profile, 'about:blank']) as browser:
                version = browser.request('Browser.getVersion', timeout=12)['product']
                target = next(t for t in browser.request('Target.getTargets')['targetInfos'] if t['type'] == 'page')
                session = browser.request('Target.attachToTarget', {
                    'targetId': target['targetId'], 'flatten': True})['sessionId']
                hashes = []
                identity = request(runtime)
                capture_pending(browser, session, runtime)
                assert not json.loads((runtime / 'browser-capture-result.json').read_text())['ok']
                checks.append('unrelated_current_origin_refused')
                for color in ['red', 'blue']:
                    browser.request('Runtime.evaluate', {'expression':
                        'document.body.style.background=' + json.dumps(color)}, session)
                    identity = request(runtime)
                    with patch('browser_capture.HOSTS', ('',)):
                        capture_pending(browser, session, runtime)
                    result = json.loads((runtime / 'browser-capture-result.json').read_text())
                    assert result['ok'] and result['id'] == identity
                    assert (runtime / 'browser-capture.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                    hashes.append(result['sha256'])
                assert hashes[0] != hashes[1], 'Capture did not reflect changed page pixels'
                checks.append('real_chrome_capture_reflects_page_change')
                browser.request('Emulation.setDeviceMetricsOverride', {'width': 1200, 'height': 900,
                    'deviceScaleFactor': 1, 'mobile': False}, session)
                browser.request('Runtime.evaluate', {'expression': '''(()=>{
                    document.body.style.margin='0';const c=document.createElement('canvas');
                    c.width=1200;c.height=900;document.body.replaceChildren(c);
                    const x=c.getContext('2d'),a=x.createImageData(1200,900);
                    for(let i=0;i<a.data.length;i+=4){for(let j=0;j<3;j++) a.data[i+j]=Math.random()*256;a.data[i+3]=255;}
                    x.putImageData(a,0,0);history.pushState({},'', '#capture');
                })()'''}, session)
                request(runtime)
                with patch('browser_capture.HOSTS', ('',)):
                    capture_pending(browser, session, runtime)
                assert json.loads((runtime / 'browser-capture-result.json').read_text())['ok']
                assert (runtime / 'browser-capture.png').stat().st_size > 3 * 1024 * 1024
                history = browser.request('Page.getNavigationHistory', session=session)
                browser.request('Page.navigateToHistoryEntry', {'entryId': history['entries'][0]['id']}, session)
                checks.append('high_entropy_capture_above_old_limit_then_navigation')
                # A large rejected response must be drained, not left in the
                # transport to break later media/navigation commands.
                try:
                    browser.request('Runtime.evaluate', {'expression': '"x".repeat(5000000)',
                                    'returnByValue': True}, session, timeout=8)
                    raise AssertionError('Oversized response was accepted')
                except RuntimeError:
                    pass
                assert browser.request('Runtime.evaluate', {'expression': '21*2',
                    'returnByValue': True}, session)['result']['value'] == 42
                checks.append('oversized_response_does_not_poison_next_request')
                identity = request(runtime)
                capture_pending(browser, session, runtime)
                assert not json.loads((runtime / 'browser-capture-result.json').read_text())['ok']
                assert not (runtime / 'browser-capture.png').exists()
                checks.append('current_origin_rechecked_after_earlier_success')
        print(json.dumps({'checks': checks, 'browser': version, 'profile': 'disposable'}))


if __name__ == '__main__':
    main()
