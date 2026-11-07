"""Run the service browser with owned pipe controls and content-free media telemetry."""
import json
import os
from pathlib import Path
import signal
import sys
import time

from browser_pipe import BrowserPipe
from video_frame_clock import VideoFrameClock
from browser_scroll import ScrollChannel
from native_scroll_activity import NativeScrollActivity
from browser_capture import capture_pending
from media_control import OPERATIONS, operation, state, supported_url


def dispatch(browser, session, command):
    if not isinstance(command, dict) or type(command.get('id')) is not int or command['id'] <= 0:
        return {'id': 0, 'ok': False, 'reason': 'invalid'}
    result = {'id': command['id'], 'ok': False}
    try:
        if not 0 <= time.time() - float(command.get('created', 0)) < 10:
            return dict(result, reason='expired')
        if command.get('op') not in OPERATIONS:
            return dict(result, reason='invalid')
        value = operation(browser, session, command['op'])
        reason = value.get('reason', '')
        return dict(result, ok=value.get('ok') is True,
                    reason=reason if reason in ('no_video', 'not_seekable', 'no_history', 'unavailable') else '')
    except (ValueError, TypeError, OSError, RuntimeError, TimeoutError):
        return dict(result, reason='unavailable')


def keep_page_focused(browser, session):
    # Gamescope gives the X focus to Chrome's own suggestion popups (saved logins, passkeys, addresses) as they
    # open, Chrome closes them at once, and no window is left focused. That happens on every typed character, so
    # the page lost focus after nearly every key. Focus emulation keeps the page focused through that churn; the
    # panel host still restores the X focus before each key, so typing reaches the page as before.
    try:
        browser.request('Emulation.setFocusEmulationEnabled', {'enabled': True}, session=session, timeout=8)
        return True
    except (RuntimeError, TimeoutError):
        return False


def developer_hooks(environ=os.environ):
    # Page screenshots on request are for development. They stay off unless FRAME_CINEMA_DEVELOPER=1.
    return environ.get('FRAME_CINEMA_DEVELOPER') == '1'


def write_status(runtime, value):
    value['updated'] = time.time()
    value['scene_session'] = os.environ.get('FRAME_CINEMA_SESSION', '')
    value['source_session'] = os.environ.get('FRAME_CINEMA_SOURCE_SESSION', '')
    path = runtime / 'media-status.tmp'
    path.write_text(json.dumps(value))
    path.replace(runtime / 'media-status.json')


def run(arguments):
    os.umask(0o077)
    runtime = Path(os.environ['FRAME_CINEMA_IPC'])
    for name in ['browser-capture-request.json', 'browser-capture-result.json', 'browser-capture.png']:
        (runtime / name).unlink(missing_ok=True)
    scroll = (NativeScrollActivity(runtime) if os.environ.get('FRAME_CINEMA_NATIVE_SCROLL') == '1'
              else ScrollChannel(runtime))
    commands = runtime / 'media'
    commands.mkdir(mode=0o700, exist_ok=True)
    clock = VideoFrameClock(runtime) if os.environ.get("FRAME_CINEMA_STEREO") == "1" else None
    capture = developer_hooks()
    session = None
    last_poll = 0.0
    last_command = {'id': 0, 'ok': True}
    with BrowserPipe(arguments) as browser:
        while browser.process.poll() is None:
            try:
                if session is None:
                    targets = browser.request('Target.getTargets', timeout=8)['targetInfos']
                    pages = [target for target in targets if target['type'] == 'page' and supported_url(target.get('url', ''))]
                    if not pages:
                        write_status(runtime, {'available': True, 'page_ready': False, 'video': False})
                        time.sleep(0.3)
                        continue
                    session = browser.request('Target.attachToTarget', {'targetId': pages[0]['targetId'], 'flatten': True})['sessionId']
                    keep_page_focused(browser, session)
                    if clock: clock.attach(browser, session)
                if clock: browser.pump_events()
                scroll.poll(browser, session)
                if capture and not scroll.busy():
                    capture_pending(browser, session, runtime)
                for path in sorted(commands.glob('*.json'))[:16]:
                    try:
                        if path.stat().st_size > 1024:
                            continue
                        command = json.loads(path.read_text())
                        scroll.cancel()
                        last_command = dispatch(browser, session, command)
                    except (ValueError, OSError, RuntimeError, TimeoutError):
                        last_command = {'id': 0, 'ok': False, 'reason': 'unavailable'}
                    finally:
                        path.unlink(missing_ok=True)
                if time.monotonic() - last_poll > 0.4 and not scroll.busy():
                    snapshot = state(browser, session)
                    if clock: clock.install(browser)
                    write_status(runtime, dict(snapshot, available=True, last_command=last_command))
                    last_poll = time.monotonic()
                time.sleep(min(.002, scroll.wait_time()) if clock else scroll.wait_time())
            except (ValueError, RuntimeError, TimeoutError, OSError):
                scroll.cancel()
                write_status(runtime, {'available': False, 'video': False, 'last_command': last_command})
                if session:
                    try:
                        browser.request('Target.detachFromTarget', {'sessionId': session}, timeout=1)
                    except (RuntimeError, TimeoutError, OSError):
                        pass
                session = None
                time.sleep(0.5)
        return browser.process.returncode


def stop_once(*_):
    # The first stop request ends the loop; later ones (the panel host sends its
    # own SIGTERM right after the group's) must not interrupt cleanup.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, stop_once)
    try:
        raise SystemExit(run(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(0)
