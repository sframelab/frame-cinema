"""Actual XRender capture fixture. Private display, synthetic pixels, no accounts."""
from pathlib import Path
import ctypes as C
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parent
display_process = None
if '--display' not in sys.argv:
    reader, writer = os.pipe()
    display_process = subprocess.Popen(['Xvfb', '-displayfd', str(writer), '-screen', '0',
        '1920x1080x24', '-nolisten', 'tcp'], pass_fds=(writer,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(writer)
    with os.fdopen(reader) as stream:
        os.environ['DISPLAY'] = ':' + stream.readline().strip()

x = C.CDLL('libX11.so.6')
def bind(name, restype, args):
    fn = getattr(x, name); fn.restype = restype; fn.argtypes = args; return fn
D, U, I = C.c_void_p, C.c_ulong, C.c_int
bind('XOpenDisplay', D, [C.c_char_p])
bind('XDefaultRootWindow', U, [D])
bind('XCreateSimpleWindow', U, [D,U,I,I,C.c_uint,C.c_uint,C.c_uint,U,U])
bind('XCreateGC', D, [D,U,U,D])
bind('XMapWindow', I, [D,U]); bind('XUnmapWindow', I, [D,U])
bind('XDestroyWindow', I, [D,U]); bind('XResizeWindow', I, [D,U,C.c_uint,C.c_uint])
bind('XSetForeground', I, [D,D,U]); bind('XFillRectangle', I, [D,U,D,I,I,C.c_uint,C.c_uint])
bind('XSync', I, [D,I]); bind('XCloseDisplay', I, [D]); bind('XFreeGC', I, [D,D])
d = x.XOpenDisplay(None)
assert d, 'No private X display'
window = x.XCreateSimpleWindow(d, x.XDefaultRootWindow(d), 0, 0, 1920, 1080, 0, 0, 0)
gc = x.XCreateGC(d, window, 0, None)
x.XMapWindow(d, window); x.XSync(d, 0)
process = None
checks = []; costs = []; last = 0
def check(ok, name):
    assert ok, name
    checks.append(name); print('PASS ' + name, flush=True)

try:
    with tempfile.TemporaryDirectory(prefix='cinema-ambient-', dir=root) as folder:
        folder = Path(folder)
        env = dict(os.environ, FRAME_CINEMA_IPC=str(folder), FRAME_CINEMA_SESSION='fixture', FRAME_CINEMA_SOURCE_SESSION='source')
        def control(on=True, timestamp=None):
            tmp = folder/'ambient-control.tmp'
            tmp.write_text(f'FCAC1 fixture {time.time() if timestamp is None else timestamp:.6f} {int(on)}')
            tmp.replace(folder/'ambient-control.txt')
        def start():
            return subprocess.Popen([str(root/'ambient_sampler'), str(window), str(os.getpid())], env=env)
        def paint(color, left=0, top=0, width=1920, height=1080):
            x.XSetForeground(d, gc, color); x.XFillRectangle(d, window, gc, left, top, width, height); x.XSync(d, 0)
        def read(predicate, refresh=True):
            global last
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if refresh: control()
                try: value = json.loads((folder/'ambient-status.json').read_text())
                except (OSError, ValueError): value = {}
                if value.get('sequence', 0) > last and predicate(value):
                    assert -.01 <= time.time()-value['updated'] <= .5, 'wire timestamp fails the actual scene freshness window'
                    last = value['sequence']; costs.append(value['sample_ms']); return value
                time.sleep(.03)
            raise AssertionError('Sampler did not produce the expected new palette')
        control(); paint(0xFF0000); process = start()
        value = read(lambda p: p.get('available') and all(c[0] > .95 and max(c[1:]) < .01 for c in p['colors']))
        check(len(value['colors'])==256 and value['crop'] == [0,0,384,216], 'real XRender capture reads red window without invented bars')
        paint(0x0000FF, 960, 0, 960, 1080)
        read(lambda p: p.get('available') and p['colors'][0][0] > .9 and p['colors'][63][2] > .9 and p['colors'][128][2] > .9 and p['colors'][191][0] > .9)
        check(True, 'actual capture preserves clockwise edge orientation')
        paint(0x0000FF); paint(0xFF0000,0,0,1920,216)
        value=read(lambda p:p.get('available') and p['colors'][32][0]>.97 and p['colors'][32][2]<.01 and p['colors'][160][2]>.97)
        check(value.get('analysis')=='edge-gradient-v4' and value.get('edge_fraction')==.05,'real capture identifies the 5% active-picture edge sampler')
        paint(0x0000FF)
        paint(0xFF0000,0,0,1920,54)
        value=read(lambda p:p.get('available') and p['colors'][32][0]>.97 and p['colors'][32][2]<.015)
        check(value['colors'][160][2]>.99,'5% red top edge rejects blue interior through real XRender reduction')
        paint(0x202020)
        paint(0xFFFFFF,116,65,1688,950)
        value=read(lambda p:p.get('available') and all(.012<c[0]<.018 for c in p['colors']))
        check(all(abs(c[0]-c[1])<.001 and abs(c[1]-c[2])<.001 for c in value['colors']),
              'bright interior 6% inward does not brighten neutral edges through capture')
        paint(0);paint(0xFF0000,960,0,8,216)
        read(lambda p:p.get('available') and .34<p['colors'][32][0]<.60 and max(p['colors'][32][1:])<.01)
        check(True,'real filtered capture retains bounded vivid color amongst dark pixels')
        paint(0xFF5209);paint(0xFFFFFF,640,100,640,40)
        read(lambda p:p.get('available') and p['colors'][32][0]>.95 and p['colors'][32][1]<.17 and p['colors'][32][2]<.1)
        check(True,'real capture keeps colored edge recognizable under a white caption stripe')
        paint(0); paint(0x00FF00, 0, 160, 1920, 760)
        value = read(lambda p: p.get('available') and p['crop'][1] >= 7 and all(c[1] > .9 for c in p['colors']))
        check(value['crop'][3] <= 154, 'actual letterboxing samples active picture edges')
        check(.13 < value['fit_top'] < .16 and value['viewport']==[1920,1080] and value['window']==window, 'picture bounds include the exact sampled window and viewport identity')
        check(abs(value['fit_top']*1080-159)<.01, 'source refinement retains just one source row at each 160-pixel bar')
        check(value['fit_known'] and value['fit_safe_top']==value['fit_top'], 'positive picture acquisition is bounded by measured safe rows')
        established=value['crop']
        paint(0xFFFFFF,640,1000,640,20)
        for _ in range(7):
            value=read(lambda p:p.get('available'))
            assert value['crop']==established and value['colors'][32][1]>.9 and value['colors'][160][1]>.9, 'caption toggled established crop'
        check(True,'subtitle crossing a black bar preserves captured picture-edge brightness over time')
        check(value['fit_top']==0, 'display cropping releases captions while ambient crop retains the correct colors')
        check(not value['fit_known'] and value['fit_safe_top']<159/1080, 'caption restores the picture through an explicit unsafe bound')
        for phase in range(5):
            paint(0);paint(0x00FF00,0,160,1920,760);paint(0xFFFFFF,640,1000+phase,640,1)
            read(lambda p:p.get('available') and p['fit_top']==0)
        check(True,'one-pixel white strokes in bars prevent display cropping through five reduction phases')
        paint(0);paint(0x00FF00,0,140,1920,801)
        value=read(lambda p:p.get('available') and abs(p['fit_top']*1080-138)<.01)
        check(True,'asymmetric 140/139-pixel source bars leave only 2/1 pixels with both picture edges intact')
        paint(0);paint(0x00FF00,900,140,120,801)
        value=read(lambda p:p.get('available') and not p['fit_known'] and abs(p['fit_safe_top']*1080-138)<.01)
        check(value['fit_top']==0 and not value['fit_dark'], 'sparse dark title retains exact safe bars without permitting acquisition')
        paint(0xFFFFFF,640,1010,640,1)
        value=read(lambda p:p.get('available') and not p['fit_known'] and p['fit_safe_top']<138/1080)
        check(value['fit_top']==0, 'caption in a sparse dark scene immediately lowers the safe bound')
        paint(0)
        value=read(lambda p:p.get('available') and p['fit_dark'])
        check(not value['fit_known'] and value['fit_top']==0 and value['fit_safe_top']==.20, 'fully black frame can retain a known shape but cannot acquire one')
        paint(0x00FF00)
        value=read(lambda p:p.get('available') and not p['fit_dark'] and p['fit_safe_top']==0)
        check(value['fit_top']==0 and not value['fit_known'], 'real full-height content releases retained bars after dark frames')
        for phase in range(4):
            for column in range(1920):
                x.XSetForeground(d, gc, 0xFFFFFF if (column+phase)%4 < 2 else 0)
                x.XFillRectangle(d, window, gc, column, 0, 1, 1080)
            x.XSync(d,0)
            read(lambda p: p.get('available') and all(.18 < c[0] < .25 for c in p['colors']))
        check(True, 'fine stripes retain a stable average across four pixel phases')
        x.XResizeWindow(d, window, 960, 540); x.XSync(d, 0); paint(0x808080, 0, 0, 960, 540)
        read(lambda p: p.get('available') and all(.20 < c[0] < .23 and abs(c[0]-c[2]) < .001 for c in p['colors']))
        check(True, 'resize updates sampling transform and linear-light gray')
        process.kill(); process.wait(timeout=3); process = start()
        read(lambda p: p.get('available'))
        check(True, 'replacement worker produces a newer sequence for the same source')
        for _ in range(16): read(lambda p: p.get('available'))
        control(False)
        read(lambda p: not p.get('available'), refresh=False)
        check(True, 'Off stops image sampling')
        control(timestamp=time.time()-3)
        read(lambda p: not p.get('available'), refresh=False)
        check(True, 'stale enable command does not sample')
        control(); paint(0,0,0,960,540)
        read(lambda p: p.get('available') and max(max(c) for c in p['colors']) == 0)
        check(True, 'black picture publishes black instead of retained color')
        process.terminate(); process.wait(timeout=3); process = None
        control()
        subprocess.run([str(root/'test_ambient_worker'), str(window)],env=env,check=True,timeout=10)
        (folder/'ambient-status.json').unlink(missing_ok=True)
        process = start()
        read(lambda p: p.get('available'))
        x.XUnmapWindow(d, window); x.XSync(d, 0)
        read(lambda p: not p.get('available'))
        check(True, 'hidden window becomes unavailable')
        x.XDestroyWindow(d, window); window=0; x.XSync(d, 0)
        read(lambda p: not p.get('available'))
        check(True, 'destroyed window fails closed without crashing')
        print(json.dumps({'checks':len(checks), 'sample_ms_median':statistics.median(costs),
            'sample_ms_p95':sorted(costs)[int(.95*(len(costs)-1))], 'display_mode':'existing private display' if '--display' in sys.argv else 'Xvfb'}))
finally:
    if process is not None:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
    x.XFreeGC(d,gc)
    if window: x.XDestroyWindow(d, window)
    x.XCloseDisplay(d)
    if display_process:
        display_process.terminate(); display_process.wait(timeout=3)
