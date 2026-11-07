"""Only the new optional reflection output: actual XRender, synthetic window."""
from pathlib import Path
import ctypes as C,json,os,subprocess,tempfile,time
ROOT=Path(__file__).resolve().parent
r,w=os.pipe()
display=subprocess.Popen(['Xvfb','-displayfd',str(w),'-screen','0','960x540x24','-nolisten','tcp'],pass_fds=(w,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
os.close(w)
with os.fdopen(r) as stream:os.environ['DISPLAY']=':'+stream.readline().strip()
x=C.CDLL('libX11.so.6');D,U,I=C.c_void_p,C.c_ulong,C.c_int
def bind(name,result,args):
    f=getattr(x,name);f.restype=result;f.argtypes=args;return f
bind('XOpenDisplay',D,[C.c_char_p]);bind('XDefaultRootWindow',U,[D])
bind('XCreateSimpleWindow',U,[D,U,I,I,C.c_uint,C.c_uint,C.c_uint,U,U]);bind('XCreateGC',D,[D,U,U,D])
bind('XMapWindow',I,[D,U]);bind('XSetForeground',I,[D,D,U]);bind('XFillRectangle',I,[D,U,D,I,I,C.c_uint,C.c_uint]);bind('XSync',I,[D,I]);bind('XCloseDisplay',I,[D])
d=x.XOpenDisplay(None);assert d
window=x.XCreateSimpleWindow(d,x.XDefaultRootWindow(d),0,0,960,540,0,0,0);gc=x.XCreateGC(d,window,0,None);x.XMapWindow(d,window)
process=None
try:
    with tempfile.TemporaryDirectory(prefix='cinema-alpine-check-',dir='/run/user/1000') as temp:
        folder=Path(temp);frame=folder/'reflection-frame.bin'
        def control(reflect,stamp=None):
            (folder/'ambient-control.tmp').write_text(f'FCAC1 test {time.time() if stamp is None else stamp:.6f} 1 {reflect}')
            (folder/'ambient-control.tmp').replace(folder/'ambient-control.txt')
        def wait(predicate):
            end=time.monotonic()+3
            while time.monotonic()<end:
                if predicate():return
                time.sleep(.025)
            raise AssertionError('reflection did not reach expected state')
        x.XSetForeground(d,gc,0xff0000);x.XFillRectangle(d,window,gc,0,0,480,540)
        x.XSetForeground(d,gc,0x0000ff);x.XFillRectangle(d,window,gc,480,0,480,540);x.XSync(d,0)
        control(1)
        process=subprocess.Popen([str(ROOT/'project/ambient_sampler'),str(window),str(os.getpid())],env=dict(os.environ,FRAME_CINEMA_IPC=temp,FRAME_CINEMA_SESSION='test',FRAME_CINEMA_SOURCE_SESSION='synthetic'))
        wait(frame.exists)
        header,pixels=frame.read_bytes().split(b'\n',1);packet=json.loads(header)
        assert packet['session']=='test' and packet['source']=='synthetic' and packet['viewport']==[960,540] and packet['window']==window
        chain,w,h=0,64,36
        while True:
            chain+=w*h*4
            if w==1 and h==1:break
            w,h=max(1,w//2),max(1,h//2)
        assert packet['mipmaps'] and len(pixels)==chain and 0<=time.time()-packet['updated']<.25
        assert pixels[(18*64+5)*4:(18*64+5)*4+4]==bytes([255,0,0,255])
        assert pixels[(18*64+58)*4:(18*64+58)*4+4]==bytes([0,0,255,255])
        control(0);wait(lambda:not frame.exists())
        assert json.loads((folder/'ambient-status.json').read_text())['available']
        control(1);wait(frame.exists)
        control(1,time.time()-3);wait(lambda:not frame.exists())
        print('PASS reflection RGBA/identity/orientation; disabled and stale output removed; palette retained',flush=True)
finally:
    if process:
        process.terminate();process.wait(timeout=5)
    x.XCloseDisplay(d);display.terminate();display.wait(timeout=5)
