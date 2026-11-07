"""Small, fixed page operations. No credentials, titles, URLs or field values returned."""
import json
import time
from urllib.parse import urlparse

HOSTS = ('netflix.com', 'hbomax.com', 'max.com', 'disneyplus.com', 'primevideo.com',
         'amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.co.jp', 'app.plex.tv')
AMAZON_HOSTS = ('amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.co.jp')


def supported_url(url):
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
    except ValueError:
        return False
    if parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None:
        return False
    if host == 'app.plex.tv':
        return parsed.path == '/desktop' or parsed.path.startswith('/desktop/')
    if host.endswith('.app.plex.tv'):
        return False
    if any(host == domain or host.endswith('.' + domain) for domain in AMAZON_HOSTS):
        # Allow the video storefront/player, not Amazon shopping or account pages.
        return parsed.path.startswith(('/gp/video/', '/hz/video/'))
    return any(host == domain or host.endswith('.' + domain) for domain in HOSTS)


PREFIX = r'''const matchesDomain=(host,domain)=>host===domain || host.endsWith('.'+domain);
const amazonDomains=['amazon.com','amazon.co.uk','amazon.de','amazon.co.jp'];
const allowedLocation=loc=>{
 if(loc.hostname && loc.protocol && loc.protocol!=='https:') return false;
 if(loc.hostname==='app.plex.tv') return /^\/desktop(?:\/|$)/.test(loc.pathname);
 if(loc.hostname.endsWith('.app.plex.tv')) return false;
 if(amazonDomains.some(d=>matchesDomain(loc.hostname,d))) return /^\/(gp|hz)\/video\//.test(loc.pathname);
 return DOMAINS.some(d=>matchesDomain(loc.hostname,d));
};
const valid = allowedLocation(location);
if (!valid) return {page_ready:false, video:false};
document.documentElement.style.scrollbarWidth='none';
if(document.body) document.body.style.scrollbarWidth='none';
// Service players may live in open web components or same-origin frames.
// Inspect structure only; never read field values, text or account attributes.
const videos=[];
const roots=[document];
const visible=node=>node.checkVisibility({opacityProperty:true,visibilityProperty:true}) &&
 node.getBoundingClientRect().width>0 && node.getBoundingClientRect().height>0;
for(let index=0;index<roots.length && index<64;index++){
 const root=roots[index];
 videos.push(...[...root.querySelectorAll('video')].filter(visible));
 for(const node of root.querySelectorAll('*')){
  if(node.shadowRoot) roots.push(node.shadowRoot);
  if(node.tagName==='IFRAME' && visible(node)){
   try {
    const frame=node.contentDocument;
    if(frame && allowedLocation(frame.location)) roots.push(frame);
   } catch (_) {}
  }
 }
}
videos.sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height);
const v=videos[0];
const netflix=location.hostname==='netflix.com' || location.hostname.endsWith('.netflix.com');
const netflixPlayer=netflix && location.pathname.startsWith('/watch/');
const disney=location.hostname==='disneyplus.com' || location.hostname.endsWith('.disneyplus.com');
const disneyPlayer=disney && /\/(play|video)(\/|$)/.test(location.pathname);
const hbo=location.hostname==='hbomax.com' || location.hostname.endsWith('.hbomax.com') ||
 location.hostname==='max.com' || location.hostname.endsWith('.max.com');
const hboPlayer=hbo && /^\/(video\/watch|player|watch)(\/|$)/.test(location.pathname);
const prime=matchesDomain(location.hostname,'primevideo.com') ||
 amazonDomains.some(d=>matchesDomain(location.hostname,d));
const plex=location.hostname==='app.plex.tv';
// Prime's player can overlay its detail page; Plex can keep its existing hash
// route during playback. A route alone must never classify an autoplay preview.
// Require a top-document full-size player (or explicit browser fullscreen).
const videoBounds=v?v.getBoundingClientRect():null;
const fullscreenVideo=!!v && !!document.fullscreenElement &&
 (document.fullscreenElement===v || document.fullscreenElement.contains(v));
const fillsViewport=!!v && v.ownerDocument===document &&
 videoBounds.width>=innerWidth*.9 && videoBounds.height>=innerHeight*.9 &&
 Math.abs(videoBounds.left)<=innerWidth*.05 && Math.abs(videoBounds.top)<=innerHeight*.05;
const primeRoute=/(?:^|\/)(detail|watch|player)(?:\/|$)/.test(location.pathname);
const primePlayer=prime && !!v && (fullscreenVideo || (primeRoute && fillsViewport));
// The hosted Plex Web full player was observed on 2026-11-01. Match the
// semantic CSS-module prefix, not its build hash; do not accept mini players.
let plexFullPlayer=false;
if(plex && v){
 for(let node=v.parentElement,depth=0;node && depth<12;node=node.parentElement,depth++){
  if([...node.classList].some(c=>c.startsWith('Player-fullPlayerContainer-'))){
   plexFullPlayer=true; break;
  }
 }
}
const plexPlayer=plex && !!v && (fullscreenVideo || (plexFullPlayer && fillsViewport));
const titlePlayer=netflixPlayer || disneyPlayer || hboPlayer || primePlayer || plexPlayer;
const playerAllowed=titlePlayer;
const editing=(()=>{
 let focused=document.activeElement;
 for(let depth=0;depth<64;depth++){
  if(!focused) return false;
  if(['INPUT','TEXTAREA','SELECT'].includes(focused.tagName) || focused.isContentEditable) return true;
  let next=focused.shadowRoot && focused.shadowRoot.activeElement;
  if(focused.tagName==='IFRAME'){
   try {next=focused.contentDocument && focused.contentDocument.activeElement;} catch (_) {return true;}
   // Do not send player shortcuts into a focused frame we cannot inspect.
   if(!next) return true;
  }
  if(!next) return false;
  focused=next;
 }
 return true;
})();
'''

STATE = '''
// Content-free identity: replace the observation when a video element or its
// media resource changes. Weak keys do not retain retired players. No URL,
// title, field value or account attribute is read or returned.
const identityKey=Symbol.for('frame-cinema.playback-identity.v1');
let identity=globalThis[identityKey];
if(!identity){
 identity={next:0,players:new WeakMap()};
 Object.defineProperty(globalThis,identityKey,{value:identity});
}
let playerGeneration='';
if(v){
 let entry=identity.players.get(v);
 if(!entry){
  entry={generation:++identity.next};
  identity.players.set(v,entry);
  v.addEventListener('loadstart',()=>{entry.generation=++identity.next});
 }
 playerGeneration=String(performance.timeOrigin)+':'+entry.generation;
}
// Fit needs a full-width title video whose box either fills the page or is
// centred with equal page bars above and below: players may letterbox in
// layout instead of inside the element. fit_check names the first failed
// condition (geometry only) so a provider layout change is diagnosable.
const fitBox=v?v.getBoundingClientRect():null;
// The rendered picture inside the element: contain/scale-down letterbox it.
function fitPicture(){
 const box=fitBox;
 const fit=getComputedStyle(v).objectFit;
 if(v.videoWidth>0 && v.videoHeight>0 && (fit==='contain' || fit==='scale-down')){
  let s=Math.min(box.width/v.videoWidth,box.height/v.videoHeight);
  if(fit==='scale-down') s=Math.min(s,1);
  const w=v.videoWidth*s, h=v.videoHeight*s;
  return {left:box.left+(box.width-w)/2, top:box.top+(box.height-h)/2, width:w, height:h};
 }
 return {left:box.left, top:box.top, width:box.width, height:box.height};
}
const fitCheck=(()=>{
 if(!v) return 'no_video';
 if(!titlePlayer) return 'not_player';
 if(editing) return 'editing';
 if(v.ended) return 'ended';
 if(v.readyState<2) return 'not_ready';
 if(v.ownerDocument!==document) return 'frame';
 const fit=getComputedStyle(v).objectFit;
 if(!['contain','fill','cover','scale-down'].includes(fit)) return 'object_fit';
 const p=fitPicture();
 if(p.left>1 || Math.abs(p.width-innerWidth)>2) return 'width';
 const below=innerHeight-(p.top+p.height);
 if(Math.abs(p.top-below)>2) return 'height';
 if(p.top<-2) return 'cropped';
 return '';
})();
return {page_ready:document.readyState!=='loading', video:!!v, title_player:!!v && titlePlayer,
 fit_viewport:[Math.round(innerWidth*devicePixelRatio),Math.round(innerHeight*devicePixelRatio)],
 fit_eligible:fitCheck==='', fit_check:fitCheck,
 fit_box:fitBox?[Math.round(fitBox.left),Math.round(fitBox.top),Math.round(fitBox.width),Math.round(fitBox.height)]:[],
 fit_page:[Math.round(innerWidth),Math.round(innerHeight)], fit_object:v?getComputedStyle(v).objectFit:'',
 fit_picture:v?(p=>[Math.round(p.left),Math.round(p.top),Math.round(p.width),Math.round(p.height)])(fitPicture()):[],
 fullscreen:!!document.fullscreenElement, paused:v?v.paused:true,
 current:v&&Number.isFinite(v.currentTime)?v.currentTime:0,
 current_valid:!!v&&Number.isFinite(v.currentTime), player_generation:playerGeneration,
 seeking:v?v.seeking:false, playback_rate:v&&Number.isFinite(v.playbackRate)?v.playbackRate:0,
 error_code:v&&v.error?v.error.code:0,
 duration:v&&Number.isFinite(v.duration)?v.duration:0,
 can_control:!!v && playerAllowed && !editing,
 can_seek:!!v && v.seekable.length>0 && playerAllowed && !editing,
 width:v?v.videoWidth:0, height:v?v.videoHeight:0,
 ready_state:v?v.readyState:0, ended:v?v.ended:false};
'''

OPERATIONS = {
    'browser_back': None,
    'browser_reload': None,
    'toggle_play': "if(!v) return {ok:false,reason:'no_video'}; if(v.paused) await v.play(); else v.pause(); return {ok:true};",
    'back_10': "if(!v || !v.seekable.length) return {ok:false,reason:'not_seekable'}; v.currentTime=Math.max(v.seekable.start(0),v.currentTime-10); return {ok:true};",
    'forward_10': "if(!v || !v.seekable.length) return {ok:false,reason:'not_seekable'}; v.currentTime=Math.min(v.seekable.end(v.seekable.length-1),v.currentTime+10); return {ok:true};",
    'exit_fullscreen': "if(document.fullscreenElement) await document.exitFullscreen(); return {ok:!document.fullscreenElement};",
}


def evaluate(browser, session, script):
    response = browser.request('Runtime.evaluate', {
        'expression': '(async()=>{' + script + '})()', 'returnByValue': True,
        'awaitPromise': True, 'userGesture': True, 'timeout': 2500}, session)
    if 'exceptionDetails' in response:
        raise RuntimeError('Page media operation failed')
    return response.get('result', {}).get('value', {})


def operation(browser, session, name):
    if name not in OPERATIONS:
        raise ValueError('Unknown media command')
    if name in ('browser_back', 'browser_reload'):
        history = browser.request('Page.getNavigationHistory', session=session)
        entries, index = history['entries'], history['currentIndex']
        if not entries or not supported_url(entries[index]['url']):
            return {'ok': False, 'reason': 'unavailable'}
        if name == 'browser_reload':
            browser.request('Page.reload', session=session)
            return {'ok': True}
        if index <= 0 or not supported_url(entries[index - 1]['url']):
            return {'ok': False, 'reason': 'no_history'}
        previous = entries[index - 1]['id']
        browser.request('Page.navigateToHistoryEntry', {'entryId': previous}, session)
        # Await the history transition so two quick Back actions cannot both
        # select the same entry. Never publish history URLs or page titles.
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            current = browser.request('Page.getNavigationHistory', session=session)
            if current['entries'][current['currentIndex']]['id'] == previous:
                return {'ok': True}
            time.sleep(.025)
        return {'ok': False, 'reason': 'unavailable'}
    prefix = PREFIX.replace('DOMAINS', json.dumps(HOSTS))
    if name in ('toggle_play', 'back_10', 'forward_10'):
        # Validate and operate against one DOM snapshot. Native UI can be stale
        # after a field receives focus, so enforce these guards at dispatch too.
        route = evaluate(browser, session, prefix + '''
if(editing) return {ok:false,reason:'editor_focused'};
if(!v || !playerAllowed) return {ok:false,reason:'no_video'};
if(disney){
 const bounds=v.getBoundingClientRect();
 return {shortcut:true, wake_pointer:{x:bounds.x+bounds.width/2,y:bounds.y+bounds.height/2}};
}
// Prime documents these same Space / left / right shortcuts (10-second seek).
// Let the provider own its MSE playhead, as with Netflix and Disney.
if(netflix || prime) return {shortcut:true};
''' + OPERATIONS[name])
        if route.get('shortcut') is True:
            if route.get('wake_pointer'):
                # Wake Disney's player controls before using its documented
                # shortcuts. Its MSE element is not the provider's playhead.
                browser.request('Input.dispatchMouseEvent', dict(type='mouseMoved', **route['wake_pointer']), session)
            key, code, number = {'toggle_play': (' ', 'Space', 32), 'back_10': ('ArrowLeft', 'ArrowLeft', 37),
                                 'forward_10': ('ArrowRight', 'ArrowRight', 39)}[name]
            # Provider shortcuts preserve player state and MSE buffers.
            # Direct currentTime changes failed in real service playback.
            for kind in ['keyDown', 'keyUp']:
                browser.request('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code,
                                                         'windowsVirtualKeyCode': number}, session)
            return {'ok': True}
        return route
    return evaluate(browser, session, prefix + OPERATIONS[name])


def state(browser, session):
    return evaluate(browser, session, PREFIX.replace('DOMAINS', json.dumps(HOSTS)) + STATE)
