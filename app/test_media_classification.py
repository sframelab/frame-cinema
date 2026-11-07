"""Title versus preview classification in disposable Chrome; no provider access."""
import json
from pathlib import Path
import tempfile
from browser_pipe import BrowserPipe
from media_control import evaluate, PREFIX, STATE, HOSTS


def main():
    checks=[]
    config=Path.home()/'.var/app/com.google.Chrome/config'
    with tempfile.TemporaryDirectory(prefix='cinema-classification-',dir=config) as profile:
        with BrowserPipe(['--headless=new','--no-first-run','--no-default-browser-check',
                          '--user-data-dir='+profile,'about:blank']) as browser:
            target=next(t for t in browser.request('Target.getTargets',timeout=12)['targetInfos'] if t['type']=='page')
            session=browser.request('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True})['sessionId']
            browser.request('Runtime.evaluate',{'expression':"document.body.innerHTML='<video style=\"width:320px;height:180px\"></video><input>';const v=document.querySelector('video');Object.defineProperty(v,'videoWidth',{value:1280});Object.defineProperty(v,'videoHeight',{value:534})"},session)
            for host,path,expected in [
                    ('www.netflix.com','/browse',False),('www.netflix.com','/watch/test',True),
                    ('www.netflix.com','/browse?watch=test',False),
                    ('www.disneyplus.com','/',False),('www.disneyplus.com','/search',False),
                    ('www.disneyplus.com','/play/test',True),('www.disneyplus.com','/video/test',True),
                    ('play.hbomax.com','/',False),('play.hbomax.com','/video/watch/test',True),
                    ('play.hbomax.com','/player/test',True),('play.hbomax.com','/watch/test',True),
                    ('play.hbomax.com','/watchlist',False),('play.max.com','/video/watch/test',True)]:
                # Shadow location only within this synthetic evaluation. Production
                # still reads its real location and the real service allowlist.
                script='const location='+json.dumps({'hostname':host,'pathname':path})+';'+PREFIX.replace('DOMAINS',json.dumps(HOSTS))+STATE
                value=evaluate(browser,session,script)
                assert value['title_player'] is expected,(host,path,value)
                assert value['can_control'] is expected,(host,path,value)
                checks.append({'host':host,'path':path,'title_player':expected})
            browser.request('Runtime.evaluate',{'expression':"document.querySelector('input').focus()"},session)
            script='const location={hostname:"www.netflix.com",pathname:"/watch/test"};'+PREFIX.replace('DOMAINS',json.dumps(HOSTS))+STATE
            value=evaluate(browser,session,script)
            assert value['title_player'] and not value['can_control'] and (value['width'],value['height'])==(1280,534)
            checks.append('editing_disables_shortcuts_without_changing_title_quality')
            generation=value['player_generation']
            assert generation and value['current_valid'] and value['error_code']==0 and value['playback_rate']==1
            assert evaluate(browser,session,script)['player_generation']==generation
            checks.append('stable_content_free_identity_and_numeric_health')
            browser.request('Runtime.evaluate',{'expression':"document.querySelector('video').dispatchEvent(new Event('loadstart'))"},session)
            assert evaluate(browser,session,script)['player_generation']!=generation
            checks.append('same_element_new_resource_changes_identity')
            browser.request('Runtime.evaluate',{'expression':"Object.defineProperty(document.querySelector('video'),'currentTime',{get:()=>NaN})"},session)
            invalid=evaluate(browser,session,script)
            assert invalid['current']==0 and invalid['current_valid'] is False
            checks.append('nonfinite_playhead_is_unknown_not_zero')
    print(json.dumps({'passed':len(checks),'checks':checks,'provider_access':False}))


if __name__=='__main__':main()
