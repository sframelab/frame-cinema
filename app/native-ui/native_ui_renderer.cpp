#include "native_ui_channel.h"
#include "native_ui_gl_texture.h"
#include "native_shortcuts.h"
#include "scene_owner_adapter.h"
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <csignal>
#include <chrono>
#include <thread>
static volatile sig_atomic_t alive=1;
static void stop(int){alive=0;}
int main(){
    struct stat info{};if(fstat(198,&info)||info.st_size!=sizeof(NativeUIChannel))return 2;
    auto* channel=static_cast<NativeUIChannel*>(mmap(nullptr,sizeof(NativeUIChannel),PROT_READ|PROT_WRITE,MAP_SHARED,198,0));
    close(198);if(channel==MAP_FAILED)return 2;
    prctl(PR_SET_PDEATHSIG,SIGTERM);std::signal(SIGTERM,stop);std::signal(SIGINT,stop);
    const auto parent=cinema_scene_owner::Process{channel->parent,channel->parent_start};
    auto parent_live=[&](){return parent.pid==uint32_t(getppid())&&cinema_scene_owner::process_identity(parent.pid)==parent;};
    if(!parent_live())return 3;
    vr::EVRInitError init{};vr::VR_Init(&init,vr::VRApplication_Overlay);
    if(init){channel->error=-100-int(init);channel->ready.store(-1,std::memory_order_release);return 4;}
    NativeUITexture texture;auto* overlays=vr::VROverlay();
    auto until=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(alive&&parent_live()&&overlays->GetOverlayRenderingPid(channel->handle)!=uint32_t(getpid())&&std::chrono::steady_clock::now()<until)std::this_thread::sleep_for(std::chrono::milliseconds(2));
    if(!alive||!parent_live()||overlays->GetOverlayRenderingPid(channel->handle)!=uint32_t(getpid())){channel->error=-5;channel->ready.store(-1,std::memory_order_release);vr::VR_Shutdown();return 5;}
    NativeShortcuts shortcuts;shortcuts.start(channel);
    channel->ready.store(1,std::memory_order_release);
    while(alive&&!channel->stop.load(std::memory_order_acquire)&&parent_live()){
        if(vr::VRApplications()->GetCurrentSceneProcessId()!=parent.pid||overlays->GetOverlayRenderingPid(channel->handle)!=uint32_t(getpid()))break;
        shortcuts.poll(channel);
        auto request=channel->request.load(std::memory_order_acquire);
        if(request!=channel->complete.load(std::memory_order_relaxed)){
            auto w=channel->width,h=channel->height;
            if(!w||!h||w>4096||h>4096||uint64_t(w)*h*4>NativeUIChannel::capacity)channel->error=-6;
            else {texture.submit(overlays,channel->handle,channel->pixels,w,h);channel->error=texture.error;}
            channel->submissions=texture.submissions;channel->allocations=texture.allocations;
            channel->complete.store(request,std::memory_order_release);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    texture.close();vr::VR_Shutdown();munmap(channel,sizeof(NativeUIChannel));return 0;
}
