// Real Gamescope/OpenVR integration test. Only a fresh synthetic Chrome profile.
#define main cinema_panel_main
#define FRAME_CINEMA_COMPOSITOR_TEST
#include "panel_host.cpp"
#undef main
#include <sstream>

static int failures=0;
static void check(bool good,const char* label) { std::printf("%s %s\n",good?"PASS":"FAIL",label); std::fflush(stdout); if (!good) ++failures; }
static void delay(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
static std::string title(Display* display,Window window) {
    Atom type=0;int format=0;unsigned long size=0,left=0;unsigned char* data=nullptr;
    XGetWindowProperty(display,window,XInternAtom(display,"_NET_WM_NAME",False),0,128,False,AnyPropertyType,&type,&format,&size,&left,&data);
    const std::string result=data?std::string(reinterpret_cast<char*>(data),size):"";
    if (data) XFree(data);
    return result;
}
static bool wait_title(Display* display,Window window,const std::string& expected,int milliseconds=2000) {
    const auto start=std::chrono::steady_clock::now();
    while (std::chrono::steady_clock::now()-start<std::chrono::milliseconds(milliseconds)) {
        if (title(display,window).find(expected)!=std::string::npos) return true;
        delay(20);
    }
    return false;
}
static std::string status(const std::string& ipc) { std::ifstream input(ipc+"/panel-status.json");return {std::istreambuf_iterator<char>(input),{}}; }
static bool has(const std::string& ipc,const std::string& value) { return status(ipc).find(value)!=std::string::npos; }
static long counter(const std::string& ipc,const std::string& name) {
    const auto data=status(ipc),needle="\""+name+"\":";
    const auto at=data.find(needle);
    if (at==std::string::npos) return -1;
    char* end=nullptr;const auto value=std::strtol(data.c_str()+at+needle.size(),&end,10);
    return end && (*end==',' || *end=='}') ? value : -1;
}
static uint64_t sequence=1;
static bool point(const std::string& ipc,vr::VROverlayHandle_t board,float u,float v,int kind,float metres=2.f,float aspect=540.f/1400.f) {
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
    scene_poses(poses);
    if (!poses[0].bPoseIsValid) return false;
    const auto& hmd=poses[0].mDeviceToAbsoluteTracking;
    vr::HmdMatrix34_t transform{};vr::ETrackingUniverseOrigin space;
    if (vr::VROverlay()->GetOverlayTransformAbsolute(board,&space,&transform)) return false;
    float origin[]={.18f,-.3f,-.2f}, local[]={ (u-.5f)*metres, (.5f-v)*metres*aspect,0};
    float direction[3]{},world_direction[3]{};
    float length=0;
    for (int i=0;i<3;++i) {
        world_direction[i]=transform.m[i][3]-hmd.m[i][3];
        for (int j=0;j<3;++j) world_direction[i]+=transform.m[i][j]*local[j]-hmd.m[i][j]*origin[j];
        length+=world_direction[i]*world_direction[i];
    }
    length=std::sqrt(length);
    for (int i=0;i<3;++i) for (int j=0;j<3;++j) direction[i]+=hmd.m[j][i]*world_direction[j]/length;
    const auto id=++sequence;
    const std::string name=kind==0 || kind==3?"pointer":"input/"+std::to_string(1000000000+id);
    std::ofstream out(ipc+"/"+name+".tmp");
    const auto sent_us=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    out<<kind<<' '<<id<<' '<<origin[0]<<' '<<origin[1]<<' '<<origin[2]<<' '<<direction[0]<<' '<<direction[1]<<' '<<direction[2]<<" 6 "<<sent_us;
    out.close();std::filesystem::rename(ipc+"/"+name+".tmp",ipc+"/"+name+(kind==0 || kind==3?".txt":".evt"));
    return true;
}
int main(int argc,char** argv) {
    if (argc!=3 || std::string(argv[2]).find("cinema-compositor-test-")==std::string::npos) return 2;
    XSetErrorHandler(ignore_x_error);
    const std::string ipc=argv[1],profile="--user-data-dir="+std::string(argv[2]);
    setenv("FRAME_CINEMA_IPC",ipc.c_str(),1);
    auto child=fork();
    if (!child) {
        const char* page="--app=data:text/html,<title>Cinema input fixture</title>"
            "<body style='background:rgb(20,25,35);color:white;font:32px sans-serif'><h1>Frame Cinema input test</h1>"
            "<input id=f style='position:absolute;left:100px;top:100px;font:40px sans-serif;width:700px;height:100px'>"
            "<input id=p type=password style='position:absolute;left:100px;top:350px;font:40px sans-serif;width:700px;height:100px'>"
            "<button id=b style='position:absolute;left:100px;top:500px' onclick=\"document.title='Fixture submitted'\">Submit</button>"
            "<script>let blurred=false;for(const el of[f,p])el.addEventListener('keydown',e=>{if(e.key==='Enter')document.title='Fixture Enter';"
            "if(e.key==='~'){e.preventDefault();setTimeout(()=>{el.style.display='none';document.title='Fixture hidden'},250)}});"
            "document.addEventListener('keydown',e=>{if(['F4','F6','F7'].includes(e.key))e.preventDefault();if(e.key==='F6')setTimeout(()=>{f.remove();document.title='Fixture removed'},250);"
            "if(e.key==='Escape')document.title='Fixture Escape received';"
            "if(e.key==='F4'){setTimeout(()=>{f.remove();document.title='Fixture removed'},250);setTimeout(()=>{p.focus();document.title='Fixture next field'},2000)}"
            "if(e.key==='F7'){document.title='Fixture reloading';setTimeout(()=>location.reload(),250)}});"
            "document.addEventListener('wheel',()=>document.title='Fixture Scroll');"
            "f.addEventListener('input',()=>{document.title=f.value==='abc123@'?'Fixture PASS':f.value==='abc123x@'?'Caret PASS':'Fixture length '+f.value.length;"
            "if(!blurred && f.value==='abc123@'){blurred=true;setTimeout(()=>{f.blur();document.title='Fixture PASS blurred'},30)}});"
            "p.addEventListener('input',()=>document.title=p.value==='abc123@'?'Password PASS':'Password length '+p.value.length);"
            "document.addEventListener('keydown',e=>{if(e.key!=='F8')return;document.body.innerHTML='';document.title='Grid ready';let last=-1,clicks=0;document.addEventListener('wheel',()=>document.title='Grid wheel');"
            "for(let i=0;i<9;i++){const t=document.createElement(i%3===0?'a':i%3===1?'button':'div');t.tabIndex=0;t.setAttribute('role','button');"
            "t.style.cssText='position:absolute;width:150px;height:120px;background:teal;color:white;text-align:center';"
            "t.style.left=((i%3+.5)*innerWidth/3-75)+'px';t.style.top=((Math.floor(i/3)+.5)*innerHeight/3-60)+'px';"
            "t.innerHTML='<span>Profile tile '+i+'</span>';for(const n of ['mouseenter','mousedown','mouseup','click'])"
            "t.addEventListener(n,()=>{if(n==='click'){last=i;clicks++;window.cinemaFixtureClicks=clicks}document.title='Grid '+JSON.stringify({last,clicks,event:n,target:i})});document.body.append(t)}});"
            "document.addEventListener('keydown',e=>{if(e.key!=='F9')return;document.body.innerHTML='<div id=sc style=\"position:absolute;left:100px;top:100px;width:800px;height:600px;overflow:auto\"><div style=\"height:3000px\">Scroll fixture</div></div><button id=fs style=\"position:absolute;left:1100px;top:100px;width:300px;height:120px\">Fullscreen</button>';"
            "sc.onscroll=()=>document.title='Scroll '+sc.scrollTop;fs.onclick=()=>document.documentElement.requestFullscreen();"
            "document.onfullscreenchange=()=>document.title=document.fullscreenElement?'Fullscreen on':'Fullscreen off';"
            "history.replaceState(0,'');history.pushState(1,'');history.pushState(2,'');window.onpopstate=()=>document.title='History '+history.state;document.title='History 2'})</script>";
        // Scripted reload of a top-level data URL can be refused by Chrome.
        // Use an owned temporary file so this test proves real document reload.
        const std::string fixture_path=std::string(argv[2])+"/input-fixture.html";
        std::ofstream(fixture_path)<<page+std::strlen("--app=data:text/html,");
        const std::string fixture_url="--app=file://"+fixture_path;
        const char* args[]={"fixture-panel","flatpak","run","--user","--env=ACCESSIBILITY_ENABLED=1","--env=NO_AT_BRIDGE=0","com.google.Chrome","--no-first-run","--no-default-browser-check",profile.c_str(),"--ozone-platform=x11","--start-maximized","--force-renderer-accessibility",fixture_url.c_str(),nullptr};
        if (std::getenv("FRAME_CINEMA_LATENCY_TEST")) {
            const auto helper=(std::filesystem::absolute(argv[0]).parent_path()/"test_latency_browser.py").string();
            const char* fast[]={"fixture-panel","python3",helper.c_str(),profile.c_str(),fixture_url.c_str(),nullptr};
            _exit(cinema_panel_main(5,const_cast<char**>(fast)));
        }
        _exit(cinema_panel_main(14,const_cast<char**>(args)));
    }
    vr::EVRInitError error{};vr::VR_Init(&error,vr::VRApplication_Background);
    if (error) { kill(child,SIGTERM);return 3; }
    auto* overlays=vr::VROverlay();
    vr::TrackedDevicePose_t raw_poses[vr::k_unMaxTrackedDeviceCount]{};
    vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,raw_poses,vr::k_unMaxTrackedDeviceCount);
    std::printf("Diagnostic physical headset pose valid=%d; test uses fixed pose only when unavailable.\n",int(raw_poses[0].bPoseIsValid));
    auto* display=XOpenDisplay(nullptr);
    if (!display) { check(false,"private X display available");kill(child,SIGTERM);vr::VR_Shutdown();return 3; }
    vr::VROverlayHandle_t board=0,upper=0,highlight=0;
    Window window=0;
    for (int i=0;i<200 && !window;++i) { window=browser_window(display,DefaultRootWindow(display));delay(50); }
    check(window!=0,"synthetic browser window attached on private Gamescope display");
#ifndef FRAME_CINEMA_REAL_DASHBOARD
    std::printf("Running automated compositor fixture with dashboard ownership gate disabled in test binary only.\n");std::fflush(stdout);
#endif
    if (!window) {
        kill(child,SIGTERM);waitpid(child,nullptr,0);XCloseDisplay(display);vr::VR_Shutdown();return 2;
    }
    vr::VROverlayHandle_t screen=0;
    overlays->FindOverlay("frame-lab.cinema.screen",&screen);
    delay(650);
#ifdef FRAME_CINEMA_REAL_DASHBOARD
    std::puts("Running production dashboard ownership: close Steam dashboard to begin.");std::fflush(stdout);
    int closed=0;
    for (int i=0;i<2400 && closed<40;++i) {
        closed=overlays->IsDashboardVisible()?0:closed+1;delay(50);
    }
    check(closed==40,"Steam dashboard stayed closed before production-routing input test");
    if (closed!=40) { kill(child,SIGTERM);waitpid(child,nullptr,0);XCloseDisplay(display);vr::VR_Shutdown();return 2; }
#endif
    XWindowAttributes browser_size{};XGetWindowAttributes(display,window,&browser_size);
    std::printf("Diagnostic browser fixture window dimensions %dx%d\n",browser_size.width,browser_size.height);
    auto browser_click=[&](float x,float y,int hold=65) {
        for (int kind:{0,1,2}) { point(ipc,screen,x/browser_size.width,y/browser_size.height,kind,4.2f,float(browser_size.height)/browser_size.width);delay(kind==1?hold:80); }
    };
    if (std::getenv("FRAME_CINEMA_LATENCY_TEST")) {
        key_symbol(display,XK_F8,window);XSync(display,False);
        check(wait_title(display,window,"Grid ready"),"quick-tap fixture opens in real Chrome");
        int expected=0;
        std::vector<long> acknowledgements;
        for (int hold:{0,8,40}) {
            bool delivered=true;
            for (int i=0;i<20;++i) {
                point(ipc,screen,.5f,.5f,0,4.2f,float(browser_size.height)/browser_size.width);
                point(ipc,screen,.5f,.5f,1,4.2f,float(browser_size.height)/browser_size.width);
                delay(hold);
                const auto released=std::chrono::steady_clock::now();
                point(ipc,screen,.5f,.5f,2,4.2f,float(browser_size.height)/browser_size.width);
                ++expected;
                bool received=false;
                for (int poll=0;poll<200;++poll) {
                    int clicks=0;std::ifstream current(ipc+"/latency-dom.txt");current>>clicks;
                    if (clicks==expected) { received=true;break; }
                    delay(5);
                }
                delivered=delivered && received;
                acknowledgements.push_back(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-released).count());
            }
            const auto label="all 20 browser taps with "+std::to_string(hold)+" ms hold arrive exactly once";
            check(delivered,label.c_str());
        }
        std::sort(acknowledgements.begin(),acknowledgements.end());
        std::printf("Diagnostic release-to-DOM acknowledgement ms median=%ld p95=%ld max=%ld; 5 ms pipe polling and 5 ms observation granularity\n",
                    acknowledgements[30],acknowledgements[56],acknowledgements.back());
        check(acknowledgements[56]<150,"95 percent of quick taps reach the browser within 150 ms of release");
        delay(150);
        check(counter(ipc,"mouse_downs")==60 && counter(ipc,"mouse_ups")==60 && counter(ipc,"mouse_cancels")==0,
              "60 quick taps leave balanced releases without cancellations");
        std::printf("Compositor regression failures: %d\nDiagnostic %s\n",failures,status(ipc).c_str());std::fflush(stdout);
        kill(child,SIGTERM);waitpid(child,nullptr,0);XCloseDisplay(display);vr::VR_Shutdown();
        return failures?1:0;
    }
    if(!std::getenv("FRAME_CINEMA_NAVIGATION_TEST")) {
    for (int kind:{0,1}) { point(ipc,screen,400.f/browser_size.width,180.f/browser_size.height,kind,4.2f,float(browser_size.height)/browser_size.width);delay(80); }
    for (int i=0;i<120 && !has(ipc,"\"keyboard_visible\":true");++i) delay(50);
    check(has(ipc,"\"keyboard_visible\":true"),"real browser ray click automatically opens keyboard without autofocus or test focus setup");
    overlays->FindOverlay("frame-lab.cinema.keyboard",&board);
    point(ipc,board,.2f,.25f,1);delay(50);
    point(ipc,board,.2f,.25f,2);delay(200);
    Window pointer_root=0,pointer_child=0;int rx=0,ry=0,wx=0,wy=0;unsigned buttons=0;
    XQueryPointer(display,window,&pointer_root,&pointer_child,&rx,&ry,&wx,&wy,&buttons);
    check(!(buttons&Button1Mask) && counter(ipc,"keyboard_char_events")==0,"keyboard opening during browser trigger hold ignores duplicate press and release over a key");
    overlays->FindOverlay("frame-lab.cinema.keyboard",&board);
    overlays->FindOverlay("frame-lab.cinema.keyboard.upper",&upper);
    overlays->FindOverlay("frame-lab.cinema.keyboard.highlight",&highlight);
    uint32_t width=0,height=0;
    const auto texture_error=overlays->GetOverlayTextureSize(board,&width,&height);
    check(!texture_error && width==2800 && height==1080 && overlays->IsOverlayVisible(board),"real compositor accepts and shows 2800x1080 keyboard");
    bool stable=true;
    CinemaKeyboard layout;
    for (int i=0;i<150;++i) {
        const auto& k=layout.keys[1+i%(layout.keys.size()-1)];
        stable=point(ipc,board,(k.x+k.w/2)/layout.width,(k.y+k.h/2)/layout.height,0) && stable;
        delay(20);
        stable=stable && overlays->IsOverlayVisible(board);
    }
    delay(550);
    check(stable && counter(ipc,"keyboard_texture_uploads")==2 && counter(ipc,"keyboard_presentations")==1,"150 hover moves keep one visible keyboard with zero texture reuploads");
    check(counter(ipc,"highlight_failures")==0,"hover highlight API calls succeed");
    auto key=[&](const char* name) { for (const auto& k:layout.keys) if (k.normal==name) return k;return layout.keys[0]; };
    auto send=[&](const char* name,int kind) { const auto k=key(name);return point(ipc,board,(k.x+k.w/2)/layout.width,(k.y+k.h/2)/layout.height,kind); };
    auto click=[&](const char* name) { send(name,0);delay(35);send(name,1);delay(45);send(name,2);delay(75); };
    send("a",0);delay(60);
    check(overlays->IsOverlayVisible(highlight),"key hover highlight is actually visible");
    check(title(display,window).find("Cinema input fixture")!=std::string::npos,"fixture begins with an empty untouched input");
    send("a",1);delay(45);
    // Above the keyboard, through the centre of the browser behind it.
    point(ipc,board,.5f,-.2f,0);delay(40);point(ipc,board,.5f,-.2f,4);delay(40);point(ipc,board,.5f,-.2f,2);delay(80);
    check(title(display,window).find("Cinema input fixture")!=std::string::npos,"captured drag and scroll over browser neither type nor scroll");
    send("a",0);send("a",1);delay(40);send("a",3);delay(40);send("a",2);delay(80);
    check(title(display,window).find("Fixture length")==std::string::npos,"tracking-cancel packet releases keyboard capture without typing");
    for (const char* name:{"a","b","c","1","2","3","Shift","2"}) click(name);
    delay(200);
    std::printf("Diagnostic synthetic field title after typing: %s\n",title(display,window).c_str());
    check(title(display,window).find("Fixture PASS")!=std::string::npos,"consecutive letters numbers and shifted punctuation reach real Chrome input");
    check(title(display,window).find("blurred")!=std::string::npos,"synthetic page has deliberately blurred the selected field");
    click("Backspace");delay(150);
    check(title(display,window).find("Fixture length 6")!=std::string::npos,"DOM blur alone: keyboard restores selected field and Backspace removes one character");
    click("2");delay(150);
    check(title(display,window).find("Fixture PASS")!=std::string::npos,"Backspace corrects the synthetic browser field");
    click("Left");click("Shift");click("x");delay(150);
    check(title(display,window).find("Caret PASS")!=std::string::npos,"Left then insertion preserves the caret instead of resetting focus");
    click("Backspace");click("Right");
    browser_click(400,180);click("Backspace");delay(150);
    check(title(display,window).find("Fixture length 6")!=std::string::npos,"clicking the same focused field keeps a valid typing target");
    click("Shift");click("2");
    click("Tab");delay(200);click("Shift");
    for (const char* name:{"a","b","c","1","2","3","Shift","2"}) click(name);
    delay(150);
    check(title(display,window).find("Password PASS")!=std::string::npos,"Tab retargets the keyboard and types into the password field");
    const auto before_hide=title(display,window);
    auto keyboard_command=[&](int id,int command) {
        const auto path=ipc+"/input/"+std::to_string(9000000000ULL+id);
        std::ofstream(path+".tmp")<<id<<' '<<command;
        std::filesystem::rename(path+".tmp",path+".nav");
    };
    const auto chars_before_hide=counter(ipc,"keyboard_char_events");
    const auto clicks_before_hide=counter(ipc,"mouse_downs");
    send("a",0);send("a",1);delay(45);
    keyboard_command(101,5);delay(150);
    send("a",2);delay(650);
    check(!overlays->IsOverlayVisible(board) && !overlays->IsOverlayVisible(upper) && has(ipc,"\"keyboard_visible\":false"),"queued B dismissal closes both real keyboard layers");
    check(counter(ipc,"keyboard_char_events")==chars_before_hide && counter(ipc,"mouse_downs")==clicks_before_hide && has(ipc,"\"has_editor\":true"),"B while a key is held cancels typing and click-through while retaining the editor");
    keyboard_command(102,5);delay(650);
    check(has(ipc,"\"keyboard_visible\":false"),"repeated explicit dismissal cannot reopen a closed keyboard");
    check(title(display,window)==before_hide,"B dismissal does not send Escape or modify the selected browser field");
    key_symbol(display,XK_Escape,window);XSync(display,False);
    check(wait_title(display,window,"Fixture Escape received"),"Escape detection control observes an actual browser key event");
    keyboard_command(103,4);delay(650);
    check(has(ipc,"\"keyboard_visible\":true") && has(ipc,"\"has_editor\":true"),"keyboard can reopen with the same selected editor after B dismissal");
    click("Backspace");delay(150);
    check(title(display,window).find("Password length 6")!=std::string::npos,"reopened keyboard still edits the retained field");
    click("Shift");click("2");delay(150);
    check(title(display,window).find("Password PASS")!=std::string::npos,"reopened keyboard restores synthetic field text correctly");
    XSetInputFocus(display,None,RevertToNone,CurrentTime);XSync(display,False);
    click("Backspace");delay(150);
    check(title(display,window).find("Password length 6")!=std::string::npos,"X focus loss alone: key dispatch restores browser focus and delivers Backspace");
    click("2");delay(150);
    click("Hide");delay(600);
    check(!overlays->IsOverlayVisible(board) && !overlays->IsOverlayVisible(upper) && has(ipc,"\"keyboard_visible\":false"),"Hide stays closed without a stale automatic reopen");
    std::ofstream(ipc+"/keyboard.request")<<2;
    delay(650);
    check(overlays->IsOverlayVisible(board),"keyboard reopens with normal case");
    click("Enter");delay(600);
    check(!overlays->IsOverlayVisible(board) && !overlays->IsOverlayVisible(upper) && title(display,window).find("Fixture Enter")!=std::string::npos,"Enter reaches Chrome and dismisses keyboard");
    std::ofstream(ipc+"/keyboard.request")<<3;delay(650);
    click("Tab");delay(200);click("Enter");delay(650);
    check(title(display,window).find("Fixture submitted")!=std::string::npos,"Tab from password to submit button then Enter activates the button");
    browser_click(400,180);delay(650);
    browser_click(1400,120);delay(650);
    check(has(ipc,"\"keyboard_visible\":false"),"clicking outside the editor dismisses the keyboard for navigation");
    std::ofstream(ipc+"/keyboard.request")<<30;delay(650);
    const auto blocked=counter(ipc,"keyboard_blocked");
    click("a");delay(650);
    check(counter(ipc,"keyboard_blocked")==blocked+1 && has(ipc,"\"has_editor\":false"),"clicking page background retires the previous field and blocks stale typing");
    check(has(ipc,"\"keyboard_visible\":true"),"manually opened keyboard stays available without a typing target");
    click("Hide");delay(650);
    browser_click(400,180);delay(650);click("Shift");click("`");
    check(wait_title(display,window,"Fixture hidden"),"fixture asynchronously hides its selected field without navigating");
    for (int i=0;i<60 && !has(ipc,"\"keyboard_visible\":false");++i) delay(50);
    check(has(ipc,"\"keyboard_visible\":false") && has(ipc,"\"has_editor\":false"),"hidden field retires the target and dismisses its automatic keyboard without another keypress");
    std::ofstream(ipc+"/keyboard.request")<<31;delay(650);
    const auto hidden_blocked=counter(ipc,"keyboard_blocked");
    click("a");delay(650);
    check(counter(ipc,"keyboard_blocked")==hidden_blocked+1 && has(ipc,"\"has_editor\":false"),"hidden field is rejected and its retained target is cleared");
    std::ofstream(ipc+"/browser-command.txt")<<"1 2";delay(1000);
    std::ofstream(ipc+"/keyboard.request")<<4;delay(650);
    const auto reload_blocked=counter(ipc,"keyboard_blocked");
    click("a");delay(650);
    check(counter(ipc,"keyboard_blocked")==reload_blocked+1 && title(display,window).find("Cinema input fixture")!=std::string::npos,"Reload clears the old field and manual keyboard cannot type into it");
    browser_click(400,180);delay(650);
    key_symbol(display,XK_F6,window);XSync(display,False);
    check(wait_title(display,window,"Fixture removed"),"manual keyboard fixture removes the newly selected field");
    for (int i=0;i<60 && !has(ipc,"\"has_editor\":false");++i) delay(50);
    check(has(ipc,"\"keyboard_visible\":true") && has(ipc,"\"has_editor\":false"),"manual keyboard remains open when its selected field disappears");
    click("Hide");delay(650);
    std::ofstream(ipc+"/browser-command.txt")<<"11 2";delay(1000);
    browser_click(400,180);delay(650);
    key_symbol(display,XK_F6,window);XSync(display,False);
    check(wait_title(display,window,"Fixture removed"),"fixture asynchronously removes the focused field");
    for (int i=0;i<60 && !has(ipc,"\"keyboard_visible\":false");++i) delay(50);
    check(has(ipc,"\"keyboard_visible\":false") && has(ipc,"\"has_editor\":false"),"removed field dismisses its automatic keyboard without typing into a stale target");
    std::ofstream(ipc+"/browser-command.txt")<<"2 2";delay(1000);
    browser_click(400,180);delay(650);
    check(has(ipc,"\"keyboard_visible\":true"),"newly selected field opens keyboard after removal recovery");
    key_symbol(display,XK_F7,window);XSync(display,False);
    check(wait_title(display,window,"Fixture reloading"),"page begins its asynchronous reload");
    check(wait_title(display,window,"Cinema input fixture"),"fixture reloads through the page while an editor was selected");
    delay(1500);
    check(has(ipc,"\"keyboard_visible\":false") && has(ipc,"\"has_editor\":false"),"page navigation dismisses an automatic keyboard whose field no longer exists");
    std::printf("Diagnostic navigation editor=%d control=%d role=%ld automatic=%d\n",has(ipc,"\"has_editor\":true"),has(ipc,"\"has_control\":true"),counter(ipc,"control_role"),has(ipc,"\"keyboard_automatic\":true"));
    browser_click(400,180);delay(650);
    key_symbol(display,XK_F4,window);XSync(display,False);
    check(wait_title(display,window,"Fixture removed"),"autofocus fixture removes its first field");
    for (int i=0;i<25 && !has(ipc,"\"keyboard_visible\":false");++i) delay(50);
    check(has(ipc,"\"keyboard_visible\":false"),"automatic keyboard retires before delayed next-field autofocus");
    check(wait_title(display,window,"Fixture next field"),"replacement field receives delayed autofocus");
    delay(650);
    check(has(ipc,"\"keyboard_visible\":true") && has(ipc,"\"has_editor\":true"),"valid subsequent autofocus reopens the keyboard after automatic retirement");
    click("a");
    check(wait_title(display,window,"Password length 1"),"reopened keyboard delivers text to the replacement field");
    click("Hide");delay(650);
    key_symbol(display,XK_F8,window);XSync(display,False);delay(250);
    check(title(display,window).find("Grid ready")!=std::string::npos,"fixture navigates from form to profile grid with keyboard hidden");
    bool hover_good=true;
    for (int i=0;i<9;++i) {
        const float x=(i%3+.5f)*browser_size.width/3,y=(i/3+.5f)*browser_size.height/3;
        point(ipc,screen,x/browser_size.width,y/browser_size.height,0,4.2f,float(browser_size.height)/browser_size.width);
        const bool hover=wait_title(display,window,"\"event\":\"mouseenter\",\"target\":"+std::to_string(i),1000);
        hover_good=hover_good && hover;
        browser_click(x,y);
        const bool clicked=wait_title(display,window,"\"last\":"+std::to_string(i)+",\"clicks\":"+std::to_string(i+1)+",");
        const auto actual=title(display,window);
        std::printf("Diagnostic grid tile %d result %s\n",i,actual.c_str());
        std::string label="profile tile "+std::to_string(i)+" receives a complete pointer click";
        check(clicked,label.c_str());
    }
    check(hover_good,"browser hover reaches all nine profile tiles");
    point(ipc,screen,.5f,.5f,5,4.2f,float(browser_size.height)/browser_size.width);
    check(wait_title(display,window,"Grid wheel"),"browser receives wheel scrolling through the direct pointer route");
    // Browser selection occurs once on trigger down. Motion and another down
    // packet during the same owned gesture cannot drag or activate again.
    point(ipc,screen,.5f,.5f,0,4.2f,float(browser_size.height)/browser_size.width);delay(50);
    point(ipc,screen,.5f,.5f,1,4.2f,float(browser_size.height)/browser_size.width);delay(65);
    point(ipc,screen,.8f,.5f,0,4.2f,float(browser_size.height)/browser_size.width);delay(50);
    point(ipc,screen,.8f,.5f,1,4.2f,float(browser_size.height)/browser_size.width);delay(50);
    point(ipc,screen,.8f,.5f,2,4.2f,float(browser_size.height)/browser_size.width);delay(200);
    check(title(display,window).find("\"last\":4,\"clicks\":10,")!=std::string::npos,"held motion duplicate down and release do not add a second browser activation");
    point(ipc,screen,.5f,.5f,0,4.2f,float(browser_size.height)/browser_size.width);delay(50);
    point(ipc,screen,.5f,.5f,1,4.2f,float(browser_size.height)/browser_size.width);delay(65);
    point(ipc,screen,.5f,.5f,3,4.2f,float(browser_size.height)/browser_size.width);delay(100);
    point(ipc,screen,.5f,.5f,2,4.2f,float(browser_size.height)/browser_size.width);delay(200);
    check(title(display,window).find("\"last\":4,\"clicks\":11,")!=std::string::npos,"tracking loss after activation adds no extra click");
    delay(650);
    const auto downs_before=counter(ipc,"mouse_downs");
    // A newer cancellation heartbeat must invalidate an older queued press.
    const auto cancelled=sequence;
    sequence=cancelled-2;
    point(ipc,screen,.5f,.5f,1,4.2f,float(browser_size.height)/browser_size.width);
    sequence=cancelled+1;
    delay(650);
    check(counter(ipc,"mouse_downs")==downs_before && counter(ipc,"mouse_downs")==counter(ipc,"mouse_ups") &&
        title(display,window).find("\"last\":4,\"clicks\":11,")!=std::string::npos,
        "older queued press after cancellation cannot start capture or activate a tile");
    point(ipc,screen,1.1f,.5f,1,4.2f,float(browser_size.height)/browser_size.width);delay(65);
    point(ipc,screen,.5f,.5f,0,4.2f,float(browser_size.height)/browser_size.width);delay(50);
    point(ipc,screen,.5f,.5f,2,4.2f,float(browser_size.height)/browser_size.width);delay(200);
    check(title(display,window).find("\"last\":4,\"clicks\":11,")!=std::string::npos && counter(ipc,"mouse_downs")==counter(ipc,"mouse_ups"),
          "press outside then move inside and release cannot activate a tile or leave a held mouse button");
    }
    if (!std::getenv("FRAME_CINEMA_INPUT_TEST")) {
    key_symbol(display,XK_F9,window);XSync(display,False);
    check(wait_title(display,window,"History 2"),"navigation fixture creates actual browser history");
    for (int i=1;i<=2;++i) {
        const auto path=ipc+"/input/"+std::to_string(9000000000ULL+i);
        std::ofstream(path+".tmp")<<i<<" 1";
        std::filesystem::rename(path+".tmp",path+".nav");
    }
    check(wait_title(display,window,"History 0"),"two queued Back commands traverse two real history entries");
    point(ipc,screen,400.f/browser_size.width,300.f/browser_size.height,0,4.2f,float(browser_size.height)/browser_size.width);
    point(ipc,screen,400.f/browser_size.width,300.f/browser_size.height,5,4.2f,float(browser_size.height)/browser_size.width);
    bool scrolled=false;
    for(int i=0;i<100;++i) { auto value=title(display,window);if(value.rfind("Scroll ",0)==0 && std::atoi(value.c_str()+7)>0){scrolled=true;break;}delay(20); }
    check(scrolled,"wheel down changes the real overflow container scroll position");
    point(ipc,screen,400.f/browser_size.width,300.f/browser_size.height,4,4.2f,float(browser_size.height)/browser_size.width);
    check(wait_title(display,window,"Scroll 0"),"wheel up returns the real overflow container to the top");
    browser_click(1250,160);
    check(wait_title(display,window,"Fullscreen on"),"browser click enters real DOM fullscreen");
    delay(650);
    std::printf("Diagnostic fullscreen window state before exit=%d\n",int(window_fullscreen(display,window)));
    if (auto* tree=popen("xwininfo -root -tree", "r")) {
        char line[1024];while(fgets(line,sizeof(line),tree)) std::printf("Diagnostic X tree %s",line);
        pclose(tree);
    }
    std::ofstream(ipc+"/browser-command.txt")<<"20 3";
    const bool fullscreen_exited=wait_title(display,window,"Fullscreen off");
    std::printf("Diagnostic fullscreen window state after exit=%d title=%s\n",int(window_fullscreen(display,window)),title(display,window).c_str());
    check(fullscreen_exited,"Exit full screen leaves real DOM fullscreen");
    if(!fullscreen_exited) {
        key_symbol(display,XK_Escape,window);XSync(display,False);delay(650);
        std::printf("Diagnostic second Escape state=%d title=%s\n",int(window_fullscreen(display,window)),title(display,window).c_str());
        key_symbol(display,XK_F11,window);XSync(display,False);delay(650);
        std::printf("Diagnostic F11 state=%d title=%s\n",int(window_fullscreen(display,window)),title(display,window).c_str());
        Atom full=XInternAtom(display,"_NET_WM_STATE_FULLSCREEN",False);
        XChangeProperty(display,window,XInternAtom(display,"_NET_WM_STATE",False),XA_ATOM,32,PropModeReplace,reinterpret_cast<unsigned char*>(&full),1);
        XSync(display,False);delay(250);
        key_symbol(display,XK_Escape,window);XSync(display,False);delay(650);
        std::printf("Diagnostic acknowledged fullscreen then Escape state=%d title=%s\n",int(window_fullscreen(display,window)),title(display,window).c_str());
    }
    auto nav=[&](int id,int command) {
        const auto path=ipc+"/input/"+std::to_string(9100000000ULL+id);
        std::ofstream(path+".tmp")<<id<<' '<<command;
        std::filesystem::rename(path+".tmp",path+".nav");
    };
    nav(1,4);delay(650);
    check(has(ipc,"\"keyboard_visible\":true"),"queued keyboard toggle opens the app keyboard");
    nav(2,4);delay(650);
    check(has(ipc,"\"keyboard_visible\":false"),"queued keyboard toggle closes the app keyboard");
    nav(3,4);nav(4,4);delay(650);
    check(has(ipc,"\"keyboard_visible\":false"),"two rapid keyboard toggles from closed remain closed");
    }
    check(has(ipc,"\"keyboard_error\":0") && has(ipc,"\"beam_error\":0") && has(ipc,"\"cursor_error\":0"),"keyboard beam and cursor APIs report success after interaction");
    std::printf("Compositor regression failures: %d\n",failures);std::fflush(stdout);
    std::printf("Diagnostic %s\n",status(ipc).c_str());std::fflush(stdout);
    kill(child,SIGTERM);waitpid(child,nullptr,0);XCloseDisplay(display);vr::VR_Shutdown();
    return failures?1:0;
}
