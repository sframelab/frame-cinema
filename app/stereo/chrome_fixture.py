"""Actual H.264 video playback in a disposable Chrome profile; no service access."""
from pathlib import Path
import signal
import sys
import tempfile
import time
import os
import shutil
import http.server
import threading
import functools
import re
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from browser_pipe import BrowserPipe
from video_frame_clock import VideoFrameClock
signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
parent=Path.home()/'.var/app/com.google.Chrome/config'
try:
    with tempfile.TemporaryDirectory(prefix='cinema-stereo-fixture-',dir=parent) as profile:
        path=Path(profile)
        clip=Path(os.environ['FRAME_CINEMA_FIXTURE_VIDEO'])
        shutil.copy2(clip,path/'fixture.mp4')
        (path/'index.html').write_text('<!doctype html><title>CinemaStereoFixture</title><style>html,body{margin:0;background:black;overflow:hidden}video{display:block;width:100vw;height:100vh;object-fit:contain}</style><video muted autoplay loop playsinline src="fixture.mp4"></video>')
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def send_head(self):
                self.remaining=None
                if self.path=='/index.html':return super().send_head()
                if self.path!='/fixture.mp4':self.send_error(404);return None
                # Chrome needs byte ranges for real MP4 seeks. The default
                # SimpleHTTPRequestHandler ignores Range and can reset to zero.
                source=path/'fixture.mp4';size=source.stat().st_size
                header=self.headers.get('Range');start=0;end=size-1
                if header:
                    match=re.fullmatch(r'bytes=(\d+)-(\d*)',header)
                    if not match:self.send_error(416);return None
                    start=int(match[1]);end=min(end,int(match[2]) if match[2] else end)
                    if start>end:self.send_error(416);return None
                self.send_response(206 if header else 200)
                self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes')
                self.send_header('Content-Length',str(end-start+1))
                if header:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.end_headers();f=source.open('rb');f.seek(start);self.remaining=end-start+1;return f
            def copyfile(self,source,output):
                if self.remaining is None:return super().copyfile(source,output)
                try:
                    while self.remaining:
                        chunk=source.read(min(65536,self.remaining))
                        if not chunk:break
                        output.write(chunk);self.remaining-=len(chunk)
                except (BrokenPipeError,ConnectionResetError):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=profile))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        address='http://127.0.0.1:'+str(server.server_address[1])+'/index.html'
        with BrowserPipe(['--no-first-run','--no-default-browser-check','--user-data-dir='+profile,'--ozone-platform=x11','--autoplay-policy=no-user-gesture-required','--kiosk','--app='+address]) as browser:
            clock=VideoFrameClock(Path(os.environ['FRAME_CINEMA_IPC']),os.environ['FRAME_CINEMA_SESSION'],'fixture')
            until=time.monotonic()+float(os.environ.get('FRAME_CINEMA_FIXTURE_SECONDS','25'))+15
            session=None;last=0;attached=0;phase=0;paused_sequence=0
            while browser.process.poll() is None and time.monotonic()<until:
                if session is None:
                    pages=browser.request('Target.getTargets',timeout=12)['targetInfos']
                    selected=[p for p in pages if p['type']=='page' and p.get('url','').startswith(address)]
                    if selected:
                        session=browser.request('Target.attachToTarget',{'targetId':selected[0]['targetId'],'flatten':True})['sessionId']
                        clock.attach(browser,session)
                        attached=time.monotonic()
                        print('fixture_browser_attached',flush=True)
                if session:
                    browser.pump_events()
                    if time.monotonic()-last>.3:
                        clock.install(browser,fixture=True);last=time.monotonic()
                    if os.environ.get('FRAME_CINEMA_FIXTURE_EXERCISE') and clock.last:
                        age=time.monotonic()-attached
                        def evaluate(expression):return browser.request('Runtime.evaluate',{'expression':expression,'returnByValue':True},session=session)
                        if phase==0 and age>3:
                            evaluate("document.querySelector('video').pause()");phase=1
                        elif phase==1 and age>3.5:
                            paused_sequence=clock.last['sequence'];phase=2
                        elif phase==2 and age>4.5:
                            assert clock.last['sequence']==paused_sequence,'Paused callback sequence advanced'
                            evaluate("document.querySelector('video').currentTime=7");phase=3
                        elif phase==3 and age>5.5:
                            assert abs(clock.last['pts']-7)<.1,'Paused seek did not deliver a fresh frame: '+str(clock.last)
                            evaluate("document.querySelector('video').play()");phase=4
                        elif phase==4 and age>6.5:
                            assert not clock.last['paused'] and clock.last['pts']>7.5,'Resume failed'
                            print('fixture_controls_pass pause seek resume',flush=True);phase=5
                time.sleep(.001)
        server.shutdown();server.server_close()
except KeyboardInterrupt:pass
