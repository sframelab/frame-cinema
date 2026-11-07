// Same-frame reflection cameras only. No changes to tracking or screen pose.
#include <godot_cpp/classes/open_xr_extension_wrapper.hpp>
#include <godot_cpp/classes/engine.hpp>
#include <godot_cpp/classes/rendering_server.hpp>
#include <godot_cpp/classes/xr_server.hpp>
#include <godot_cpp/classes/xr_interface.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/array.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/projection.hpp>
#include <godot_cpp/variant/transform3d.hpp>
#include <mutex>
#include <cmath>
#include <algorithm>
using namespace godot;

class FrameWaterSync final : public OpenXRExtensionWrapper {
    GDCLASS(FrameWaterSync, OpenXRExtensionWrapper)
    std::mutex mutex;
    RID cameras[2], viewports[2], material;
    Transform3D origin, plane;
    double near_z=.05, far_z=1800;
    bool enabled=false;
    uint64_t frames=0, rejected=0;
    double eye_separation=0, max_projection_error=0;
    Transform3D last_eye[2];
    static Vector3 reflect_vector(Vector3 v, Vector3 n) { return v-n*(2*n.dot(v)); }
    static bool reflect_eye(const Transform3D& eye, const Projection& p, const Transform3D& water,
                            double near_clip, double far_clip, Transform3D& mirror,
                            Projection& projection, Vector2& offset, double& size) {
        Vector3 n=water.basis.get_column(1).normalized();
        if(!eye.is_finite() || !water.is_finite() || n.length_squared()<.99 ||
           !std::isfinite(near_clip) || !std::isfinite(far_clip) || near_clip<=0 || far_clip<=near_clip)return false;
        for(int c=0;c<4;++c)for(int r=0;r<4;++r)if(!std::isfinite(p.columns[c][r]))return false;
        if(p.columns[0].x<=0 || p.columns[1].y<=0)return false;
        Vector3 point=eye.origin-n*(2*n.dot(eye.origin-water.origin));
        Basis b(reflect_vector(eye.basis.get_column(0),n),-reflect_vector(eye.basis.get_column(1),n),reflect_vector(eye.basis.get_column(2),n));
        mirror=Transform3D(b,point);
        double left=(p.columns[2].x-1)*near_clip/p.columns[0].x;
        double right=(p.columns[2].x+1)*near_clip/p.columns[0].x;
        double bottom=-(p.columns[2].y+1)*near_clip/p.columns[1].y;
        double top=-(p.columns[2].y-1)*near_clip/p.columns[1].y;
        size=std::max(right-left,top-bottom)*1.12;
        offset=Vector2((left+right)*.5,(bottom+top)*.5);
        projection.set_frustum(size,1.0,offset,near_clip,far_clip,false);
        return true;
    }
protected:
    static void _bind_methods() {
        ClassDB::bind_method(D_METHOD("configure","left_camera","right_camera","material","left_viewport","right_viewport"), &FrameWaterSync::configure);
        ClassDB::bind_method(D_METHOD("set_context","origin","water_plane","near","far","enabled"), &FrameWaterSync::set_context);
        ClassDB::bind_method(D_METHOD("clear"), &FrameWaterSync::clear);
        ClassDB::bind_method(D_METHOD("state"), &FrameWaterSync::state);
        ClassDB::bind_method(D_METHOD("reflection_case","eye","projection","water_plane","near","far"), &FrameWaterSync::reflection_case);
    }
public:
    Dictionary reflection_case(Transform3D eye, Projection source, Transform3D water, double near_clip, double far_clip) {
        Transform3D mirror;Projection projection;Vector2 offset;double size=0;
        Dictionary result;result["valid"]=reflect_eye(eye,source,water,near_clip,far_clip,mirror,projection,offset,size);
        result["mirror"]=mirror;result["projection"]=projection;result["offset"]=offset;result["size"]=size;return result;
    }
    void configure(RID left, RID right, RID p_material, RID left_view, RID right_view) {
        std::lock_guard<std::mutex> lock(mutex);
        cameras[0]=left; cameras[1]=right; material=p_material;
        viewports[0]=left_view;viewports[1]=right_view;
        enabled=false; frames=0;rejected=0;max_projection_error=0;
    }
    void set_context(Transform3D p_origin, Transform3D p_plane, double p_near, double p_far, bool p_enabled) {
        std::lock_guard<std::mutex> lock(mutex);
        origin=p_origin;plane=p_plane;near_z=p_near;far_z=p_far;
        enabled=p_enabled && origin.is_finite() && plane.is_finite() && std::isfinite(near_z) && std::isfinite(far_z)
            && near_z>0 && far_z>near_z && cameras[0].is_valid() && cameras[1].is_valid() && material.is_valid();
    }
    void clear() {
        // Caller clears before freeing viewports/material; lock excludes a
        // concurrently executing pre-render callback from using freed RIDs.
        std::lock_guard<std::mutex> lock(mutex);
        enabled=false;cameras[0]=RID();cameras[1]=RID();material=RID();viewports[0]=RID();viewports[1]=RID();
    }
    void _on_pre_render() override {
        std::lock_guard<std::mutex> lock(mutex);
        if(!enabled)return;
        auto rs=RenderingServer::get_singleton();
        // Use only Godot's render-state views. A second xrLocateViews could
        // validate a different pose/time; the engine suppresses XR viewport
        // submission when its own render_state.view_pose_valid is false.
        auto xr=XRServer::get_singleton()->get_primary_interface();
        if(xr.is_null() || !xr->is_initialized() || xr->get_view_count()!=2){++rejected;return;}
        Vector3 n=plane.basis.get_column(1).normalized();
        if(n.length_squared()<.99){++rejected;return;}
        Transform3D eyes[2], mirrors[2]; Projection projections[2]; Vector2 offsets[2]; double sizes[2];
        for(int i=0;i<2;++i) {
            // Must run after xrLocateViews, on the rendering thread. The
            // origin is XROrigin, not XRCamera: the API adds current head pose.
            eyes[i]=xr->get_transform_for_view(i,origin);
            const Projection p=xr->get_projection_for_view(i,1.0,near_z,far_z);
            // Square reflection target covers the asymmetric reflected eye
            // frustum plus a 12% margin for normal distortion/head roll.
            if(!reflect_eye(eyes[i],p,plane,near_z,far_z,mirrors[i],projections[i],offsets[i],sizes[i])){++rejected;return;}
            Projection check;
            check.set_frustum(offsets[i].x-sizes[i]*.5,offsets[i].x+sizes[i]*.5,
                              offsets[i].y-sizes[i]*.5,offsets[i].y+sizes[i]*.5,near_z,far_z);
            for(int column=0;column<4;++column)for(int row=0;row<4;++row)
                max_projection_error=std::max(max_projection_error,double(std::abs(check.columns[column][row]-projections[i].columns[column][row])));
        }
        for(int i=0;i<2;++i) {
            if(viewports[i].is_valid())rs->viewport_set_update_mode(viewports[i],RenderingServer::VIEWPORT_UPDATE_ALWAYS);
            rs->camera_set_use_vertical_aspect(cameras[i],false);
            rs->camera_set_frustum(cameras[i],sizes[i],offsets[i],near_z,far_z);
            rs->camera_set_transform(cameras[i],mirrors[i]);
            rs->material_set_param(material,i==0?"reflection_projection0":"reflection_projection1",projections[i]);
            rs->material_set_param(material,i==0?"reflection_view0":"reflection_view1",mirrors[i].affine_inverse());
            last_eye[i]=eyes[i];
        }
        eye_separation=eyes[0].origin.distance_to(eyes[1].origin);
        rs->material_set_param(material,"use_planar",true);
        ++frames;
    }
    Dictionary state() {
        std::lock_guard<std::mutex> lock(mutex);
        Dictionary result;result["enabled"]=enabled;result["frames"]=frames;result["rejected"]=rejected;
        result["eye_separation"]=eye_separation;result["projection_error"]=max_projection_error;
        result["left_eye"]=last_eye[0];result["right_eye"]=last_eye[1];return result;
    }
};

static FrameWaterSync *wrapper=nullptr;
static void initialize(ModuleInitializationLevel level) {
    if(level!=MODULE_INITIALIZATION_LEVEL_CORE)return;
    GDREGISTER_CLASS(FrameWaterSync);
    wrapper=memnew(FrameWaterSync);wrapper->register_extension_wrapper();
    Engine::get_singleton()->register_singleton("FrameWaterSync",wrapper);
}
static void terminate(ModuleInitializationLevel level) {
    if(level!=MODULE_INITIALIZATION_LEVEL_SCENE)return;
    if(wrapper)wrapper->clear();
    Engine::get_singleton()->unregister_singleton("FrameWaterSync");
}
extern "C" GDExtensionBool GDE_EXPORT frame_water_sync_init(GDExtensionInterfaceGetProcAddress proc,GDExtensionClassLibraryPtr library,GDExtensionInitialization* init) {
    GDExtensionBinding::InitObject object(proc,library,init);
    object.register_initializer(initialize);object.register_terminator(terminate);
    object.set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_CORE);return object.init();
}
