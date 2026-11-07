"""Frame-only end-to-end test against a disposable Chrome input page.

Close Frame Cinema first. The test binary alone allows injected rays in dashboard.
No Netflix profile, credentials or remote debugging are used.
"""
from pathlib import Path
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import json
import datetime
import sys
from supervisor import panel_command

root = Path(__file__).resolve().parent
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'atspi-2', 'gobject-2.0', 'cairo'], text=True))
real_dashboard = '--production-routing' in sys.argv
definitions = ['-DFRAME_CINEMA_REAL_DASHBOARD'] if real_dashboard else []
subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', *definitions, 'test_compositor.cpp', '-lopenvr_api', '-lX11', '-lXtst', *flags, '-o', 'test_compositor'], cwd=root, check=True)
config = Path.home() / '.var/app/com.google.Chrome/config'
profile = Path(tempfile.mkdtemp(prefix='cinema-compositor-test-', dir=config)).resolve()
runtime = Path(tempfile.mkdtemp(prefix='frame-cinema-test-', dir=f'/run/user/{os.getuid()}'))
scene_ipc = runtime / 'scene'
panel_ipc = runtime / 'panel'
for path in [scene_ipc, panel_ipc]:
    (path / 'input').mkdir(parents=True)
env = dict(os.environ, XR_RUNTIME_JSON='/opt/steamvr/steamxr_linuxarm64.json', FRAME_CINEMA_IPC=str(scene_ipc))
env.setdefault('DISPLAY', ':0')
if '--navigation-only' in sys.argv:
    env['FRAME_CINEMA_NAVIGATION_TEST'] = '1'
if '--latency-only' in sys.argv:
    env['FRAME_CINEMA_LATENCY_TEST'] = '1'
if '--input-only' in sys.argv:
    env['FRAME_CINEMA_INPUT_TEST'] = '1'
scene_env = dict(env, XDG_DATA_HOME=str(runtime / 'godot-data'))
scene = subprocess.Popen([str(root / 'godot'), '--path', str(root), '--xr-mode', 'on'], cwd=root, env=scene_env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
production_command = panel_command('local', {})
command = production_command[:production_command.index(str(root / 'panel_host'))] + [str(root / 'test_compositor'), str(panel_ipc), str(profile)]
test = subprocess.Popen(command, cwd=root, env=env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
lines = []
def interrupted(signum, _frame):
    raise SystemExit(128 + signum)
signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGHUP, interrupted)
try:
    for line in test.stdout:
        if line.startswith(('PASS ', 'FAIL ', 'Running ', 'Diagnostic ', 'Compositor regression')):
            lines.append(line.strip())
            print(line.strip(), flush=True)
            (root / 'compositor-test-progress.json').write_text(json.dumps({'last': lines[-1], 'checks': len(lines)}))
    code = test.wait(timeout=10)
    if any(line.startswith('FAIL ') for line in lines) or 'Compositor regression failures: 0' not in lines:
        code = 1
    report = {'date': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'exit': code,
              'scope': 'latency' if '--latency-only' in sys.argv else 'input' if '--input-only' in sys.argv else 'navigation' if '--navigation-only' in sys.argv else 'full',
              'mode': 'Frame ARM64 Gamescope/OpenVR with production compositor flags and disposable Chrome',
              'dashboard_gate': 'production' if real_dashboard else 'bypassed in fixture',
              'steam_launch': bool(os.environ.get('SteamAppId') or os.environ.get('SteamGameId')),
              'pose_substitution': 'fixed headset pose only if tracking unavailable', 'checks': lines}
    try:
        scene_status = json.loads((scene_ipc / 'scene.json').read_text())
        report['scene'] = {key: scene_status.get(key) for key in ['version', 'engine', 'xr_active', 'session_state']}
    except (OSError, ValueError):
        pass
    (root / 'compositor-test-result.json').write_text(json.dumps(report, indent=2))
finally:
    for process in [test, scene]:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    if profile.parent == config.resolve() and profile.name.startswith('cinema-compositor-test-'):
        shutil.rmtree(profile)
    if runtime.parent == Path(f'/run/user/{os.getuid()}') and runtime.name.startswith('frame-cinema-test-'):
        shutil.rmtree(runtime)
raise SystemExit(code)
