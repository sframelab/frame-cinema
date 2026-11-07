#pragma once
#include "native_ui_channel.h"
#include "scene_owner_adapter.h"
#include <spawn.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <linux/memfd.h>
#include <filesystem>
#include <cstring>
#include <thread>
#include <vector>
extern char** environ;
// The scene owns input and overlay lifetime. Only GPU upload is delegated.
// Never mix OpenGL with this process's Vulkan/OpenXR SteamVR graphics state.
class NativeUITexture {
    NativeUIChannel* channel=nullptr;
    pid_t child=-1;
    uint64_t sequence=0;
    bool pending=false;
    std::vector<unsigned char> in_flight;
    using Clock=std::chrono::steady_clock;
    Clock::time_point deadline{};
    bool stopping=false;
    int frame_width=0,frame_height=0;
    uint64_t shortcuts_seen[8]{};
    void forget(){
        child=-1;if(channel){munmap(channel,sizeof(NativeUIChannel));channel=nullptr;}
        pending=false;sequence=0;in_flight.clear();frame_width=frame_height=0;stopping=false;
        for(auto& value:shortcuts_seen)value=0;
    }
    bool start(vr::IVROverlay* api,vr::VROverlayHandle_t handle){
        int fd=int(syscall(SYS_memfd_create,"cinema-native-ui",MFD_CLOEXEC));
        if(fd<0)return false;
        if(ftruncate(fd,sizeof(NativeUIChannel))){::close(fd);return false;}
        void* memory=mmap(nullptr,sizeof(NativeUIChannel),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
        if(memory==MAP_FAILED){::close(fd);return false;}
        channel=new(memory) NativeUIChannel;
        const auto parent=cinema_scene_owner::process_identity(uint32_t(getpid()));
        channel->parent=parent.pid;channel->parent_start=parent.start;channel->handle=handle;
        auto executable=(std::filesystem::read_symlink("/proc/self/exe").parent_path()/"native-ui/native_ui_renderer").string();
        posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions,fd,198);
        char* argv[]={executable.data(),nullptr};
        int result=posix_spawn(&child,executable.c_str(),&actions,nullptr,argv,environ);
        posix_spawn_file_actions_destroy(&actions);::close(fd);
        if(result){forget();return false;}
        error=int(api->SetOverlayRenderingPid(handle,uint32_t(child)));
        // SteamVR overlay initialization can exceed two seconds on Frame.
        // This grace applies only to startup; acknowledged uploads stay bounded
        // by the separate two-second deadline in submit().
        deadline=Clock::now()+std::chrono::seconds(10);
        return !error;
    }
public:
    int error=0;
    uint64_t submissions=0,allocations=0;
    bool ready()const{return frame_width>0&&!stopping;}
    bool busy()const{return pending;}
    unsigned take_shortcuts(){
        if(!channel||stopping)return 0;
        unsigned mask=0;
        for(unsigned i=0;i<8;++i){auto value=channel->shortcuts[i].load(std::memory_order_acquire);if(value!=shortcuts_seen[i])mask|=1u<<i;shortcuts_seen[i]=value;}
        return mask;
    }
    unsigned shortcut_active()const{return channel?channel->shortcut_active.load(std::memory_order_acquire):0;}
    unsigned shortcut_components()const{return channel?channel->shortcut_components.load(std::memory_order_acquire):0;}
    uint64_t shortcut_count(unsigned i)const{return channel&&i<8?channel->shortcuts[i].load(std::memory_order_acquire):0;}
    int shortcut_error()const{return channel?channel->shortcut_error.load(std::memory_order_acquire):0;}
    bool poll(){
        if(!channel)return false;
        int status=0;const auto reaped=waitpid(child,&status,WNOHANG);
        if(reaped==child||(reaped<0&&errno==ECHILD)){if(!error)error=channel->error?channel->error:-11;forget();return false;}
        const auto now=Clock::now();
        if(stopping){if(now>deadline)kill(child,SIGKILL);return false;}
        const auto ready_state=channel->ready.load(std::memory_order_acquire);
        if(ready_state<0&&!error)error=channel->error?channel->error:-12;
        if(pending&&channel->complete.load(std::memory_order_acquire)==sequence){
            pending=false;error=channel->error;submissions=channel->submissions;allocations=channel->allocations;
            if(!error){frame_width=int(channel->width);frame_height=int(channel->height);}
        }
        if(ready_state<0||error||(now>deadline&&(pending||ready_state==0))){
            if(!error)error=-12;
            stopping=true;frame_width=frame_height=0;channel->stop.store(1,std::memory_order_release);
            kill(child,SIGTERM);deadline=now+std::chrono::milliseconds(200);return false;
        }
        return ready_state==1;
    }
    bool submit(vr::IVROverlay* api,vr::VROverlayHandle_t handle,const unsigned char* pixels,int width,int height){
        poll();
        if(!channel){error=0;if(!start(api,handle)){if(!error)error=-10;return false;}}
        if(!poll()||pending)return false;
        size_t bytes=size_t(width)*height*4;
        if(width<1||height<1||bytes>NativeUIChannel::capacity){error=-13;return false;}
        // Success means the exact image was acknowledged, never merely queued.
        if(frame_width==width&&frame_height==height&&in_flight.size()==bytes&&!std::memcmp(in_flight.data(),pixels,bytes))return true;
        in_flight.assign(pixels,pixels+bytes);std::memcpy(channel->pixels,pixels,bytes);
        channel->width=uint32_t(width);channel->height=uint32_t(height);
        deadline=Clock::now()+std::chrono::seconds(2);
        pending=true;channel->request.store(++sequence,std::memory_order_release);
        return false;
    }
    void close(){
        if(channel)channel->stop.store(1,std::memory_order_release);
        if(child>0){
            bool ended=false;
            for(int i=0;i<100;++i){auto result=waitpid(child,nullptr,WNOHANG);if(result==child||result<0){ended=true;break;}std::this_thread::sleep_for(std::chrono::milliseconds(2));}
            if(!ended){kill(child,SIGTERM);for(int i=0;i<100;++i){if(waitpid(child,nullptr,WNOHANG)!=0){ended=true;break;}std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
            if(!ended){kill(child,SIGKILL);waitpid(child,nullptr,0);}
        }
        forget();
    }
    ~NativeUITexture(){close();}
};
