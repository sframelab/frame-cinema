"""Owned Chrome DevTools transport over private FIFOs; no TCP listener or protocol logs."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time


class BrowserPipe:
    def __init__(self, arguments):
        self.root = Path.home() / '.var/app/com.google.Chrome/config/frame-cinema-control'
        # Flatpak makes ~/.var/app/com.google.Chrome only when Chrome first runs, so on
        # a headset where Chrome was never opened the parents do not exist yet.
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.directory = Path(tempfile.mkdtemp(prefix='session-', dir=self.root))
        self.reader = None
        self.writer = None
        self.process = None
        self.sequence = 0
        self.buffer = b''
        self.discarding = False
        self.pending = {}
        self.incoming = self.directory / 'to-browser'
        self.outgoing = self.directory / 'from-browser'
        try:
            self._start(arguments)
        except BaseException:
            self.close()
            raise

    def _start(self, arguments):
        for path in [self.incoming, self.outgoing]:
            os.mkfifo(path, 0o600)
        self.writer = os.open(self.incoming, os.O_RDWR | os.O_NONBLOCK)
        self.reader = os.open(self.outgoing, os.O_RDWR | os.O_NONBLOCK)
        # Open the inherited descriptors INSIDE Flatpak, which otherwise closes them.
        script = 'exec 3<"$1"; exec 4>"$2"; shift 2; exec /app/bin/chrome "$@"'
        self.process = subprocess.Popen([
            'flatpak', 'run', '--arch=aarch64', '--env=ACCESSIBILITY_ENABLED=1', '--env=NO_AT_BRIDGE=0',
            '--command=sh', 'com.google.Chrome', '-c', script, 'cinema-browser',
            str(self.incoming), str(self.outgoing), '--remote-debugging-pipe', *arguments],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def begin_request(self, method, params=None, session=None, timeout=4,
                      max_response_bytes=4 * 1024 * 1024):
        if len(self.pending) >= 4:
            raise RuntimeError('Browser control backpressure')
        self.sequence += 1
        packet = {'id': self.sequence, 'method': method, 'params': params or {}}
        if session:
            packet['sessionId'] = session
        data = json.dumps(packet).encode() + b'\0'
        deadline = time.monotonic() + timeout
        while data:
            if not select.select([], [self.writer], [], max(0, deadline-time.monotonic()))[1]:
                raise TimeoutError('Browser control write timed out')
            data = data[os.write(self.writer, data):]
        self.pending[self.sequence] = {'deadline': deadline, 'limit': max_response_bytes,
                                      'response': None}
        return self.sequence

    def abandon(self, request_id):
        # A submitted wheel may already have happened. Drop its late reply,
        # never retry or carry its distance into a new gesture.
        self.pending.pop(request_id, None)

    def poll_response(self, request_id, wait=0):
        entry = self.pending[request_id]
        deadline = min(entry['deadline'], time.monotonic()+wait)
        while True:
            while b'\0' in self.buffer:
                message, self.buffer = self.buffer.split(b'\0', 1)
                if len(message) > 16 * 1024 * 1024:
                    raise RuntimeError('Unexpectedly large browser control response')
                if not message:
                    continue
                response = json.loads(message)
                if 'method' in response and getattr(self, 'event_handler', None): self.event_handler(response)
                destination = self.pending.get(response.get('id'))
                if destination is not None:
                    if len(message) > destination['limit']:
                        destination['response'] = {'error': 'response too large'}
                    else:
                        destination['response'] = response
            response = entry['response']
            if response is not None:
                self.abandon(request_id)
                if 'error' in response:
                    raise RuntimeError('Browser control operation rejected')
                return response.get('result', {})
            if time.monotonic() >= entry['deadline']:
                self.abandon(request_id)
                raise TimeoutError('Browser control response timed out')
            if self.process.poll() is not None:
                raise RuntimeError('Owned browser exited')
            if select.select([self.reader], [], [], max(0, deadline-time.monotonic()))[0]:
                chunk = os.read(self.reader, 65536)
                if self.discarding:
                    if b'\0' not in chunk:
                        continue
                    _, self.buffer = chunk.split(b'\0', 1)
                    self.discarding = False
                    raise RuntimeError('Unexpectedly large browser control response')
                self.buffer += chunk
                if len(self.buffer) > 16 * 1024 * 1024 and b'\0' not in self.buffer:
                    # Drain this packet before accepting another response. The
                    # state survives timeout so a late packet cannot poison it.
                    self.buffer = b''
                    self.discarding = True
            else:
                return None

    def request(self, method, params=None, session=None, timeout=4, max_response_bytes=4 * 1024 * 1024):
        request_id = self.begin_request(method, params, session, timeout, max_response_bytes)
        try:
            response = self.poll_response(request_id, wait=timeout)
            if response is None:
                raise TimeoutError('Browser control response timed out')
            return response
        finally:
            self.abandon(request_id)

    def pump_events(self):
        # Same owner/reader as request(). Never create a competing pipe reader.
        while select.select([self.reader], [], [], 0)[0]:
            chunk = os.read(self.reader, 65536)
            if not chunk: break
            if self.discarding:
                if b'\0' not in chunk: continue
                _, chunk = chunk.split(b'\0', 1)
                self.discarding = False
            self.buffer += chunk
            if len(self.buffer) > 16 * 1024 * 1024 and b'\0' not in self.buffer:
                self.buffer = b''
                self.discarding = True
                raise RuntimeError('Unexpectedly large browser event')
        while b'\0' in self.buffer:
            packet, self.buffer = self.buffer.split(b'\0', 1)
            if not packet: continue
            if len(packet) > 16 * 1024 * 1024: raise RuntimeError('Unexpectedly large browser event')
            value = json.loads(packet)
            if 'method' in value and getattr(self, 'event_handler', None): self.event_handler(value)
            # Native scrolling can have an outstanding asynchronous request.
            # Preserve its response while dispatching frame notifications.
            destination = self.pending.get(value.get('id'))
            if destination is not None:
                destination['response'] = value if len(packet) <= destination['limit'] else {'error': 'response too large'}

    def close(self):
        try:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.request('Browser.close', timeout=2)
                except (TimeoutError, RuntimeError, OSError):
                    self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            # Always release the pipes and this session's folder, even if closing Chrome failed.
            for name in ['reader', 'writer']:
                descriptor = getattr(self, name)
                if descriptor is not None:
                    os.close(descriptor)
                    setattr(self, name, None)
            if self.directory.exists() and self.directory.parent == self.root and self.directory.name.startswith('session-'):
                shutil.rmtree(self.directory)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
