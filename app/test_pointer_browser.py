"""Private Xvfb/Chrome pointer fixture. Never opens a service profile."""
import ctypes
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from browser_pipe import BrowserPipe

ROOT = Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--mode',choices=['atomic','legacy'],default='atomic')
    args=parser.parse_args()
    reader, writer = os.pipe()
    display = subprocess.Popen(['Xvfb', '-displayfd', str(writer), '-screen', '0',
                                '1920x1080x24', '-nolisten', 'tcp'], pass_fds=(writer,),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(writer)
    with os.fdopen(reader) as stream:
        os.environ['DISPLAY'] = ':' + stream.readline().strip()
    try:
        config = Path.home() / '.var/app/com.google.Chrome/config'
        with tempfile.TemporaryDirectory(prefix='cinema-pointer-test-', dir=config) as profile:
            with BrowserPipe(['--no-first-run', '--no-default-browser-check',
                              '--user-data-dir=' + profile, '--ozone-platform=x11', '--kiosk',
                              '--app=data:text/html,<!doctype html><title>Pointer fixture</title><body></body>']) as browser:
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    pages = [t for t in browser.request('Target.getTargets')['targetInfos']
                             if t['type'] == 'page' and t['url'].startswith('data:')]
                    if pages:
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('Fixture page did not open')
                session = browser.request('Target.attachToTarget',
                                          {'targetId': pages[0]['targetId'], 'flatten': True})['sessionId']

                def evaluate(expression):
                    response = browser.request('Runtime.evaluate',
                                               {'expression': expression, 'returnByValue': True}, session)
                    if 'exceptionDetails' in response:
                        raise RuntimeError('Synthetic fixture evaluation failed')
                    return response['result'].get('value')

                tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
                windows = re.findall(r'(0x[0-9a-f]+).*?"Google-chrome"\)\s+(\d+)x(\d+)', tree)
                window = next(w[0] for w in windows if int(w[1]) > 500)
                x11 = ctypes.CDLL('libX11.so.6')
                x11.XOpenDisplay.restype = ctypes.c_void_p
                x11.XResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_uint]
                x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
                x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
                connection = x11.XOpenDisplay(None)
                x11.XResizeWindow(connection, int(window, 16), 1920, 1080)
                x11.XSync(connection, 0)
                x11.XCloseDisplay(connection)
                time.sleep(.3)
                evaluate('''(()=>{
                    document.body.innerHTML=`<style>body{margin:0}
                    button{position:absolute}#top{left:1550px;top:20px;width:110px;height:50px}
                    #hero{left:300px;top:300px;width:600px;height:400px}
                    #tile{position:absolute;left:1050px;top:850px;width:260px;height:140px;background:blue}
                    #tile:hover{background:red}
                    #tile_action{position:absolute;left:1020px;top:820px;width:320px;height:200px}
                    </style><button id=top>Search</button><button id=hero>Hero</button><div id=tile>Show tile</div>`;
                    window.cinemaFixtureEvents=[];
                    window.cinemaFixtureAccepted=[];
                    let dragged=false;
                    document.addEventListener('mousedown',()=>dragged=false,true);
                    document.addEventListener('mousemove',e=>{if(e.buttons===1)dragged=true},true);
                    document.addEventListener('click',e=>{if(!dragged)cinemaFixtureAccepted.push(e.target.id)},true);
                    document.getElementById('tile').addEventListener('mouseenter',()=>setTimeout(()=>{
                      if(document.getElementById('tile_action'))return;
                      const popup=document.createElement('button');popup.id='tile_action';
                      popup.textContent='Expanded show';document.body.append(popup);
                    },250),{once:true});
                    for(const type of ['mousemove','mousedown','mouseup','click'])
                      document.addEventListener(type,e=>cinemaFixtureEvents.push({type,
                        x:e.clientX,y:e.clientY,detail:e.detail,target:e.target.id,
                        buttons:e.buttons,hover:e.target.matches(':hover'),trusted:e.isTrusted}),true);
                    return true;
                })()''')
                results = []
                driver = os.environ.get('FRAME_CINEMA_POINTER_DRIVER', str(ROOT / 'inspect_panel'))
                for name, x, y in [('top', 1600, 40), ('hero', 600, 500), ('tile_action', 1150, 900), ('top',1600,40)]:
                    for action in ['move', 'click']:
                        subprocess.run([driver, action, window, str(x), str(y)], check=True)
                        time.sleep(.4)
                    events = evaluate('cinemaFixtureEvents.splice(0)')
                    results.append({'target': name, 'events': events,
                                    'hovered_after': evaluate("[...document.querySelectorAll(':hover')].map(e=>e.id)"),
                                    'clicked': any(e['type'] == 'click' and e['target'] == name for e in events),
                                    'tap_accepted': name in evaluate('cinemaFixtureAccepted.splice(0)'),
                                    'held_moves': sum(e['type'] == 'mousemove' and e['buttons'] == 1 for e in events)})
                passed = all(v['clicked'] and v['tap_accepted'] and v['target'] in v['hovered_after'] and v['held_moves']==0 for v in results)
                replays=[]
                if args.replay:
                    gestures=json.loads(args.replay.read_text())['gestures']
                    for gesture in gestures:
                        evaluate('cinemaFixtureEvents=[];cinemaFixtureAccepted=[]')
                        stream=''.join(f'{ms} {kind} {1600+dx} {40+dy}\n' for ms,kind,dx,dy in gesture)
                        subprocess.run([str(ROOT/'test_pointer_replay'),args.mode,window],input=stream,text=True,check=True)
                        deadline=time.monotonic()+2
                        while time.monotonic()<deadline:
                            events=evaluate('cinemaFixtureEvents')
                            if any(e['type']=='mouseup' for e in events):break
                            time.sleep(.01)
                        accepted=evaluate('cinemaFixtureAccepted')
                        replays.append({'duration_ms':gesture[-1][0],
                            'clicks':sum(e['type']=='click' and e['target']=='top' for e in events),
                            'accepted':accepted.count('top'),
                            'held_moves':sum(e['type']=='mousemove' and e['buttons']==1 for e in events),
                            'balanced':sum(e['type']=='mousedown' for e in events)==sum(e['type']=='mouseup' for e in events)==1})
                    passed=passed and all(r['accepted']==1 and r['clicks']==1 and r['held_moves']==0 and r['balanced'] for r in replays)
                print(json.dumps({'viewport': evaluate('[innerWidth,innerHeight]'), 'passed': passed, 'mode':args.mode,'results': results,'recorded_gesture_replays':replays}))
                return 0 if passed else 1
    finally:
        display.terminate()
        display.wait(timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
