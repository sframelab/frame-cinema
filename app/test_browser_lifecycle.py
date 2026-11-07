"""Frame-only real Chrome shutdown/reopen test; disposable profile and X display."""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from process_group import ProcessGroup


def run():
    root = Path(__file__).resolve().parent
    config = Path.home() / '.var/app/com.google.Chrome/config'
    profile = Path(tempfile.mkdtemp(prefix='cinema-lifecycle-test-', dir=config)).resolve()
    reports = []
    group = None
    display = None
    read_fd, write_fd = os.pipe()
    try:
        display = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x720x24', '-nolisten', 'tcp'],
                                   pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(write_fd)
        write_fd = None
        if not select.select([read_fd], [], [], 5)[0]:
            raise RuntimeError('Disposable display did not start')
        with os.fdopen(read_fd) as stream:
            display_name = ':' + stream.readline().strip()
        read_fd = None
        with tempfile.TemporaryDirectory(prefix='cinema-browser-lifecycle-') as location:
            runtime = Path(location)
            env = dict(os.environ, DISPLAY=display_name, FRAME_CINEMA_IPC=str(runtime))
            command = [sys.executable, str(root / 'browser_bridge.py'), '--no-first-run', '--no-default-browser-check',
                       '--user-data-dir=' + str(profile), '--ozone-platform=x11', '--app=about:blank']
            # A disposable parent stands in for Gamescope, so we can exercise
            # its early exit without registering or replacing any VR overlays.
            parent = 'import subprocess,time; subprocess.Popen(%r); time.sleep(60)' % command
            for crash in (False, True, False):
                (runtime / 'media-status.json').unlink(missing_ok=True)
                group = ProcessGroup([sys.executable, '-c', parent], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    try:
                        if json.loads((runtime / 'media-status.json').read_text()).get('available'):
                            break  # A real browser pipe roundtrip has completed.
                    except (OSError, ValueError):
                        pass
                    time.sleep(.05)
                else:
                    raise RuntimeError('Disposable Chrome did not answer after launch')
                if crash:
                    os.kill(group.pid, signal.SIGKILL)
                    deadline = time.monotonic() + 2
                    while group.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    if group.poll() != -signal.SIGKILL:
                        raise RuntimeError('Disposable leader did not exit as expected')
                start = time.monotonic()
                report = group.stop()
                reports.append(dict(report, parent_crashed=crash, browser_answered=True,
                                    stop_seconds=round(time.monotonic() - start, 3)))
                group = None
        return {'scope': 'Isolated Chrome and private Xvfb, no VR or service account',
                'cycles': reports, 'same_profile_reopened': len(reports) == 3, 'success': True}
    finally:
        if group is not None:
            group.stop(grace=.2)
        if display is not None:
            display.terminate()
            display.wait(timeout=3)
        for descriptor in (read_fd, write_fd):
            if descriptor is not None:
                os.close(descriptor)
        if profile.parent == config.resolve() and profile.name.startswith('cinema-lifecycle-test-'):
            shutil.rmtree(profile)


if __name__ == '__main__':
    result = run()
    (Path(__file__).resolve().parent / 'browser-lifecycle-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
