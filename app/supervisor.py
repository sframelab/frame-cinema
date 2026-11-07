"""Own the scene and one video panel; local file IPC, no listening network port."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sys
import subprocess
import time
import uuid
from service_catalog import service
from process_group import ProcessGroup
from exit_record import event as exit_event

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home() / '.config/frame-cinema'
PREVIEW = os.environ.get('FRAME_CINEMA_NATIVE_PREVIEW') == '1'
RUNTIME = (Path(os.environ['FRAME_CINEMA_IPC']) if PREVIEW else
           Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'frame-cinema')


VRCMD = Path('/opt/steamvr/bin/linuxarm64/vrcmd')


LAUNCH_CLOSED_FOR, LAUNCH_REPORT_WAIT = 5, 20


def launch_dashboard_open(scene_state):
    """Whether SteamVR's dashboard is open as the app comes up; None until the app's own controls can tell.
    Until they have SteamVR's overlay interfaces ('borrowed') they report the dashboard closed whatever it is:
    on a launch in the headset the scene went live in that gap and 0.5.17 took the dashboard for closed."""
    native = scene_state.get('native_ui') if isinstance(scene_state, dict) else None
    if not isinstance(native, dict) or 'dashboard_visible' not in native or native.get('borrowed') is not True:
        return None
    return native['dashboard_visible'] is True


def launch_dashboard_verdict(opened, since_ready, closed_for):
    """'close' the launch dashboard, settle on 'not_open' after it has read closed for a few seconds, or on
    'unknown' when the controls never report; None keeps watching."""
    if opened:
        return 'close'
    if opened is False and closed_for > LAUNCH_CLOSED_FOR:
        return 'not_open'
    if opened is None and since_ready > LAUNCH_REPORT_WAIT:
        return 'unknown'
    return None


def hide_dashboard(vrcmd=VRCMD):
    # Steam starts Frame Cinema from its dashboard and, as for any non-Steam app, waits for a flat game window.
    # A VR app never opens one, so the dashboard stayed up over the cinema, on the app's page with a Resume
    # button. SteamVR's own tool closes it. The caller does this once per launch, so a dashboard the wearer
    # opens later is never closed.
    if not vrcmd.exists():
        return False
    libraries = ':'.join(filter(None, [str(vrcmd.parent), os.environ.get('LD_LIBRARY_PATH', '')]))
    try:
        return subprocess.run([str(vrcmd), '--hidedashboard'], env=dict(os.environ, LD_LIBRARY_PATH=libraries),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def panel_logs():
    """Godot's own logs folder: the scene runs with XDG_DATA_HOME set to this data home."""
    data = os.environ.get('FRAME_CINEMA_PREVIEW_GODOT_DATA') or os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local/share')
    return Path(data) / 'FrameCinema/logs'


def stop_optional_controllers(group):
    # A controller-renderer fault must not skip browser/scene cleanup.
    try:
        return group.stop(grace=0.1, kill_timeout=0.4).get('complete', False)
    except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
        return False


def panel_command(source, config, service_id='netflix'):
    selected = service(service_id)
    if source != 'local':
        raise ValueError('Choose a local streaming service')
    base = ['gamescope', '--backend', 'openvr', '-w', '1920', '-h', '1080',
            '--virtual-connector-strategy', 'SingleApplication',
            '--vr-overlay-key', 'frame-lab.cinema.video',
            '--vr-overlay-explicit-name', 'Frame Cinema - ' + selected['name'],
            '--vr-overlay-physical-width', '4.2', '--vr-overlay-show-immediately',
            '--vr-overlay-enable-click-stabilization', '--']
    if source == 'local':
        profile = Path.home() / '.var/app/com.google.Chrome/config' / selected['profile']
        child = [sys.executable, str(ROOT / 'browser_bridge.py'), '--no-first-run',
                 '--no-default-browser-check', f'--user-data-dir={profile}',
                 '--ozone-platform=x11', '--start-maximized', '--force-renderer-accessibility',
                 '--kiosk', '--app=' + selected['url']]
    return base + [str(ROOT / 'panel_host')] + child


class Session:
    def __init__(self, no_browser=False, runtime=None, scene_session=None):
        self.runtime = runtime
        self.scene_session = scene_session or uuid.uuid4().hex
        self.source_session = ''
        self.panel = None
        self.mode = 'auto'
        self.source = ''
        self.service_id = 'netflix'
        self.library = True
        self.reason = 'Ready'
        self.no_browser = no_browser
        self.last_panel_exit = None
        self.last_cleanup = None
        self.cleanup_pending = False
        self.config = {}

    def stop_panel(self):
        if self.panel is not None:
            try:
                self.last_cleanup = self.panel.stop()
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
                self.cleanup_pending = True
                self.last_cleanup = {'complete': False}
                self.reason = 'The service is still closing. Choose Reopen to retry.'
                return False
            self.panel = None
        self.cleanup_pending = False
        self.source_session = ''
        if self.runtime:
            for name in ['pointer.txt', 'keyboard.request', 'browser-command.txt', 'panel-status.json', 'media-status.json',
                         'browser-capture-request.json', 'browser-capture-request.tmp',
                         'browser-capture-result.json', 'browser-capture-result.tmp',
                         'browser-capture.png', 'browser-capture.tmp', 'ambient-status.json', 'ambient-status.tmp',
                         'desktop-session.txt', 'desktop-session.tmp']:
                (self.runtime / name).unlink(missing_ok=True)
            for item in (self.runtime / 'input').glob('*'):
                if item.suffix not in ('.evt', '.nav'): continue
                item.unlink(missing_ok=True)
            for item in (self.runtime / 'media').glob('*.json'):
                item.unlink(missing_ok=True)
        return True

    def home(self):
        if not self.stop_panel():
            return
        self.library = True
        self.source = ''
        self.reason = 'Choose a service'

    def select(self, mode, restart=False, service_id=None):
        if mode not in ('auto', 'local'):
            return
        next_service = self.service_id if service_id is None else service_id
        service(next_service)  # Validate before changing or stopping the current session.
        service_changed = next_service != self.service_id
        self.mode = mode
        target = 'local'
        self.reason = 'Opening playback'
        if not self.cleanup_pending and not restart and not service_changed and target == self.source and self.panel and self.panel.poll() is None:
            self.library = False
            return
        # Validate the destination before closing a usable source.
        try:
            command = panel_command(target, self.config, next_service)
        except ValueError as error:
            self.reason = str(error)
            if self.source == 'local' and self.panel and self.panel.poll() is None:
                return
            return
        if not self.stop_panel():
            return
        self.service_id = next_service
        self.library = False
        self.source = target
        if self.no_browser:
            self.reason = 'Environment test - video source not started'
            return
        try:
            env = dict(os.environ)
            env.setdefault('DISPLAY', ':0')
            env['FRAME_CINEMA_IPC'] = str(self.runtime or RUNTIME)
            env['FRAME_CINEMA_SESSION'] = self.scene_session
            self.source_session = uuid.uuid4().hex
            env['FRAME_CINEMA_SOURCE_SESSION'] = self.source_session
            env['FRAME_CINEMA_BROWSER_PIPE'] = '1'
            if PREVIEW:
                env.update(FRAME_CINEMA_SYSTEM_POINTER='1', FRAME_CINEMA_SCENE_OWNER='1')
            env['FRAME_CINEMA_LEASE_DIAGNOSTICS'] = '1'
            # A missing log folder must never stop a service from opening.
            try:
                logs = panel_logs()
                logs.mkdir(mode=0o700, parents=True, exist_ok=True)
                log = open(logs / time.strftime('panel-%H%M%S.log'), 'wb', buffering=0)
            except OSError:
                log = subprocess.DEVNULL
            try:
                self.panel = ProcessGroup(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            finally:
                if log is not subprocess.DEVNULL:
                    log.close()  # the panel has its own copy
            self.reason = 'Opening ' + service(self.service_id)['name']
        except (ValueError, OSError) as error:
            self.reason = str(error)

    def tick(self):
        if self.cleanup_pending:
            return  # An explicit source action retries; never create a retry loop.
        if self.panel is not None and self.panel.poll() is not None:
            self.last_panel_exit = self.panel.returncode
            if not self.stop_panel():
                return
            self.reason = 'The service closed. Choose Reopen to try again.'

    def status(self):
        return {'updated': time.time(), 'mode': self.mode, 'source': self.source, 'message': self.reason,
                'source_session': self.source_session,
                'service': self.service_id, 'service_name': service(self.service_id)['name'], 'library': self.library,
                'quality': 'Quality not measured', 'pc_verified_4k': False,
                'last_panel_exit': self.last_panel_exit,
                'cleanup_pending': self.cleanup_pending, 'last_cleanup': self.last_cleanup,
                'panel_running': not self.cleanup_pending and self.panel is not None and self.panel.poll() is None}


def run(args):
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUNTIME.chmod(0o700)
    (RUNTIME / 'input').mkdir(mode=0o700, exist_ok=True)
    (RUNTIME / 'media').mkdir(mode=0o700, exist_ok=True)
    lock = (RUNTIME / 'session.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Frame Cinema is already running')
    request = RUNTIME / 'request.json'
    request.unlink(missing_ok=True)
    # Do not replay the previous inspection action after a scene restart.
    for name in ['observe-request.json', 'observe-result.json']:
        (RUNTIME / name).unlink(missing_ok=True)
    for item in (RUNTIME / 'input').iterdir():
        if item.suffix not in ('.evt', '.nav'): continue
        item.unlink()
    (RUNTIME / 'pointer.txt').unlink(missing_ok=True)
    (RUNTIME / 'keyboard.request').unlink(missing_ok=True)
    (RUNTIME / 'browser-command.txt').unlink(missing_ok=True)
    (RUNTIME / 'panel-status.json').unlink(missing_ok=True)
    (RUNTIME / 'scene.json').unlink(missing_ok=True)
    (RUNTIME / 'exit-reason.json').unlink(missing_ok=True)
    (RUNTIME / 'media-status.json').unlink(missing_ok=True)
    for item in (RUNTIME / 'media').glob('*.json'):
        item.unlink()
    scene_session = uuid.uuid4().hex
    env = dict(os.environ, FRAME_CINEMA_IPC=str(RUNTIME), FRAME_CINEMA_SESSION=scene_session)
    env.setdefault('DISPLAY', ':0')
    runtime = Path('/opt/steamvr/steamxr_linuxarm64.json')
    if runtime.exists():
        env.setdefault('XR_RUNTIME_JSON', str(runtime))
    if PREVIEW:
        env.update(FRAME_CINEMA_SYSTEM_POINTER='1', FRAME_CINEMA_SCENE_OWNER='1')
        env['XDG_DATA_HOME'] = os.environ['FRAME_CINEMA_PREVIEW_GODOT_DATA']
    scene = subprocess.Popen([str(ROOT / 'godot'), '--path', str(ROOT), '--xr-mode', 'on',
                              '--', *(['--smoke'] if args.smoke else [])], env=env)
    controllers = None
    controller_binary = ROOT / 'controller_layer'
    if controller_binary.exists() and not PREVIEW:
        try:
            controller_env = dict(env, FRAME_CINEMA_SCENE_PID=str(scene.pid))
            controllers = ProcessGroup([str(controller_binary)], env=controller_env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass # Scene models remain visible if the optional layer cannot start.
    session = Session(args.no_browser, runtime=RUNTIME, scene_session=scene_session)
    last_request = None
    # The dashboard Steam launched the app from: closed once, when the app's controls first report it open.
    launch_dashboard, ready_since, closed_since = None, None, None
    try:
        # Let the local scene initialize before showing the playback panel.
        started = time.monotonic()
        while scene.poll() is None:
            if controllers is not None and controllers.poll() is not None:
                if stop_optional_controllers(controllers):
                    controllers = None
                    (RUNTIME / 'controller-layer.json').unlink(missing_ok=True)
            ready = False
            scene_state = {}
            try:
                scene_state = json.loads((RUNTIME / 'scene.json').read_text())
                ready = scene_state.get('xr_active', False) if isinstance(scene_state, dict) else False
            except (OSError, ValueError):
                pass
            # Not gated on PREVIEW: start.sh always sets it, so it is how the installed app runs.
            if ready and launch_dashboard is None:
                now = time.monotonic()
                ready_since = ready_since or now
                opened = launch_dashboard_open(scene_state)
                closed_since = (closed_since or now) if opened is False else None
                verdict = launch_dashboard_verdict(opened, now - ready_since, now - closed_since if closed_since else 0)
                if verdict == 'close':
                    launch_dashboard = 'closed' if hide_dashboard() else 'close_failed'
                elif verdict:
                    launch_dashboard = verdict
            if not ready and time.monotonic() - started > 4:
                session.reason = 'Preparing your cinema'
            try:
                value = json.loads(request.read_text())
                if ready and value.get('id') != last_request:
                    last_request = value.get('id')
                    if value.get('action') == 'library':
                        session.home()
                    else:
                        session.select(value.get('mode'), restart=value.get('restart') is True,
                                       service_id=value.get('service'))
            except (OSError, ValueError):
                pass
            session.tick()
            state = dict(session.status(), request_id=last_request, launch_dashboard=launch_dashboard)
            if PREVIEW:
                def identity(pid):
                    try:
                        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
                        return {'pid': pid, 'start': fields[19]}
                    except (OSError, IndexError):
                        return {}
                state['preview_children'] = {'scene': identity(scene.pid),
                    'panel': identity(session.panel.pid) if session.panel else {}}
            write_json(RUNTIME / 'status.json', state)
            time.sleep(0.2)
    finally:
        supervisor_stopped = scene.poll() is None
        if controllers is not None:
            stop_optional_controllers(controllers)
        (RUNTIME / 'controller-layer.json').unlink(missing_ok=True)
        (RUNTIME / 'controller-layer.tmp').unlink(missing_ok=True)
        (RUNTIME / 'controller-focus.txt').unlink(missing_ok=True)
        (RUNTIME / 'controller-focus.tmp').unlink(missing_ok=True)
        session.stop_panel()
        if scene.poll() is None:
            scene.terminate()
            try:
                scene.wait(timeout=5)
            except subprocess.TimeoutExpired:
                scene.kill()
                scene.wait(timeout=5)
        record = exit_event(RUNTIME, scene_session, scene.returncode, supervisor_stopped, session.last_panel_exit)
        write_json(RUNTIME / 'status.json', {'source': '', 'message': 'Cinema closed', 'exit': record})
        try:
            state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'frame-cinema'
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_json(state / 'last-exit.json', record)
        except OSError:
            pass  # Logging failure must not prevent owned-process cleanup.
    return scene.returncode


def stop_once(*_):
    # The first stop request ends the loop; later ones (the panel host sends its
    # own SIGTERM right after the group's) must not interrupt cleanup.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    arguments = parser.parse_args()
    signal.signal(signal.SIGTERM, stop_once)
    signal.signal(signal.SIGINT, stop_once)
    try:
        raise SystemExit(run(arguments))
    except KeyboardInterrupt:
        raise SystemExit(0)
