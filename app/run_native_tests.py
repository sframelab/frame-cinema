"""Frame-only isolated input tests. Never loads Netflix or an existing profile."""
from pathlib import Path
import argparse
import os
import shlex
import shutil
import signal
import subprocess
import tempfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--chrome', action='store_true')
args = parser.parse_args()
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'atspi-2', 'gtk+-3.0'], text=True))
subprocess.run(['g++', '-std=c++17', '-O2', 'test_native.cpp', '-lopenvr_api', '-lX11', '-lXtst', *flags, '-o', 'test_native'], cwd=root, check=True)
profile = None
config = Path.home() / '.var/app/com.google.Chrome/config'
if args.chrome:
    profile = Path(tempfile.mkdtemp(prefix='cinema-input-test-', dir=config)).resolve()
read_fd, write_fd = os.pipe()
display_process = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1920x1080x24', '-nolisten', 'tcp'], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.close(write_fd)
try:
    with os.fdopen(read_fd) as stream:
        display = ':' + stream.readline().strip()
    command = [str(root / 'test_native'), *(['--chrome', str(profile)] if profile else [])]
    test = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=dict(os.environ, DISPLAY=display, NO_AT_BRIDGE='0'), start_new_session=True)
    try:
        output, _ = test.communicate(timeout=30)
        print(output)
        result = test.returncode
    except subprocess.TimeoutExpired:
        os.killpg(test.pid, signal.SIGTERM)
        output, _ = test.communicate(timeout=5)
        print(output)
        print('Isolated input test timed out')
        result = 1
finally:
    display_process.terminate()
    display_process.wait(timeout=5)
    if profile and profile.parent == config.resolve() and profile.name.startswith('cinema-input-test-'):
        shutil.rmtree(profile)
raise SystemExit(result)
