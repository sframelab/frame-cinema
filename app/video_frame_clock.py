"""Content-free source-frame notifications over the existing private browser pipe."""
import json
import math
import os
import re
import time
from media_control import PREFIX, HOSTS

BINDING = '__frameCinemaVideoFrame'
INSTALL = r'''
const key=Symbol.for('frame-cinema.frame-clock.v1');
let clock=globalThis[key];
if(!clock){clock={video:null,generation:0,sequence:0,handle:0,last:null};globalThis[key]=clock;}
if(clock.video!==v){
 if(clock.video&&clock.handle)clock.video.cancelVideoFrameCallback(clock.handle);
 if(clock.handlers)clock.handlers.abort();clock.handlers=new AbortController();
 clock.video=v||null;clock.generation++;clock.sequence=0;clock.last=null;
 const reset=()=>{if(clock.video===v){v.cancelVideoFrameCallback(clock.handle);clock.video=null;clock.last=null;}};
 if(v){
  v.addEventListener('loadstart',reset,{once:true,signal:clock.handlers.signal});
  v.addEventListener('seeked',()=>{
   // A playing loop/seek keeps its rVFC subscription, so no frames are lost
   // waiting for the slower player-discovery poll. Paused seeks may need an
   // explicit notification after the new picture has had two paint turns.
   if(!v.paused)return;
   requestAnimationFrame(()=>requestAnimationFrame(()=>{
    if(clock.video!==v||!v.paused||v.seeking||v.readyState<2)return;
    if(clock.last&&Math.abs(clock.last.pts-v.currentTime)<.05)return;
    clock.sequence++;clock.last={generation:String(v.ownerDocument.defaultView.performance.timeOrigin)+':'+clock.generation,sequence:clock.sequence,
     presented:Math.max(1,v.getVideoPlaybackQuality().totalVideoFrames),pts:v.currentTime,expected:Date.now()/1000,paused:true,seeking:false};
    globalThis.__frameCinemaVideoFrame(JSON.stringify(clock.last));
   }));
  },{signal:clock.handlers.signal});
  v.addEventListener('pause',()=>{if(clock.video===v&&clock.last)globalThis.__frameCinemaVideoFrame(JSON.stringify({...clock.last,paused:true,seeking:v.seeking}));},{signal:clock.handlers.signal});
 }
 if(v&&v.requestVideoFrameCallback){
  const video=v, generation=clock.generation;
  const origin=video.ownerDocument.defaultView.performance.timeOrigin;
  const frame=(now,metadata)=>{
   if(clock.video!==video||clock.generation!==generation)return;
   clock.sequence++;
   clock.last={generation:String(origin)+':'+generation,sequence:clock.sequence,
    presented:metadata.presentedFrames,pts:metadata.mediaTime,
    expected:(origin+metadata.expectedDisplayTime)/1000,
    paused:video.paused,seeking:video.seeking};
   globalThis.__frameCinemaVideoFrame(JSON.stringify(clock.last));
   clock.handle=video.requestVideoFrameCallback(frame);
  };
  clock.handle=video.requestVideoFrameCallback(frame);
 }
}
if(v&&v.paused&&v.readyState>=2&&!clock.last){clock.sequence++;clock.last={generation:String(performance.timeOrigin)+':'+clock.generation,sequence:clock.sequence,presented:Math.max(1,v.getVideoPlaybackQuality().totalVideoFrames),pts:v.currentTime,expected:Date.now()/1000,paused:true,seeking:v.seeking};}
if(clock.last){globalThis.__frameCinemaVideoFrame(JSON.stringify({...clock.last,paused:!!v&&v.paused,seeking:!!v&&v.seeking}));}
return {installed:!!v&&!!v.requestVideoFrameCallback};
'''

class VideoFrameClock:
    def __init__(self, runtime, scene=None, source=None):
        self.runtime=runtime
        self.scene=scene if scene is not None else os.environ.get('FRAME_CINEMA_SESSION','')
        self.source=source if source is not None else os.environ.get('FRAME_CINEMA_SOURCE_SESSION','')
        self.session=None
        self.last=None

    def attach(self, browser, session):
        self.session=session
        browser.event_handler=self.event
        browser.request('Runtime.enable',session=session)
        browser.request('Runtime.addBinding',{'name':BINDING},session=session)

    def install(self, browser, fixture=False):
        prefix="const v=document.querySelector('video');" if fixture else 'const DOMAINS='+json.dumps(HOSTS)+';'+PREFIX
        browser.request('Runtime.evaluate',{'expression':'(()=>{'+prefix+INSTALL+'})()', 'returnByValue':True},session=self.session,timeout=2)

    def event(self, event):
        if event.get('sessionId')!=self.session or event.get('method')!='Runtime.bindingCalled':return
        params=event.get('params',{})
        if params.get('name')!=BINDING:return
        raw=params.get('payload','')
        if not isinstance(raw,str) or len(raw)>1024:return
        try:
            v=json.loads(raw)
            if not re.fullmatch(r'[0-9.:]{1,80}',v['generation']):return
            for key in ['sequence','presented']:
                if type(v[key]) is not int or not 0<v[key]<2**53:return
            for key in ['pts','expected']:
                if type(v[key]) not in [float,int] or not math.isfinite(v[key]) or v[key]<0:return
            if type(v['paused']) is not bool or type(v['seeking']) is not bool:return
            now=time.time()
            # Paused video retains its last frame. Live notifications must be current.
            if not v['paused'] and abs(now-v['expected'])>1:return
            if self.last and v['generation']==self.last['generation'] and v['sequence']<self.last['sequence']:return
            self.last=v
            packet=f"FCVF1 {self.scene} {self.source} {now:.9f} {v['generation']} {v['sequence']} {v['presented']} {v['pts']:.9f} {v['expected']:.9f} {int(v['paused'])} {int(v['seeking'])}\n"
            path=self.runtime/'video-frame.tmp';path.write_text(packet);path.replace(self.runtime/'video-frame.txt')
        except (ValueError,KeyError,TypeError,OSError):return
