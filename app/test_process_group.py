"""Real Linux process tests. No browser, compositor, profiles or desktop input."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from process_group import ProcessGroup


def live(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] not in ('Z', 'X')
    except FileNotFoundError:
        return False


@contextmanager
def fixture(ignore=False, leader_exit=None):
    with tempfile.TemporaryDirectory(prefix='cinema-process-test-') as location:
        root = Path(location)
        child = f'''
import signal,sys,time
from pathlib import Path
root=Path({str(root)!r})
def stop(*_):
    time.sleep(.2)
    (root/'flushed').write_text('done')
    sys.exit(0)
signal.signal(signal.SIGTERM,signal.SIG_IGN if {ignore!r} else stop)
(root/'child-ready').write_text('ready')
time.sleep(60)
'''
        leader = f'''
import subprocess,sys,time
from pathlib import Path
root=Path({str(root)!r})
child=subprocess.Popen([sys.executable,'-c',{child!r}])
(root/'child').write_text(str(child.pid))
while not (root/'child-ready').exists(): time.sleep(.01)
(root/'ready').write_text('ready')
if {leader_exit!r} is not None: sys.exit({leader_exit!r})
time.sleep(60)
'''
        group = ProcessGroup([sys.executable, '-c', leader], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not (root / 'ready').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if not (root / 'ready').exists():
                raise RuntimeError('Disposable process fixture did not start')
            yield group, int((root / 'child').read_text()), root
        finally:
            group.stop(grace=.1, kill_timeout=2)


@unittest.skipUnless(sys.platform == 'linux', 'Uses Linux waitid and procfs')
class ProcessGroupTests(unittest.TestCase):
    def test_waits_for_child_to_flush_after_leader_exits(self):
        with fixture() as (group, child, root):
            result = group.stop(grace=2)
            self.assertTrue(result['complete'])
            self.assertFalse(result['forced'])
            self.assertTrue((root / 'flushed').exists())
            self.assertFalse(live(child))

    def test_escalates_only_its_group_and_waits_for_child(self):
        foreign = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            with fixture(ignore=True) as (group, child, _):
                result = group.stop(grace=.15)
                self.assertTrue(result['complete'])
                self.assertTrue(result['forced'])
                self.assertFalse(live(child))
                self.assertIsNone(foreign.poll())
        finally:
            foreign.terminate()
            foreign.wait(timeout=3)

    def test_poll_preserves_exited_leader_until_children_are_cleaned(self):
        with fixture(ignore=True, leader_exit=37) as (group, child, _):
            deadline = time.monotonic() + 3
            while group.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(group.poll(), 37)
            self.assertEqual(os.waitid(os.P_PID, group.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT).si_status, 37)
            self.assertTrue(live(child))
            group.stop(grace=.15)
            self.assertFalse(live(child))
            self.assertEqual(group.returncode, 37)

    def test_second_stop_never_signals_a_reused_group_number(self):
        with fixture() as (group, _, _):
            first = group.stop(grace=2)
            with patch('process_group.os.killpg') as kill:
                self.assertEqual(group.stop(), first)
                kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
