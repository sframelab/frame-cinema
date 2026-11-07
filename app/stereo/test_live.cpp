// Owned synthetic X window or generated H.264 Chrome video, with the real
// scene-created overlay lease. No provider profiles or private pixels are used.
#include "stereo_bridge.h"
#include "scene_owner_adapter.h"
#include "forwarded_window.h"
#include <filesystem>
#include <cstdio>
#include <sys/wait.h>
#include <signal.h>
Window chrome_window(Display* d,Window parent,int depth=0){
    if(depth>3)return 0;Window root,owner,*children=nullptr,result=0;unsigned count=0;
    if(!XQueryTree(d,parent,&root,&owner,&children,&count))return 0;
    for(unsigned i=0;i<count&&!result;++i){XWindowAttributes a{};XClassHint hint{};
        if(XGetWindowAttributes(d,children[i],&a)&&a.map_state==IsViewable&&a.width>=320&&a.height>=200&&XGetClassHint(d,children[i],&hint)){
            std::string cls=hint.res_class?hint.res_class:"";std::transform(cls.begin(),cls.end(),cls.begin(),[](unsigned char c){return std::tolower(c);});
            if(cls.find("chrome")!=std::string::npos)result=children[i];if(hint.res_class)XFree(hint.res_class);if(hint.res_name)XFree(hint.res_name);
        }if(!result)result=chrome_window(d,children[i],depth+1);
    }if(children)XFree(children);return result;
}
int main(int argc,char** argv){
    if(argc<4)return 2;XInitThreads();bool chrome=argc>4;
    std::string ipc=argv[1],session=argv[2],model=argv[3],test=ipc+"/stereo-fixture";
    std::filesystem::create_directory(test);std::filesystem::permissions(test,std::filesystem::perms::owner_all);
    vr::EVRInitError init{};vr::VR_Init(&init,vr::VRApplication_Overlay);if(init){std::fprintf(stderr,"fixture_init_failed=%d\n",init);return 3;}
    auto* o=vr::VROverlay();vr::VROverlayHandle_t transport=0,mono=0,stereo=0;
    if(o->FindOverlay("frame-lab.cinema.video",&transport)){std::fprintf(stderr,"fixture_transport_missing\n");return 4;}
    cinema_scene_owner::BorrowedHandles lease;lease.enabled=true;
    if(!lease.begin(o,vr::VRApplications(),ipc,session,o->GetOverlayRenderingPid(transport))){std::fprintf(stderr,"fixture_lease_begin_failed\n");return 5;}
    lease.create(o,cinema_scene_owner::Role::Screen,"","",&mono);lease.create(o,cinema_scene_owner::Role::Stereo,"","",&stereo);
    auto* display=XOpenDisplay(nullptr);if(!display)return 6;
    // Chrome can destroy a startup child between XQueryTree and attributes.
    // Ignore only that expected enumeration race in this disposable fixture.
    static XErrorHandler previous=XSetErrorHandler([](Display* d,XErrorEvent* e){
        if(e->error_code==BadWindow)return 0;
        return previous?previous(d,e):0;
    });
    Window window=0;pid_t child=0;
    pid_t sampler=0;
    setenv("FRAME_CINEMA_IPC",test.c_str(),1);setenv("FRAME_CINEMA_SESSION",session.c_str(),1);setenv("FRAME_CINEMA_SOURCE_SESSION","fixture",1);
    if(chrome){
        child=fork();if(child==0){execlp("python3","python3",argv[4],nullptr);_exit(127);}
        const double until=cinema_stereo::wall()+20;
        while(!window&&cinema_stereo::wall()<until&&lease.tick(vr::VRApplications())){
            window=chrome_window(display,DefaultRootWindow(display));
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        if(!window){std::fprintf(stderr,"fixture_chrome_window_missing\n");kill(child,SIGTERM);waitpid(child,nullptr,0);return 7;}
    }else{
        window=XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,1920,1080,0,0,0);
        XStoreName(display,window,"Cinema stereo fixture");XMapWindow(display,window);XSync(display,False);
    }
    auto target=XInternAtom(display,"STEAM_GAMESCOPE_VROVERLAY_TARGET",False);forward_window(display,target,mono,0,window);
    GC gc=XCreateGC(display,window,0,nullptr);int code=1;
    if(const char* binary=std::getenv("FRAME_CINEMA_FIXTURE_SAMPLER")){
        auto parent=std::to_string(getpid()),id=std::to_string(window);sampler=fork();
        if(sampler==0){execl(binary,binary,id.c_str(),parent.c_str(),nullptr);_exit(127);}
    }
    try{
        cinema_stereo::Bridge bridge(stereo,mono,test,session,"fixture",model);
        vr::HmdMatrix34_t pose{{{1,0,0,0},{0,1,0,1.7f},{0,0,1,-3.5f}}};
        o->SetOverlayWidthInMeters(mono,4.2);o->SetOverlayTransformAbsolute(mono,vr::TrackingUniverseStanding,&pose);
        o->SetOverlaySortOrder(mono,10);o->HideOverlay(transport);
        double duration=std::getenv("FRAME_CINEMA_FIXTURE_SECONDS")?std::atof(std::getenv("FRAME_CINEMA_FIXTURE_SECONDS")):3;
        int mode=std::getenv("FRAME_CINEMA_FIXTURE_STRENGTH")?std::atoi(std::getenv("FRAME_CINEMA_FIXTURE_STRENGTH")):2;
        bool reflect=std::getenv("FRAME_CINEMA_FIXTURE_ROOM") && std::atoi(std::getenv("FRAME_CINEMA_FIXTURE_ROOM"))==7;
        int ambient=std::getenv("FRAME_CINEMA_FIXTURE_AMBIENT")?std::atoi(std::getenv("FRAME_CINEMA_FIXTURE_AMBIENT")):0;
        const bool budget_check=std::getenv("FRAME_CINEMA_EXPECT_BUDGET")!=nullptr;
        auto begin=cinema_stereo::wall();double first=0,next_frame=0;int active=0,total=0,fallback=0,limited=0;unsigned frame=0;
        while(cinema_stereo::wall()-begin<duration+20){
            auto now=cinema_stereo::wall();if(!lease.tick(vr::VRApplications()))throw std::runtime_error("lease_expired");
            if(!chrome&&now>=next_frame){XSetForeground(display,gc,0x405a72);XFillRectangle(display,window,gc,0,0,1920,1080);
            XSetForeground(display,gc,0x253f22);XFillRectangle(display,window,gc,0,720,1920,360);
            XSetForeground(display,gc,0xc9a376);XFillRectangle(display,window,gc,500+int(frame%200),260,420,600);
            XSetForeground(display,gc,0xf3f3ed);XFillRectangle(display,window,gc,750,915,420,20);XSync(display,False);++frame;
            {std::ofstream f(test+"/video-frame.tmp");f<<std::setprecision(17)<<"FCVF1 "<<session<<" fixture "<<now<<" 1:1 "<<frame<<' '<<frame<<' '<<frame/30.<<' '<<now<<" 0 0\n";}std::rename((test+"/video-frame.tmp").c_str(),(test+"/video-frame.txt").c_str());next_frame=now+1./30;
            }
            {std::ofstream f(test+"/ambient-control.tmp");f<<std::setprecision(17)<<"FCAC1 "<<session<<' '<<now<<' '<<(ambient>0||reflect)<<' '<<reflect<<'\n';}std::rename((test+"/ambient-control.tmp").c_str(),(test+"/ambient-control.txt").c_str());
            bool test_off=first>0&&now-first>duration;
            {std::ofstream f(test+"/stereo-control.tmp");f<<std::setprecision(17)<<"FCST1 "<<session<<" fixture "<<now<<' '<<mode<<' '<<(test_off?0:1)<<" 1\n";}
            std::rename((test+"/stereo-control.tmp").c_str(),(test+"/stereo-control.txt").c_str());
            bridge.tick(window,true,true,false,false,pose,4.2,0);
            std::ifstream clock_file(test+"/video-frame.txt");
            auto clock=cinema_stereo::VideoFrame::read(clock_file,session,"fixture",now);
            bool visible=mode?bridge.active:(clock.sequence && o->IsOverlayVisible(mono));
            if(visible&&!first)first=now;
            if(first&&!test_off){++total;if(visible)++active;}
            if(budget_check&&!bridge.active&&o->IsOverlayVisible(mono)&&!o->IsOverlayVisible(stereo)){
                std::ifstream f(test+"/stereo-status.json");std::string status;std::getline(f,status);
                if(status.find("\"budget_limited\":true")!=std::string::npos)++limited;
            }
            if(test_off){if(!bridge.active&&o->IsOverlayVisible(mono)&&!o->IsOverlayVisible(stereo))++fallback;if(fallback>=15)break;}
            std::this_thread::sleep_for(std::chrono::milliseconds(16));
        }
        double ratio=total?double(active)/total:0;
        std::printf("{\"live_fixture\":true,\"six_role_lease\":true,\"active_ratio\":%.4f,\"active_samples\":%d,\"fallback_samples\":%d,\"first_frame_seconds\":%.3f}\n",ratio,active,fallback,first?first-begin:0);
        if((budget_check?limited<30:ratio<.8)||fallback<15)throw std::runtime_error("presentation_gate");
        if(budget_check)std::printf("budget_fallback_pass samples=%d\n",limited);code=0;
    }catch(const std::exception& e){std::fprintf(stderr,"live_fixture_error=%s\n",e.what());}
    if(sampler>0){kill(sampler,SIGTERM);waitpid(sampler,nullptr,0);}
    forward_window(display,target,mono,window,0);lease.release(o);XFreeGC(display,gc);if(chrome){kill(child,SIGTERM);waitpid(child,nullptr,0);}else XDestroyWindow(display,window);XCloseDisplay(display);vr::VR_Shutdown();return code;
}
