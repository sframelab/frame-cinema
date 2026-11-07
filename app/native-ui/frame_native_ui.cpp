// Preview-only sharp native UI. Scene-owned full-resolution persistent texture.
#include "scene_owner_adapter.h"
#include "pose_history.h"
#include "native_click_gate.h"
#include "native_ui_texture.h"
#include "shortcut_edge.h"
#include "reference_change.h"
#include <godot_cpp/classes/open_xr_extension_wrapper.hpp>
#include <godot_cpp/classes/open_xrapi_extension.hpp>
#include <godot_cpp/classes/engine.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/array.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/transform3d.hpp>
#include <godot_cpp/variant/vector2.hpp>
#include <godot_cpp/variant/packed_byte_array.hpp>
#include <dlfcn.h>
#include <memory>
#include <cstdlib>
#include <ctime>
using namespace godot;
namespace cp=cinema_placement;
namespace co=cinema_scene_owner;
class NativeUICore003 {public:
    virtual vr::EVRInitError Init(vr::EVRApplicationType,const char*)=0;
    virtual void Cleanup()=0;
    virtual vr::EVRInitError IsInterfaceVersionValid(const char*)=0;
    virtual void* GetGenericInterface(const char*,vr::EVRInitError*)=0;
    virtual bool BIsHmdPresent()=0;
    virtual const char* GetEnglishStringForHmdError(vr::EVRInitError)=0;
    virtual const char* GetIDForVRInitError(vr::EVRInitError)=0;
};
class FrameNativeUI final:public OpenXRExtensionWrapper {
    GDCLASS(FrameNativeUI,OpenXRExtensionWrapper)
    uint64_t instance=0,session=0;
    void* module=nullptr;vr::IVROverlay* overlay=nullptr;vr::IVRApplications* apps=nullptr;vr::IVRSystem* system=nullptr;
    vr::IVRInput* input=nullptr;vr::IVRRenderModels* models=nullptr;
    ShortcutEdge focus_triggers[2];
    vr::VROverlayHandle_t handle=0;
    std::string ipc,scene_session;
    bool enabled=false,shown=false,held=false,require_up=true,reference_known=false;
    bool requested_visible=false,controllers_idle=false;
    const char* alignment_reason="not requested";
    uint32_t held_device=vr::k_unTrackedDeviceIndexInvalid;uint64_t universe=0;
    cp::Matrix raw{},last_pose{};Vector2 last_size{},last_logical{};
    cp::PoseHistory history;std::unique_ptr<cp::Bridge> bridge;
    int last_error=0;uint64_t moves=0,downs=0,ups=0,cancels=0;
    double last_publish=0,last_hover=-1;
    frame_native_ui::NativeClickGate clicks;
    uint64_t raw_downs=0,raw_ups=0,rejected_clicks=0,hover_attributions=0,shows=0,hides=0;
    PackedByteArray previous_pixels;
    NativeUITexture texture;
    uint32_t texture_width=0,texture_height=0;
    bool texture_ready=false,texture_layout_changed=false;
    uint64_t uploads=0,unchanged_uploads=0,uploaded_bytes=0,upload_us=0;
    int64_t last_upload_ns=0;
    static int64_t ns(){timespec t{};clock_gettime(CLOCK_MONOTONIC,&t);return int64_t(t.tv_sec)*1000000000+t.tv_nsec;}
    static std::string env(const char* name){const char* value=std::getenv(name);return value?value:"";}
    static cp::Matrix matrix(const Transform3D& t){cp::Matrix m{};for(int r=0;r<3;++r){for(int c=0;c<3;++c)m.m[r][c]=t.basis[r][c];m.m[r][3]=t.origin[r];}return m;}
    bool valid(){return enabled&&instance&&session&&overlay&&apps&&system&&get_openxr_api()->is_running()
        &&get_openxr_api()->get_session()==session&&apps->GetCurrentSceneProcessId()==uint32_t(getpid());}
    void publish(bool active){
        const double now=co::wall_now();if(active&&now-last_publish<.04)return;last_publish=now;
        if(ipc.empty()||scene_session.empty())return;
        std::ostringstream out;out.precision(17);out<<"FCNUI1 "<<scene_session<<' '<<getpid()<<' '<<now<<' '<<int(active)<<'\n';
        co::private_write(ipc+"/native-ui.txt",out.str());
    }
    void cancel(Array& events){clicks.reset();last_hover=-1;if(held){Dictionary e;e["kind"]="cancel";events.push_back(e);++cancels;}held=false;held_device=vr::k_unTrackedDeviceIndexInvalid;require_up=true;}
    void hide(Array& events){cancel(events);if(overlay&&handle&&shown){++hides;overlay->SetOverlayFlag(handle,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,false);overlay->HideOverlay(handle);}shown=false;publish(false);}
    void teardown(){Array events;hide(events);if(overlay&&handle)overlay->DestroyOverlay(handle);handle=0;texture.close();
        overlay=nullptr;apps=nullptr;system=nullptr;input=nullptr;models=nullptr;
        for(auto& edge:focus_triggers)edge.sample(0,false);
        bridge.reset();history.clear();reference_known=false;
        previous_pixels.clear();texture_width=texture_height=0;texture_ready=false;texture_layout_changed=false;last_upload_ns=0;
        if(module){dlclose(module);module=nullptr;}}
    bool call(vr::EVROverlayError e){last_error=int(e);return e==vr::VROverlayError_None;}
    bool create(){
        if(handle)return true;
        const auto key="frame-lab.cinema.native-ui."+scene_session;
        if(!call(overlay->CreateOverlay(key.c_str(),"Cinema controls",&handle)))return false;
        return call(overlay->SetOverlayFlag(handle,vr::VROverlayFlags_SortWithNonSceneOverlays,true))
            &&call(overlay->SetOverlayFlag(handle,vr::VROverlayFlags_SendVRSmoothScrollEvents,true))
            &&call(overlay->SetOverlayFlag(handle,vr::VROverlayFlags_IsPremultiplied,true))
            &&call(overlay->SetOverlayTextureColorSpace(handle,vr::ColorSpace_Gamma))
            &&call(overlay->SetOverlayInputMethod(handle,vr::VROverlayInputMethod_Mouse))
            &&call(overlay->SetOverlaySortOrder(handle,10));
    }
    bool align(){
        const double now=co::wall_now();vr::ETrackedPropertyError error{};
        const auto next_universe=system->GetUint64TrackedDeviceProperty(0,vr::Prop_CurrentUniverseId_Uint64,&error);
        const auto next=system->GetRawZeroPoseToStandingAbsoluteTrackingPose();
        if(error||!next_universe||!cp::rigid(next)){alignment_reason="waiting for tracking universe";return false;}
        if(reference_known&&(next_universe!=universe||cinema_reference_changed(next,raw))){
            if(next_universe!=universe||!bridge->rebase(cp::multiply(next,cp::inverse(raw))))bridge->invalidate(now);
            history.clear();
        }
        raw=next;universe=next_universe;reference_known=true;
        vr::TrackedDevicePose_t head{};auto before=ns();system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,&head,1);auto after=ns();
        if(after-before<=2000000)history.add(before+(after-before)/2,head);else history.clear();
        cp::Packet packet;std::ifstream input(ipc+"/placement.txt");if(!cp::read(input,packet)){alignment_reason="invalid scene placement packet";return false;}
        bool synchronized=false;
        if(packet.pose_time_ns>0){const double seconds=double(packet.pose_time_ns-ns())*1e-9;
            if(seconds>=0&&seconds<=.08){system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,float(seconds),&head,1);synchronized=true;}
            else synchronized=history.at(packet.pose_time_ns,head);
            if(!synchronized)head.bPoseIsValid=false;
        }
        const bool aligned=bridge->update(packet,head,now,synchronized);
        alignment_reason=bridge->reason;return aligned;
    }
protected:
    static void _bind_methods(){
        ClassDB::bind_method(D_METHOD("update_ui","relative","physical_size","logical_size","visible"),&FrameNativeUI::update_ui);
        ClassDB::bind_method(D_METHOD("poll_focus_wake","enabled"),&FrameNativeUI::poll_focus_wake);
        ClassDB::bind_method(D_METHOD("poll_controller_activity"),&FrameNativeUI::poll_controller_activity);
        ClassDB::bind_method(D_METHOD("set_controllers_idle","idle"),&FrameNativeUI::set_controllers_idle);
        ClassDB::bind_method(D_METHOD("upload_ui","rgba","width","height"),&FrameNativeUI::upload_ui);
        ClassDB::bind_method(D_METHOD("state"),&FrameNativeUI::state);
        ClassDB::bind_method(D_METHOD("close"),&FrameNativeUI::close);
    }
public:
    void _on_instance_created(uint64_t value)override{instance=value;ipc=env("FRAME_CINEMA_IPC");scene_session=env("FRAME_CINEMA_SESSION");
        enabled=env("FRAME_CINEMA_UNIFIED_UI")=="1"&&!ipc.empty()&&co::token(scene_session);}
    void _on_session_created(uint64_t value)override{
        session=value;if(!enabled)return;
        module=dlopen("/opt/steamvr/bin/linuxarm64/vrclient.so",RTLD_NOLOAD|RTLD_NOW);if(!module)return;
        using Factory=void*(*)(const char*,int*);auto factory=reinterpret_cast<Factory>(dlsym(module,"VRClientCoreFactory"));if(!factory)return;
        int e=0;auto* core=static_cast<NativeUICore003*>(factory("IVRClientCore_003",&e));if(!core||e)return;
        vr::EVRInitError error{};
        overlay=static_cast<vr::IVROverlay*>(core->GetGenericInterface(vr::IVROverlay_Version,&error));
        apps=static_cast<vr::IVRApplications*>(core->GetGenericInterface(vr::IVRApplications_Version,&error));
        system=static_cast<vr::IVRSystem*>(core->GetGenericInterface(vr::IVRSystem_Version,&error));
        input=static_cast<vr::IVRInput*>(core->GetGenericInterface(vr::IVRInput_Version,&error));
        models=static_cast<vr::IVRRenderModels*>(core->GetGenericInterface(vr::IVRRenderModels_Version,&error));
        bridge=std::make_unique<cp::Bridge>(scene_session,ipc+"/native-ui-map.txt");
    }
    void _on_session_destroyed()override{teardown();session=0;}
    void _on_instance_destroyed()override{teardown();instance=0;enabled=false;}
    void set_controllers_idle(bool idle){
        if(controllers_idle==idle)return;
        controllers_idle=idle;
        if(valid()&&handle&&shown)call(overlay->SetOverlayFlag(handle,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,!idle));
        if(idle){Array events;cancel(events);publish(false);}
    }
    Dictionary poll_controller_activity(){
        Dictionary result;Array hands;
        const bool available=valid()&&input&&models&&!overlay->IsDashboardVisible();
        result["available"]=available;
        if(available){
            vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
            system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
            for(unsigned hand=0;hand<2;++hand){
                auto device=system->GetTrackedDeviceIndexForControllerRole(hand?vr::TrackedControllerRole_RightHand:vr::TrackedControllerRole_LeftHand);
                if(device>=vr::k_unMaxTrackedDeviceCount||system->GetTrackedDeviceClass(device)!=vr::TrackedDeviceClass_Controller
                    ||!poses[device].bDeviceIsConnected||!poses[device].bPoseIsValid||poses[device].eTrackingResult!=vr::TrackingResult_Running_OK)continue;
                const auto&m=poses[device].mDeviceToAbsoluteTracking.m;
                Dictionary item;item["id"]=int64_t(device);
                item["pose"]=Transform3D(Basis(Vector3(m[0][0],m[1][0],m[2][0]),Vector3(m[0][1],m[1][1],m[2][1]),Vector3(m[0][2],m[1][2],m[2][2])),Vector3(m[0][3],m[1][3],m[2][3]));
                char model[512]{};vr::VRInputValueHandle_t path=0;bool pressed=false;
                system->GetStringTrackedDeviceProperty(device,vr::Prop_RenderModelName_String,model,sizeof(model));
                if(model[0]&&!input->GetInputSourceHandle(hand?"/user/hand/right":"/user/hand/left",&path)){
                    // Observe existing physical components; do not bind or steal Steam inputs.
                    for(const char* name:{"trigger","button_a","button_b","button_x","button_y","grip","thumbstick","joystick","trackpad"}){
                        vr::RenderModel_ControllerMode_State_t mode{};vr::RenderModel_ComponentState_t value{};
                        if(models->GetComponentStateForDevicePath(model,name,path,&mode,&value))pressed|=bool(value.uProperties&vr::VRComponentProperty_IsPressed);
                    }
                }
                item["pressed"]=pressed;hands.push_back(item);
            }
        }
        result["hands"]=hands;return result;
    }
    bool poll_focus_wake(bool focus){
        if(!focus||!valid()||!input||!models||overlay->IsDashboardVisible()){
            for(auto& edge:focus_triggers)edge.sample(0,false);
            return false;
        }
        // Observe the runtime's existing trigger component; do not bind it or
        // take ownership away from Steam's native pointer. Require release
        // after entering Focus, dashboard use, tracking loss or hand replacement.
        vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
        system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
        bool wake=false;
        for(unsigned hand=0;hand<2;++hand){
            const auto role=hand?vr::TrackedControllerRole_RightHand:vr::TrackedControllerRole_LeftHand;
            const auto device=system->GetTrackedDeviceIndexForControllerRole(role);
            const bool tracked=device<vr::k_unMaxTrackedDeviceCount&&system->GetTrackedDeviceClass(device)==vr::TrackedDeviceClass_Controller
                &&poses[device].bDeviceIsConnected&&poses[device].bPoseIsValid&&poses[device].eTrackingResult==vr::TrackingResult_Running_OK;
            char model[512]{};vr::VRInputValueHandle_t path=0;
            vr::RenderModel_ControllerMode_State_t mode{};vr::RenderModel_ComponentState_t component{};
            if(tracked)system->GetStringTrackedDeviceProperty(device,vr::Prop_RenderModelName_String,model,sizeof(model));
            const bool readable=tracked&&model[0]&&input->GetInputSourceHandle(hand?"/user/hand/right":"/user/hand/left",&path)==vr::VRInputError_None
                &&models->GetComponentStateForDevicePath(model,"trigger",path,&mode,&component);
            const bool down=(component.uProperties&vr::VRComponentProperty_IsPressed)!=0;
            wake=focus_triggers[hand].sample(readable?device+1:0,down)||wake;
        }
        return wake;
    }
    bool upload_ui(const PackedByteArray& rgba,int width,int height){
        // Existing full-resolution library is 3200x1300 = 16,640,000 RGBA bytes.
        // Keep a strict 16 MiB ceiling; do not guess/compress or silently downscale.
        if(!valid()||width<1||height<1||width>4096||height>4096
            ||uint64_t(width)*uint64_t(height)*4>16*1024*1024
            ||uint64_t(rgba.size())!=uint64_t(width)*uint64_t(height)*4)return false;
        texture.poll();
        const auto now=ns();if(last_upload_ns&&now-last_upload_ns<66666667)return false;
        if(!create())return false;
        const auto started=ns();
        if(!texture.submit(overlay,handle,rgba.ptr(),width,height)){last_error=texture.error;return false;}
        if(texture_ready&&texture_width==uint32_t(width)&&texture_height==uint32_t(height)&&previous_pixels==rgba){++unchanged_uploads;return true;}
        last_error=0;
        upload_us=uint64_t(ns()-started)/1000;
        texture_layout_changed=texture_width!=uint32_t(width)||texture_height!=uint32_t(height);
        texture_width=uint32_t(width);texture_height=uint32_t(height);texture_ready=true;
        previous_pixels=rgba;last_upload_ns=ns();++uploads;uploaded_bytes+=uint64_t(rgba.size());
        return true;
    }
    Array update_ui(const Transform3D& relative,Vector2 physical,Vector2 logical,bool visible){
        requested_visible=visible;
        Array events;const auto rel=matrix(relative);
        texture.poll();
        const auto shortcuts=texture.take_shortcuts();
        if(valid()&&!overlay->IsDashboardVisible())for(unsigned i=0;i<8;++i)if(shortcuts&(1u<<i)){
            Dictionary action;action["kind"]="shortcut";action["index"]=int(i);events.push_back(action);
        }
        if(texture_ready&&!texture.ready()){
            texture_ready=false;previous_pixels.clear();
            Dictionary lost;lost["kind"]="texture_lost";events.push_back(lost);
        }
        if(!valid()||!visible||!cp::rigid(rel)||!physical.is_finite()||!logical.is_finite()
            ||physical.x<.05||physical.y<.05||physical.x>8||physical.y>8||logical.x<1||logical.y<1||logical.x>8192||logical.y>8192
            ||overlay->IsDashboardVisible()||!align()){hide(events);return events;}
        if(!create()||!texture_ready){hide(events);return events;}
        const auto pose=cp::multiply(bridge->screen,rel);
        if(!shown||physical!=last_size||logical!=last_logical||texture_layout_changed){
            cancel(events);vr::HmdVector2_t scale{{float(logical.x),float(logical.y)}};
            vr::VROverlayIntersectionMaskPrimitive_t mask{};mask.m_nPrimitiveType=vr::OverlayIntersectionPrimitiveType_Rectangle;
            mask.m_Primitive.m_Rectangle={0,0,float(logical.x),float(logical.y)};
            if(!call(overlay->SetOverlayWidthInMeters(handle,float(physical.x)))
                ||!call(overlay->SetOverlayTexelAspect(handle,float((physical.x/physical.y)/(double(texture_width)/texture_height))))
                ||!call(overlay->SetOverlayMouseScale(handle,&scale))
                ||!call(overlay->SetOverlayIntersectionMask(handle,nullptr,0))){hide(events);return events;}
            last_size=physical;last_logical=logical;texture_layout_changed=false;
        }
        if(!shown||cp::distance(pose,last_pose)>.000001||cp::angle(pose,last_pose)>.000001){
            if(!call(overlay->SetOverlayTransformAbsolute(handle,vr::TrackingUniverseStanding,&pose))){hide(events);return events;}
            last_pose=pose;
        }
        if(!shown){vr::VREvent_t stale{};while(overlay->PollNextOverlayEvent(handle,&stale,sizeof(stale))){}clicks.reset();if(!call(overlay->SetOverlayFlag(handle,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,!controllers_idle))||!call(overlay->ShowOverlay(handle))){hide(events);return events;}shown=true;++shows;}
        const double now=double(ns())*1e-9;
        vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
        system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
        auto source_of=[&](uint32_t source){return source<vr::k_unMaxTrackedDeviceCount
            &&system->GetTrackedDeviceClass(source)==vr::TrackedDeviceClass_Controller
            &&poses[source].bDeviceIsConnected&&poses[source].bPoseIsValid
            ?source:frame_native_ui::NativeClickGate::invalid_source;};
        const auto owner=clicks.held_source();
        if(owner!=frame_native_ui::NativeClickGate::invalid_source&&source_of(owner)!=owner)cancel(events);
        vr::VREvent_t event{};
        for(unsigned count=0;count<256&&overlay->PollNextOverlayEvent(handle,&event,sizeof(event));++count){
            const bool move=event.eventType==vr::VREvent_MouseMove;
            const bool down=event.eventType==vr::VREvent_MouseButtonDown;
            const bool up=event.eventType==vr::VREvent_MouseButtonUp;
            raw_downs+=down;raw_ups+=up;
            const uint32_t source=source_of(event.trackedDeviceIndex);
            if(event.eventType==vr::VREvent_FocusLeave){
                clicks.focus_leave(source);last_hover=-1;
                Dictionary e;e["kind"]="leave";events.push_back(e);continue;
            }
            if(event.eventType==vr::VREvent_ScrollSmooth){
                if(source!=frame_native_ui::NativeClickGate::invalid_source&&std::isfinite(event.data.scroll.ydelta)){
                    Dictionary e;e["kind"]="scroll";e["delta"]=event.data.scroll.ydelta;events.push_back(e);
                }continue;
            }
            if(!move&&!down&&!up)continue;
            if((down||up)&&event.data.mouse.button!=vr::VRMouseButton_Left)continue;
            // Release can be outside the rectangle; never leave the latch stuck.
            if(up){if(clicks.up(source,now))++ups;continue;}
            const double x=event.data.mouse.x,y=event.data.mouse.y;
            if(!std::isfinite(x)||!std::isfinite(y)||x<0||y<0||x>logical.x||y>logical.y)continue;
            Dictionary e;e["position"]=Vector2(std::clamp(x,0.,double(logical.x)-.001),std::clamp(double(logical.y)-y,0.,double(logical.y)-.001));
            if(move&&source!=frame_native_ui::NativeClickGate::invalid_source){
                clicks.move(source,now);last_hover=now;e["kind"]="move";++moves;events.push_back(e);
            }else if(down){
                const auto press=clicks.down(source,now);
                if(press.accepted){last_hover=now;hover_attributions+=press.used_hover;e["kind"]="click";++downs;events.push_back(e);}
                else ++rejected_clicks;
            }
        }
        // Native hover flags may trail a delivered move by one frame.
        Dictionary hover;hover["kind"]="hover";hover["inside"]=overlay->IsHoverTargetOverlay(handle)||(last_hover>=0&&now-last_hover<=.08);events.push_back(hover);
        publish(!controllers_idle);return events;
    }
    Dictionary state(){Dictionary d;d["requested_visible"]=requested_visible;d["alignment_reason"]=alignment_reason;d["dashboard_visible"]=overlay&&overlay->IsDashboardVisible();d["enabled"]=enabled;d["borrowed"]=overlay&&apps&&system;d["active"]=shown;d["error"]=last_error;d["moves"]=int64_t(moves);d["downs"]=int64_t(downs);d["ups"]=int64_t(ups);d["cancels"]=int64_t(cancels);d["raw_downs"]=int64_t(raw_downs);d["raw_ups"]=int64_t(raw_ups);d["rejected_clicks"]=int64_t(rejected_clicks);d["hover_attributions"]=int64_t(hover_attributions);d["texture_width"]=int64_t(texture_width);d["texture_height"]=int64_t(texture_height);d["uploads"]=int64_t(uploads);d["identical_frames_skipped"]=int64_t(unchanged_uploads);d["uploaded_bytes"]=int64_t(uploaded_bytes);d["last_upload_us"]=int64_t(upload_us);d["shortcut_active"]=int64_t(texture.shortcut_active());d["shortcut_error"]=texture.shortcut_error();d["shortcut_components"]=int64_t(texture.shortcut_components());d["shortcut_a_presses"]=int64_t(texture.shortcut_count(0));d["shortcut_b_presses"]=int64_t(texture.shortcut_count(1));d["texture_backend"]="persistent_gl_helper";d["texture_allocations"]=int64_t(texture.allocations);d["texture_submissions"]=int64_t(texture.submissions);d["shows"]=int64_t(shows);d["hides"]=int64_t(hides);return d;}
    void close(){teardown();enabled=false;}
};
static FrameNativeUI* native_ui=nullptr;
static void initialize(ModuleInitializationLevel level){if(level!=MODULE_INITIALIZATION_LEVEL_CORE)return;GDREGISTER_CLASS(FrameNativeUI);native_ui=memnew(FrameNativeUI);native_ui->register_extension_wrapper();Engine::get_singleton()->register_singleton("FrameNativeUI",native_ui);}
static void terminate(ModuleInitializationLevel level){if(level!=MODULE_INITIALIZATION_LEVEL_SCENE)return;if(native_ui)native_ui->close();Engine::get_singleton()->unregister_singleton("FrameNativeUI");}
extern "C" GDExtensionBool GDE_EXPORT frame_native_ui_init(GDExtensionInterfaceGetProcAddress p,GDExtensionClassLibraryPtr library,GDExtensionInitialization* init){GDExtensionBinding::InitObject o(p,library,init);o.register_initializer(initialize);o.register_terminator(terminate);o.set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_CORE);return o.init();}
