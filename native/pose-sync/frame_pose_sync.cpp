// Native OpenXR metadata only. Never submits tracking, frames, or user input.
#include <ctime>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <godot_cpp/classes/open_xr_extension_wrapper.hpp>
#include <godot_cpp/classes/open_xrapi_extension.hpp>
#include <godot_cpp/classes/engine.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/array.hpp>
#include <godot_cpp/variant/transform3d.hpp>
#include <algorithm>
#include <deque>
#include <cmath>
using namespace godot;

class FramePoseSync final:public OpenXRExtensionWrapper {
    GDCLASS(FramePoseSync,OpenXRExtensionWrapper)
    bool time_enabled=false;
    XrInstance instance=XR_NULL_HANDLE;
    PFN_xrConvertTimeToTimespecTimeKHR convert=nullptr;
    std::deque<XrEventDataReferenceSpaceChangePending> changes;
    std::deque<XrEventDataReferenceSpaceChangePending> seen;
    uint64_t overflows=0,events=0;
protected:
    static void _bind_methods() {
        ClassDB::bind_method(D_METHOD("convert_pose_time","xr_time"),&FramePoseSync::convert_pose_time);
        ClassDB::bind_method(D_METHOD("take_due_changes","xr_time","space_type"),&FramePoseSync::take_due_changes);
        ClassDB::bind_method(D_METHOD("state"),&FramePoseSync::state);
    }
public:
    Dictionary _get_requested_extensions(uint64_t) override {
        Dictionary d;
        // A native bool address makes this optional. Zero would make it required.
        d["XR_KHR_convert_timespec_time"]=uint64_t(&time_enabled);return d;
    }
    void _on_instance_created(uint64_t handle) override {
        instance=reinterpret_cast<XrInstance>(handle);
        if(time_enabled)convert=reinterpret_cast<PFN_xrConvertTimeToTimespecTimeKHR>(get_openxr_api()->get_instance_proc_addr("xrConvertTimeToTimespecTimeKHR"));
    }
    void _on_instance_destroyed() override {
        instance=XR_NULL_HANDLE;convert=nullptr;time_enabled=false;changes.clear();
    }
    void _on_session_destroyed() override { changes.clear();seen.clear(); }
    bool _on_event_polled(const void* ptr) override {
        const auto* event=static_cast<const XrEventDataBuffer*>(ptr);
        if(event && event->type==XR_TYPE_EVENT_DATA_REFERENCE_SPACE_CHANGE_PENDING) {
            const auto value=*reinterpret_cast<const XrEventDataReferenceSpaceChangePending*>(event);
            const bool duplicate=std::any_of(seen.begin(),seen.end(),[&](const auto& e){return e.session==value.session && e.referenceSpaceType==value.referenceSpaceType && e.changeTime==value.changeTime;});
            if(!duplicate) {
                seen.push_back(value);if(seen.size()>64)seen.pop_front();
                if(changes.size()==32) {changes.pop_front();++overflows;}
                changes.push_back(value);++events;
                std::stable_sort(changes.begin(),changes.end(),[](const auto& a,const auto& b){return a.changeTime<b.changeTime;});
            }
        }
        return false; // Let Godot process the original event normally.
    }
    Dictionary convert_pose_time(int64_t xr_time) const {
        Dictionary d;d["available"]=false;
        if(!time_enabled || !instance || !convert || xr_time<=0)return d;
        timespec target{},now{};
        const auto error=convert(instance,xr_time,&target);
        d["result"]=int64_t(error);
        if(XR_FAILED(error) || clock_gettime(CLOCK_MONOTONIC,&now)!=0)return d;
        const int64_t target_ns=int64_t(target.tv_sec)*1000000000+target.tv_nsec;
        const int64_t now_ns=int64_t(now.tv_sec)*1000000000+now.tv_nsec;
        // An unreasonably distant time is not a usable pose target.
        if(target_ns<=0 || std::abs(target_ns-now_ns)>250000000)return d;
        d["available"]=true;d["target_ns"]=target_ns;d["observed_ns"]=now_ns;return d;
    }
    Array take_due_changes(int64_t xr_time,int64_t space_type) {
        Array result;
        const auto session=reinterpret_cast<XrSession>(get_openxr_api()->get_session());
        while(!changes.empty() && changes.front().changeTime<=xr_time) {
            auto change=changes.front();changes.pop_front();
            if(change.session!=session || int64_t(change.referenceSpaceType)!=space_type)continue;
            Dictionary value;value["time"]=int64_t(change.changeTime);value["valid"]=false;
            // The pose fields are undefined when poseValid is false.
            if(change.poseValid==XR_TRUE) {
                const auto& q=change.poseInPreviousSpace.orientation;
                const auto& p=change.poseInPreviousSpace.position;
                const double norm=double(q.x)*q.x+double(q.y)*q.y+double(q.z)*q.z+double(q.w)*q.w;
                if(std::isfinite(norm) && std::abs(norm-1)<.002 && std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z)
                        && std::abs(p.x)<10000 && std::abs(p.y)<10000 && std::abs(p.z)<10000) {
                    value["valid"]=true;
                    value["delta"]=Transform3D(Basis(Quaternion(q.x,q.y,q.z,q.w).normalized()),Vector3(p.x,p.y,p.z));
                }
            }
            result.append(value);
        }
        return result;
    }
    Dictionary state() const {
        Dictionary d;d["instance_created"]=instance!=XR_NULL_HANDLE;d["time_enabled"]=time_enabled;
        d["converter_ready"]=convert!=nullptr;d["reference_events"]=events;d["queue_overflows"]=overflows;
        return d;
    }
};

static FramePoseSync* wrapper=nullptr;
static void initialize(ModuleInitializationLevel level) {
    if(level!=MODULE_INITIALIZATION_LEVEL_CORE)return;
    GDREGISTER_CLASS(FramePoseSync);
    wrapper=memnew(FramePoseSync);
    wrapper->register_extension_wrapper();
    Engine::get_singleton()->register_singleton("FramePoseSync",wrapper);
}
static void terminate(ModuleInitializationLevel level) {
    if(level!=MODULE_INITIALIZATION_LEVEL_SCENE)return;
    Engine::get_singleton()->unregister_singleton("FramePoseSync");
    // OpenXR's extension wrapper registration owns the wrapper until shutdown.
}
extern "C" GDExtensionBool GDE_EXPORT frame_pose_sync_init(GDExtensionInterfaceGetProcAddress proc,GDExtensionClassLibraryPtr library,GDExtensionInitialization* init) {
    GDExtensionBinding::InitObject object(proc,library,init);
    object.register_initializer(initialize);object.register_terminator(terminate);
    object.set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_CORE);return object.init();
}
