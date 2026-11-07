#pragma once
#include "scene_owner_contract.h"
#include "openvr.h"
#include <chrono>
#include <cerrno>
#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <sstream>
#include <thread>
#include <utility>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>

namespace cinema_scene_owner {
inline double wall_now(){return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();}
inline bool private_read(const std::string& path,std::string& out){
    const int fd=open(path.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return false;
    struct stat info{};bool ok=fstat(fd,&info)==0&&S_ISREG(info.st_mode)&&info.st_uid==getuid()
        &&!(info.st_mode&0077)&&info.st_size>0&&info.st_size<=4096;
    std::string value;if(ok)value.resize(size_t(info.st_size));size_t done=0;
    while(ok&&done<value.size()){const auto n=read(fd,value.data()+done,value.size()-done);if(n<0&&errno==EINTR)continue;if(n<=0)ok=false;else done+=size_t(n);}
    char extra=0;if(ok)ok=read(fd,&extra,1)==0;close(fd);if(ok)out=std::move(value);return ok;
}
inline bool private_write(const std::string& path,const std::string& wire){
    const auto temporary=path+".tmp";
    const int fd=open(temporary.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return false;
    bool ok=true;size_t done=0;
    while(ok&&done<wire.size()){const auto n=write(fd,wire.data()+done,wire.size()-done);if(n<0&&errno==EINTR)continue;if(n<=0)ok=false;else done+=size_t(n);}
    if(close(fd))ok=false;
    if(ok)ok=rename(temporary.c_str(),path.c_str())==0;
    if(!ok)unlink(temporary.c_str());
    return ok;
}
inline Process process_identity(uint32_t pid){
    if(!pid||pid>INT32_MAX)return {};
    const auto directory="/proc/"+std::to_string(pid);struct stat info{};
    if(stat(directory.c_str(),&info)||info.st_uid!=getuid())return {};
    std::ifstream input(directory+"/stat");std::string wire;std::getline(input,wire);
    const auto after=wire.rfind(')');if(after==std::string::npos)return {};
    std::istringstream fields(wire.substr(after+1));std::string value;
    for(unsigned field=3;field<=22;++field)if(!(fields>>value))return {};
    uint64_t start=0;
    for(unsigned char c:value){if(c<'0'||c>'9'||start>(UINT64_MAX-(c-'0'))/10)return {};start=start*10+(c-'0');}
    return start?Process{pid,start}:Process{};
}
inline std::string random_nonce(){
    unsigned char bytes[16];size_t done=0;
    while(done<sizeof(bytes)){const auto n=getrandom(bytes+done,sizeof(bytes)-done,0);if(n<0&&errno==EINTR)continue;if(n<=0)return {};done+=size_t(n);}
    static constexpr char hex[]="0123456789abcdef";std::string out;
    for(auto byte:bytes){out+=hex[byte>>4];out+=hex[byte&15];}return out;
}

// Only the direct-properties/event route is represented here. A broker must not
// issue required_direct until the separate A/B/C probe proves each capability.
// No creator-side OpenVR initialization, ownership transfer or texture access is
// hidden inside this adapter.
class BorrowedHandles {
#if defined(FRAME_CINEMA_SCENE_OWNER_TEST)
    friend struct BorrowedHandleTest;
#endif
    Request request_;Lease lease_;std::string stem_;uint64_t sequence_=0;
    bool requested_=false,active_=false;
    std::chrono::steady_clock::time_point checked_{};
    bool heartbeat(bool release){
        if(!active_)return false;
        Heartbeat value{request_.nonce,request_.worker,lease_.epoch,++sequence_,wall_now(),release};
        std::ostringstream wire;write_heartbeat(wire,value);return private_write(stem_+".client",wire.str());
    }
    bool read_candidate(Lease& value){std::string wire;if(!private_read(stem_+".lease",wire))return false;std::istringstream input(wire);return read_lease(input,value);}
    void abandon(){if(active_)heartbeat(true);active_=false;}
public:
    bool enabled=false;
    ~BorrowedHandles(){if(active_)heartbeat(true);}
    template<class API,class Applications> bool begin(API* api,Applications* applications,const std::string& ipc,const std::string& session,uint32_t renderer){
        if(!enabled)return true;
        request_={session,random_nonce(),process_identity(uint32_t(getpid())),process_identity(renderer),wall_now()};
        if(!valid(request_))return false;
        stem_=ipc+"/scene-owner-"+request_.nonce;
        std::ostringstream wire;write_request(wire,request_);if(!private_write(stem_+".request",wire.str()))return false;
        requested_=true;const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
        do{
            Lease candidate;const auto scene=process_identity(applications->GetCurrentSceneProcessId());
            if(read_candidate(candidate)&&accepts(candidate,request_,scene,wall_now())){
                bool matched=true;
                for(unsigned i=0;i<role_count;++i){
                    vr::VROverlayHandle_t found=0;const auto& handle=candidate.handles[i];bool other_group=false;
                    if(api->FindOverlay(key(request_,Role(i)).c_str(),&found)||found!=handle.value
                       ||api->GetOverlayRenderingPid(found)!=handle.renderer||api->IsOverlayVisible(found)
                       ||api->GetOverlayFlag(found,vr::VROverlayFlags_SortWithNonSceneOverlays,&other_group)||!other_group)matched=false;
                }
                if(!matched)return false;
                lease_=candidate;active_=true;checked_=std::chrono::steady_clock::now();
                if(heartbeat(false))return true;
                active_=false;return false;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }while(std::chrono::steady_clock::now()<deadline);
        return false;
    }
    template<class Applications> bool tick(Applications* applications){
        if(!enabled)return true;
        if(!active_)return false;
        const auto now=std::chrono::steady_clock::now();if(now-checked_<std::chrono::milliseconds(40))return true;
        checked_=now;Lease next;const auto scene=process_identity(applications->GetCurrentSceneProcessId());
        const bool read=read_candidate(next), continued=read&&continues(lease_,next,request_,scene,wall_now());
        const bool renderer=process_identity(request_.renderer.pid)==request_.renderer, worker=process_identity(request_.worker.pid)==request_.worker;
        if(!continued||!renderer||!worker){
            if(std::getenv("FRAME_CINEMA_LEASE_DIAGNOSTICS"))std::fprintf(stderr,"lease_diagnostic read=%d continued=%d renderer=%d worker=%d age_ms=%.3f same_scene=%d same_epoch=%d\n",read,continued,renderer,worker,read?1000*(wall_now()-next.updated):0,read&&next.creator==scene,read&&next.epoch==lease_.epoch);
            abandon();return false;
        }
        lease_=next;if(heartbeat(false))return true;abandon();return false;
    }
    bool borrowed(vr::VROverlayHandle_t handle)const{
        if(!enabled||!requested_||!handle)return false;
        for(const auto& own:lease_.handles)if(own.value==handle)return true;
        return false;
    }
    template<class API> vr::EVROverlayError create(API* api,Role role,const char* key_name,const char* title,vr::VROverlayHandle_t* out){
        if(!enabled)return api->CreateOverlay(key_name,title,out);
        if(!active_||unsigned(role)>=role_count||!out)return vr::VROverlayError_InvalidHandle;
        *out=lease_.handles[unsigned(role)].value;return vr::VROverlayError_None;
    }
    template<class API> vr::EVROverlayError screen_renderer(API* api,vr::VROverlayHandle_t screen,uint32_t renderer){
        if(!enabled)return api->SetOverlayRenderingPid(screen,renderer);
        return active_&&screen==lease_.handles[0].value&&renderer==request_.renderer.pid&&api->GetOverlayRenderingPid(screen)==renderer
            ?vr::VROverlayError_None:vr::VROverlayError_PermissionDenied;
    }
    template<class API> bool cleanup_safe(API* api){
        if(!enabled)return true;
        if(!active_)return false;
        Lease next;
        // Cleanup may follow a foreground-scene switch, but never an identity,
        // epoch, process lifetime or handle replacement. Do not use the current
        // foreground scene PID as permission to mutate the former scene.
        bool ok=read_candidate(next)&&continues(lease_,next,request_,lease_.creator,wall_now())
            &&process_identity(lease_.creator.pid)==lease_.creator&&process_identity(request_.renderer.pid)==request_.renderer;
        for(unsigned i=0;ok&&i<role_count;++i){
            vr::VROverlayHandle_t found=0;
            ok=!api->FindOverlay(key(request_,Role(i)).c_str(),&found)&&found==lease_.handles[i].value
                &&api->GetOverlayRenderingPid(found)==lease_.handles[i].renderer;
        }
        if(!ok){abandon();return false;}
        lease_=next;
        if(!heartbeat(false)){abandon();return false;}
        return true;
    }
    // Worker may release input/hide (only after that right was proven), but
    // destruction always belongs to A. A must also expire missing heartbeats.
    template<class API> bool release(API* api){
        if(!enabled)return true;
        if(!cleanup_safe(api))return false;
        bool ok=true;
        for(const auto& handle:lease_.handles){
            if(api->SetOverlayInputMethod(handle.value,vr::VROverlayInputMethod_None))ok=false;
            if(api->SetOverlayFlag(handle.value,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,false))ok=false;
            if(api->HideOverlay(handle.value))ok=false;
        }
        if(!heartbeat(true))ok=false;
        active_=false;return ok;
    }
    template<class API> vr::EVROverlayError destroy(API* api,vr::VROverlayHandle_t handle){return borrowed(handle)?vr::VROverlayError_None:api->DestroyOverlay(handle);}
};
}
