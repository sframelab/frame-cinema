// Production page scripts in an offline DOM model. No provider/network access.
// Usage: node test_prime_plex_media.cjs <python executable>
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const vm = require('node:vm');
const scripts = JSON.parse(execFileSync(process.argv[2] || 'python', ['media_fixture_scripts.py'],
  {cwd: __dirname, encoding: 'utf8'}));
let checks = 0;

function fixture(options = {}) {
  const location = new URL(options.url || 'https://www.primevideo.com/detail/fixture');
  const bounds = options.bounds || {left:0, top:0, width:1280, height:720};
  const document = {readyState:'complete', style:{}, documentElement:{style:{}}, body:{style:{}},
    fullscreenElement:null, activeElement: options.editing ? {tagName:'INPUT'} : {tagName:'BODY'}};
  const parent = {classList:options.plexFull ? ['Player-fullPlayerContainer-fixture'] : ['Player-miniPlayer-fixture'],
    parentElement:null};
  const video = {
    tagName:'VIDEO', ownerDocument:document, parentElement:parent, paused:!!options.paused,
    ended:false, currentTime:30, duration:120, playbackRate:1, error:null, readyState:4,
    seeking:false, videoWidth:1920, videoHeight:1080,
    seekable:{length: options.live ? 0 : 1, start:()=>0, end:()=>120},
    getBoundingClientRect:()=>({...bounds, x:bounds.left, y:bounds.top}),
    checkVisibility:()=>!options.hidden, addEventListener:()=>{},
    play:async function(){this.paused=false;}, pause:function(){this.paused=true;}
  };
  document.querySelectorAll = selector => options.noVideo ? [] : [video];
  document.exitFullscreen = async () => {document.fullscreenElement = null;};
  if (options.fullscreen) document.fullscreenElement={contains:node=>node===video};
  const context = vm.createContext({location, document, innerWidth:1280, innerHeight:720,
    devicePixelRatio:1, performance:{timeOrigin:100}, getComputedStyle:()=>({objectFit:'contain'})});
  const run = script => vm.runInContext('(async()=>{'+script+'})()', context);
  return {run, video, document};
}

async function stateCase(options, expected, expectedControl = expected) {
  const f = fixture(options);
  const state = await f.run(scripts.state);
  assert.equal(state.title_player || false, expected);
  assert.equal(state.can_control || false, expectedControl);
  assert.equal(state.can_seek || false, expectedControl && !options.live);
  checks++;
  return {f, state};
}

(async()=>{
  for (const url of ['https://www.primevideo.com/detail/example',
    'https://www.primevideo.com/-/en/detail/example',
    'https://www.amazon.com/gp/video/detail/example',
    'https://www.amazon.co.uk/gp/video/detail/example',
    'https://www.amazon.de/hz/video/detail/example',
    'https://www.amazon.co.jp/gp/video/detail/example']) {
    await stateCase({url}, true);
  }
  await stateCase({url:'https://www.primevideo.com/'}, false);
  await stateCase({url:'https://www.primevideo.com/storefront'}, false);
  await stateCase({bounds:{left:0, top:0, width:1280, height:400}}, false); // detail hero
  await stateCase({bounds:{left:900, top:500, width:320, height:180}}, false); // mini player
  await stateCase({hidden:true}, false);
  await stateCase({noVideo:true}, false);
  await stateCase({url:'https://www.amazon.com/dp/example', fullscreen:true}, false);
  await stateCase({url:'https://www.amazon.com/ap/signin', fullscreen:true}, false);
  await stateCase({url:'https://primevideo.com.evil.test/detail/example', fullscreen:true}, false);
  await stateCase({url:'https://www.primevideo.com/', fullscreen:true}, true); // explicit full player
  await stateCase({editing:true}, true, false);
  await stateCase({live:true}, true);

  // Plex plays over its existing hash route: /#!/ alone is not a title signal.
  for (const hash of ['#!/', '#!/server/fixture/details', '#!/discover', '#!/player']) {
    await stateCase({url:'https://app.plex.tv/desktop/'+hash, plexFull:true}, true);
    await stateCase({url:'https://app.plex.tv/desktop/'+hash}, false);
  }
  await stateCase({url:'https://app.plex.tv/desktop/', plexFull:true,
    bounds:{left:900, top:500, width:320, height:180}}, false);
  await stateCase({url:'https://app.plex.tv/desktop/', fullscreen:true}, true);
  await stateCase({url:'https://app.plex.tv/desktop/', plexFull:true, editing:true}, true, false);
  await stateCase({url:'https://app.plex.tv/desktop/', plexFull:true, live:true}, true);
  await stateCase({url:'https://plex.tv/auth', plexFull:true}, false);
  await stateCase({url:'https://app.plex.tv.evil.test/desktop/', plexFull:true}, false);
  await stateCase({url:'https://evil.app.plex.tv/desktop/', plexFull:true}, false);
  await stateCase({url:'http://app.plex.tv/desktop/', plexFull:true}, false);

  // Existing providers retain their route guards independent of new geometry.
  for (const [url, expected] of [['https://www.netflix.com/browse',false],
      ['https://www.netflix.com/watch/example',true], ['https://www.disneyplus.com/play/example',true],
      ['https://www.disneyplus.com/search',false], ['https://play.hbomax.com/video/watch/example',true]]) {
    await stateCase({url, bounds:{left:0,top:0,width:320,height:180}}, expected);
  }
  for (const name of ['toggle_play','back_10','forward_10']) {
    const prime = fixture();
    assert.equal((await prime.run(scripts.commands[name])).shortcut, true);
    assert.equal(prime.video.currentTime,30);
    const editor = fixture({editing:true});
    assert.equal((await editor.run(scripts.commands[name])).reason,'editor_focused');
    const preview = fixture({url:'https://www.primevideo.com/'});
    assert.equal((await preview.run(scripts.commands[name])).reason,'no_video');
    checks+=3;
  }
  const plex = fixture({url:'https://app.plex.tv/desktop/',plexFull:true,paused:true});
  assert.equal((await plex.run(scripts.commands.toggle_play)).ok,true);
  assert.equal(plex.video.paused,false);
  assert.equal((await plex.run(scripts.commands.forward_10)).ok,true);
  assert.equal(plex.video.currentTime,40);
  assert.equal((await plex.run(scripts.commands.back_10)).ok,true);
  assert.equal(plex.video.currentTime,30);
  const live = fixture({url:'https://app.plex.tv/desktop/',plexFull:true,live:true});
  assert.equal((await live.run(scripts.commands.forward_10)).reason,'not_seekable');
  checks+=4;
  const sensitive = await stateCase({url:'https://app.plex.tv/desktop/?token=private-fixture#!/server/private-id',
    plexFull:true},true);
  assert(!JSON.stringify(sensitive.state).includes('private'));
  assert(!JSON.stringify(sensitive.state).includes('plex.tv'));
  checks++;
  console.log(JSON.stringify({passed:checks,provider_access:false,kind:'offline DOM model'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
