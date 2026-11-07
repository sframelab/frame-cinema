// Experimental creator-only broker. Native controller/input/rendering work
// remains in SteamVR, panel_host and Gamescope. FramePoseSync is untouched.
#include "scene_owner_adapter.h"
#include <godot_cpp/classes/open_xr_extension_wrapper.hpp>
#include <godot_cpp/classes/open_xrapi_extension.hpp>
#include <godot_cpp/classes/engine.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <algorithm>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <dlfcn.h>
using namespace godot;
namespace so=cinema_scene_owner;
namespace fs=std::filesystem;

// Public Valve src/ivrclientcore.h IVRClientCore_003 ABI. Only the query is used.
class ResidentCore003 { public:
    virtual vr::EVRInitError Init(vr::EVRApplicationType,const char*)=0;
    virtual void Cleanup()=0;
    virtual vr::EVRInitError IsInterfaceVersionValid(const char*)=0;
    virtual void* GetGenericInterface(const char*,vr::EVRInitError*)=0;
    virtual bool BIsHmdPresent()=0;
    virtual const char* GetEnglishStringForHmdError(vr::EVRInitError)=0;
    virtual const char* GetIDForVRInitError(vr::EVRInitError)=0;
};

class FrameSceneOwnerBroker final:public OpenXRExtensionWrapper {
    GDCLASS(FrameSceneOwnerBroker,OpenXRExtensionWrapper)
    uint64_t instance=0,session=0,active_instance=0,active_session=0;
    void* module=nullptr;vr::IVROverlay* overlays=nullptr;vr::IVRApplications* apps=nullptr;
    std::string ipc,scene_session,stem,reason="disabled";
    so::Lease lease;bool enabled=false,active=false,heartbeat_seen=false,cleanup_ok=true;
    uint64_t epoch_counter=0,heartbeat_sequence=0,offers=0,revocations=0;
    int borrow_error=109,last_overlay_error=0;
    double next_poll=0,offer_time=0,last_heartbeat=0;
    size_t discovery_cursor=0;
    std::deque<std::pair<std::string,double>> seen;
    static double mono(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
    static std::string env(const char* key){const char* value=std::getenv(key);return value?value:"";}
    bool configured(){
        if(env("FRAME_CINEMA_SCENE_OWNER")!="1")return false;
        ipc=env("FRAME_CINEMA_IPC");scene_session=env("FRAME_CINEMA_SESSION");
        if(ipc.empty()||ipc.front()!='/'||!so::token(scene_session)){reason="invalid_configuration";return false;}
        struct stat info{};
        if(lstat(ipc.c_str(),&info)||!S_ISDIR(info.st_mode)||info.st_uid!=getuid()||(info.st_mode&0022)){reason="ipc_directory_not_owned";return false;}
        return true;
    }
    bool scene_valid(){
        return enabled&&instance&&session&&overlays&&apps&&get_openxr_api()->is_running()
            &&get_openxr_api()->get_session()==session&&apps->GetCurrentSceneProcessId()==uint32_t(getpid());
    }
    void withdraw(){
        if(stem.empty())return;
        // Invalidate before destruction. A failing atomic write still removes
        // our lease so a worker cannot accept it through its freshness window.
        if(!so::private_write(stem+".lease","inactive\n"))unlink((stem+".lease").c_str());
    }
    void revoke(const char* why){
        if(!active&&stem.empty()){reason=why;return;}
        withdraw();bool clean=true;
        for(unsigned i=0;i<so::role_count;++i){auto& handle=lease.handles[i];if(!handle.value)continue;
            if(!overlays){clean=false;handle.value=0;continue;}
            vr::VROverlayHandle_t found=0;const auto e=overlays->FindOverlay(so::key(lease.request,so::Role(i)).c_str(),&found);
            if(e||found!=handle.value){clean=false;handle.value=0;continue;}
            // Only these exact creator-owned handles are ever mutated here.
            if(overlays->SetOverlayInputMethod(handle.value,vr::VROverlayInputMethod_None))clean=false;
            if(overlays->SetOverlayFlag(handle.value,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,false))clean=false;
            if(overlays->HideOverlay(handle.value))clean=false;
            if(overlays->DestroyOverlay(handle.value))clean=false;
            found=0;if(overlays->FindOverlay(so::key(lease.request,so::Role(i)).c_str(),&found)!=vr::VROverlayError_UnknownOverlay)clean=false;
            handle.value=0;
        }
        cleanup_ok=cleanup_ok&&clean;active=false;heartbeat_seen=false;stem.clear();++revocations;reason=why;
    }
    void release_runtime(){
        revoke("xr_teardown");overlays=nullptr;apps=nullptr;
        if(module){dlclose(module);module=nullptr;}
    }
    bool identities_valid(){
        return so::process_identity(lease.creator.pid)==lease.creator
            &&so::process_identity(lease.request.worker.pid)==lease.request.worker
            &&so::process_identity(lease.request.renderer.pid)==lease.request.renderer;
    }
    bool handle_identities_valid(){
        for(unsigned i=0;i<so::role_count;++i){vr::VROverlayHandle_t h=0;bool other=false;
            if(overlays->FindOverlay(so::key(lease.request,so::Role(i)).c_str(),&h)||h!=lease.handles[i].value
                ||overlays->GetOverlayRenderingPid(h)!=lease.handles[i].renderer
                ||overlays->GetOverlayFlag(h,vr::VROverlayFlags_SortWithNonSceneOverlays,&other)||!other)return false;
        }
        return true;
    }
    bool publish(){
        lease.updated=so::wall_now();std::ostringstream wire;so::write_lease(wire,lease);
        return so::private_write(stem+".lease",wire.str());
    }
    bool begin(const so::Request& request){
        lease={};lease.request=request;lease.creator=so::process_identity(uint32_t(getpid()));lease.epoch=++epoch_counter;
        // Proven by contract-hidden-f6686e15 on this Frame runtime: B controls
        // properties/events and its own raw textures while C renders screen.
        // B cannot grant a new renderer, destroy handles or clear C's texture.
        lease.capabilities=so::required_direct;
        if(!so::valid(lease.creator)||lease.creator==request.worker||lease.creator==request.renderer||!identities_valid())return false;
        stem=ipc+"/scene-owner-"+request.nonce;
        active_instance=instance;active_session=session;heartbeat_sequence=0;heartbeat_seen=false;
        for(unsigned i=0;i<so::role_count;++i){
            auto& h=lease.handles[i];h.renderer=i==unsigned(so::Role::Screen)?request.renderer.pid:request.worker.pid;
            auto call=[&](vr::EVROverlayError e){last_overlay_error=int(e);return e==vr::VROverlayError_None;};
            if(!call(overlays->CreateOverlay(so::key(request,so::Role(i)).c_str(),"Frame Cinema",&h.value))
                ||!call(overlays->SetOverlayFlag(h.value,vr::VROverlayFlags_SortWithNonSceneOverlays,true))
                ||!call(overlays->SetOverlayFlag(h.value,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,false))
                ||!call(overlays->SetOverlayInputMethod(h.value,vr::VROverlayInputMethod_None))
                ||!call(overlays->SetOverlayRenderingPid(h.value,h.renderer))){revoke("overlay_create_or_grant_failed");return false;}
            if(overlays->IsOverlayVisible(h.value)){revoke("initial_overlay_visible");return false;}
        }
        if(!handle_identities_valid()){revoke("initial_handle_readback_failed");return false;}
        active=true;offer_time=mono();last_heartbeat=offer_time;reason="awaiting_first_heartbeat";++offers;
        if(!publish()){revoke("lease_publish_failed");return false;}
        return true;
    }
    void poll_active(){
        if(instance!=active_instance||session!=active_session||!scene_valid()){revoke("scene_or_session_changed");return;}
        if(!identities_valid()||!handle_identities_valid()){revoke("process_or_handle_changed");return;}
        const double now=mono();std::string wire;so::Heartbeat h;
        if(so::private_read(stem+".client",wire)){
            std::istringstream input(wire);
            if(so::read_heartbeat(input,h)&&so::heartbeat_matches(h,lease,so::wall_now(),heartbeat_sequence)){
                heartbeat_sequence=h.sequence;heartbeat_seen=true;last_heartbeat=now;
                if(h.release){revoke("worker_released");return;}
                reason="active";
            }
        }
        if(now-(heartbeat_seen?last_heartbeat:offer_time)>(heartbeat_seen?2.0:3.0)){revoke(heartbeat_seen?"heartbeat_expired":"first_heartbeat_expired");return;}
        if(!publish())revoke("lease_publish_failed");
    }
    void discover(){
        const double now=so::wall_now();
        while(!seen.empty()&&(now-seen.front().second>10||seen.size()>128))seen.pop_front();
        std::error_code error;unsigned inspected=0;size_t matched=0;
        for(fs::directory_iterator it(ipc,error),end;!error&&it!=end;it.increment(error)){
            const auto filename=it->path().filename().string();
            if(filename.rfind("scene-owner-",0)!=0||it->path().extension()!=".request")continue;
            if(matched++<discovery_cursor)continue;
            if(inspected++==64){discovery_cursor+=64;return;}
            std::string wire;so::Request request;
            if(!so::private_read(it->path().string(),wire))continue;std::istringstream input(wire);
            if(!so::read_request(input,request)||request.session!=scene_session||!so::fresh(request.created,now,2)
                ||filename!="scene-owner-"+request.nonce+".request"||request.worker==request.renderer)continue;
            if(std::any_of(seen.begin(),seen.end(),[&](const auto& item){return item.first==request.nonce;}))continue;
            seen.emplace_back(request.nonce,now);if(begin(request)){discovery_cursor=0;return;}
        }
        discovery_cursor=0;if(error)reason="request_scan_failed";
    }
protected:
    static void _bind_methods(){ClassDB::bind_method(D_METHOD("state"),&FrameSceneOwnerBroker::state);ClassDB::bind_method(D_METHOD("close"),&FrameSceneOwnerBroker::close);}
public:
    void _on_instance_created(uint64_t value)override{instance=value;enabled=configured();}
    void _on_session_created(uint64_t value)override{
        session=value;if(!enabled)return;
        module=dlopen("/opt/steamvr/bin/linuxarm64/vrclient.so",RTLD_NOLOAD|RTLD_NOW);if(!module){reason="runtime_not_resident";return;}
        using Factory=void*(*)(const char*,int*);const auto factory=reinterpret_cast<Factory>(dlsym(module,"VRClientCoreFactory"));if(!factory){reason="factory_missing";return;}
        int error=0;auto* core=static_cast<ResidentCore003*>(factory("IVRClientCore_003",&error));if(!core||error){borrow_error=error;reason="core_missing";return;}
        vr::EVRInitError a{},b{};overlays=static_cast<vr::IVROverlay*>(core->GetGenericInterface(vr::IVROverlay_Version,&a));apps=static_cast<vr::IVRApplications*>(core->GetGenericInterface(vr::IVRApplications_Version,&b));
        borrow_error=a?int(a):int(b);reason=overlays&&apps?"ready":"interface_missing";
    }
    void _on_process()override{
        const double now=mono();if(now<next_poll)return;next_poll=now+.04;
        if(active){poll_active();return;}
        if(scene_valid())discover();
    }
    void _on_session_destroyed()override{release_runtime();session=0;}
    void _on_instance_destroyed()override{release_runtime();instance=0;enabled=false;}
    Dictionary state(){Dictionary d;d["enabled"]=enabled;d["borrowed"]=overlays&&apps;d["borrow_error"]=borrow_error;d["active"]=active;d["first_heartbeat_seen"]=heartbeat_seen;d["reason"]=reason.c_str();d["offers"]=int64_t(offers);d["revocations"]=int64_t(revocations);d["cleanup_ok"]=cleanup_ok;d["last_overlay_error"]=last_overlay_error;d["actual_scene_is_self"]=apps&&apps->GetCurrentSceneProcessId()==uint32_t(getpid());d["xr_running"]=instance&&session&&get_openxr_api()->is_running();return d;}
    void close(){revoke("closed");enabled=false;}
};
static FrameSceneOwnerBroker* wrapper=nullptr;
static void initialize(ModuleInitializationLevel level){if(level!=MODULE_INITIALIZATION_LEVEL_CORE)return;GDREGISTER_CLASS(FrameSceneOwnerBroker);wrapper=memnew(FrameSceneOwnerBroker);wrapper->register_extension_wrapper();Engine::get_singleton()->register_singleton("FrameSceneOwnerBroker",wrapper);}
static void terminate(ModuleInitializationLevel level){if(level!=MODULE_INITIALIZATION_LEVEL_SCENE)return;if(wrapper)wrapper->close();Engine::get_singleton()->unregister_singleton("FrameSceneOwnerBroker");}
extern "C" GDExtensionBool GDE_EXPORT frame_scene_owner_broker_init(GDExtensionInterfaceGetProcAddress p,GDExtensionClassLibraryPtr lib,GDExtensionInitialization* init){GDExtensionBinding::InitObject o(p,lib,init);o.register_initializer(initialize);o.register_terminator(terminate);o.set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_CORE);return o.init();}
