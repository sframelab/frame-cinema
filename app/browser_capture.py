"""On-demand page capture through the existing browser owner; no extra pipe reader."""
import base64
import hashlib
import json
import re
import time
from media_control import HOSTS


def capture_pending(browser, session, runtime):
    request = runtime / 'browser-capture-request.json'
    if not request.exists():
        return
    result = {'id': '', 'ok': False}
    output = runtime / 'browser-capture.png'
    try:
        if request.stat().st_size > 512:
            return
        value = json.loads(request.read_text())
        if not isinstance(value, dict) or not re.fullmatch('[0-9a-f]{32}', str(value.get('id', ''))):
            return
        result['id'] = value['id']
        if not 0 <= time.time() - float(value.get('created', 0)) < 5:
            return
        eligible = browser.request('Runtime.evaluate', {'expression':
            '(()=>' + json.dumps(HOSTS) + '.some(d=>location.hostname===d || location.hostname.endsWith("."+d)))()',
            'returnByValue': True}, session)
        if eligible.get('result', {}).get('value') is not True:
            return
        # Capture only the owned service page. No arbitrary method, script,
        # destination, cookies or profile state is accepted from the requester.
        response = browser.request('Page.captureScreenshot', {
            'format': 'png', 'fromSurface': True, 'captureBeyondViewport': False,
        }, session, timeout=5, max_response_bytes=16 * 1024 * 1024)
        picture = base64.b64decode(response['data'], validate=True)
        if not picture.startswith(b'\x89PNG\r\n\x1a\n') or len(picture) > 12 * 1024 * 1024:
            return
        temporary = output.with_suffix('.tmp')
        temporary.write_bytes(picture)
        temporary.chmod(0o600)
        temporary.replace(output)
        result.update(ok=True, sha256=hashlib.sha256(picture).hexdigest(),
                      source='owned browser page; not headset compositor')
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, TimeoutError):
        pass
    finally:
        request.unlink(missing_ok=True)
        if not result['ok']:
            output.unlink(missing_ok=True)
        temporary = runtime / 'browser-capture-result.tmp'
        temporary.write_text(json.dumps(result))
        temporary.chmod(0o600)
        temporary.replace(runtime / 'browser-capture-result.json')
