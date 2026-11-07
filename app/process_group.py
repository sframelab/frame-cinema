"""Lifecycle of one private Linux process group; never matches by app name."""
import os
from pathlib import Path
import signal
import subprocess
import time


class ProcessGroup:
    def __init__(self, command, **options):
        self._process = subprocess.Popen(command, start_new_session=True, **options)
        self.pid = self._process.pid
        self.returncode = None
        self._closed = False
        self._result = None

    def poll(self):
        if self._closed:
            return self.returncode
        # Keep the leader waitable until its children stop. Reaping it earlier
        # loses the lifetime anchor and permits its numeric PID to be reused.
        status = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if status is not None:
            self.returncode = status.si_status if status.si_code == os.CLD_EXITED else -status.si_status
        return self.returncode

    def _has_live_members(self):
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                # comm may contain spaces or parentheses; fields start after
                # the final ')'. State is field 3 and pgrp is field 5.
                fields = path.read_text().rsplit(')', 1)[1].split()
                if int(fields[2]) == self.pid and fields[0] not in ('Z', 'X'):
                    return True
            except (FileNotFoundError, ProcessLookupError):
                continue
        return False

    def _wait_quiet(self, timeout):
        deadline = time.monotonic() + timeout
        empty_once = False
        while time.monotonic() < deadline:
            alive = self._has_live_members()
            if not alive and empty_once:
                return True
            empty_once = not alive
            time.sleep(0.05)
        return False

    def stop(self, grace=4.0, kill_timeout=2.0):
        if self._closed:
            return self._result
        self.poll()  # Also verifies that this is still our waitable child.
        if os.getpgid(self.pid) != self.pid or os.getsid(self.pid) != self.pid:
            raise RuntimeError('Private process-group ownership changed')
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        forced = not self._wait_quiet(grace)
        if forced:
            os.killpg(self.pid, signal.SIGKILL)
            if not self._wait_quiet(kill_timeout):
                # Keep the unreaped leader and the group handle for a later
                # explicit retry. The caller must not start another source.
                raise TimeoutError('Video processes have not stopped')
        self.returncode = self._process.wait(timeout=1)
        self._closed = True
        self._result = {'complete': True, 'forced': forced}
        return self._result
