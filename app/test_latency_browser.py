"""Disposable compositor fixture; numeric DOM counter, no service accounts.

Chrome's X11 title update is not a precise clock for DOM event delivery.
"""
import os
from pathlib import Path
import signal
import sys
import time
from browser_pipe import BrowserPipe


def main():
    profile, page = sys.argv[1:]
    runtime = Path(os.environ['FRAME_CINEMA_IPC'])
    if 'cinema-compositor-test-' not in profile or not page.startswith('--app=data:text/html,'):
        raise ValueError('Disposable synthetic fixture required')
    with BrowserPipe(['--no-first-run', '--no-default-browser-check', profile,
                      '--ozone-platform=x11', '--start-maximized', '--force-renderer-accessibility', page]) as browser:
        session = None
        deadline = time.monotonic() + 90
        while browser.process.poll() is None and time.monotonic() < deadline:
            if session is None:
                pages = [t for t in browser.request('Target.getTargets')['targetInfos'] if t['type'] == 'page']
                if not pages:
                    time.sleep(.01)
                    continue
                session = browser.request('Target.attachToTarget', {'targetId':pages[0]['targetId'], 'flatten':True})['sessionId']
            result = browser.request('Runtime.evaluate', {'expression':'Number(window.cinemaFixtureClicks || 0)', 'returnByValue':True}, session)
            value = result['result'].get('value', 0)
            if type(value) in (int, float):
                path = runtime / 'latency-dom.tmp'
                path.write_text(str(int(value)))
                path.replace(runtime / 'latency-dom.txt')
            time.sleep(.005)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        main()
    except KeyboardInterrupt:
        pass
