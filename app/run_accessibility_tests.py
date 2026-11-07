"""Frame-only asynchronous state tests on a disposable message bus."""
import datetime
import json
from pathlib import Path
import shlex
import subprocess

root = Path(__file__).resolve().parent
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'atspi-2'], text=True))
subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', 'test_accessible_state_probe.cpp',
                *flags, '-o', 'test_accessible_state_probe'], cwd=root, check=True)
result = subprocess.run(['dbus-run-session', '--', str(root / 'test_accessible_state_probe')],
                        cwd=root, capture_output=True, text=True, timeout=10)
lines = [line for line in result.stdout.splitlines()
         if line.startswith(('PASS ', 'FAIL ', 'Diagnostic ', 'Accessible state failures:'))]
report = {'date': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'mode': 'Frame ARM64, disposable D-Bus session; no service account access',
          'exit': result.returncode, 'checks': lines}
(root / 'accessible-state-test-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('\n'.join(lines))
raise SystemExit(result.returncode)
