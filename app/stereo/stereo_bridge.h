#pragma once
#include "stereo_policy.h"
#include "depth_budget.h"
#include "stereo_depth.h"
#include "stereo_gl.h"
#include "openvr.h"
#include "../reflection_frame.h"
#include <memory>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <filesystem>
namespace cinema_stereo {
class Bridge {
    std::thread worker;std::mutex mutex;std::atomic<bool> stop_requested{false};
    struct Request {Window window=0;bool enabled=false;uint64_t revision=0;int mode=0;float crop=0,amount=0;};
    struct Result {
        Window window=0;uint64_t revision=0,frames=0;double captured=0,updated=0,infer_ms=0,render_ms=0;
        bool ready=false,failed=false;double capture_ms=0,submit_ms=0;
        uint64_t color_sequence=0,depth_sequence=0,missed=0;int depth_width=model_width;bool paused=false,budget_limited=false;
    };
    Request requested;Result result;
    vr::VROverlayHandle_t stereo=0,mono=0;std::string ipc,scene,source,model;
    double status_at=0,reflection_at=0;uint64_t reflection_sequence=0;bool reflection_active=false;
    uint64_t control_revision=0,epoch=0;Window previous_window=0;bool was_enabled=false;int previous_mode=0;float previous_crop=0,previous_amount=0,ipd=.05f;
    VideoFrame frame_clock(){std::ifstream f(ipc+"/video-frame.txt");return VideoFrame::read(f,scene,source,wall());}
    void run(){
        std::unique_ptr<TextureCapture> capture;std::unique_ptr<StereoGL> gpu;
        try{
            int width=model_width,height=model_height;
            if(const char* size=std::getenv("FRAME_CINEMA_DEPTH_SIZE")){width=std::atoi(size);height=width==256?160:width==512?288:224;if(width!=256&&width!=384&&width!=512)throw std::runtime_error("depth_profile");}
            const int preferred_width=width,preferred_height=height;bool suspended=true;
            auto directory=[&](int w){return w==model_width?model:(std::filesystem::path(model).parent_path()/("model"+std::to_string(w))).string();};
            auto depth=std::make_unique<DepthEstimator>(directory(width),width,height);
            uint64_t revision=0,sequence=0,local_cut=0,frames=0,missed=0,prior_presented=0;std::string generation;
            double prior_pts=0,interval=1./30;DepthBudget budget;bool budget_limited=false;Result state;
            bool fixed=std::getenv("FRAME_CINEMA_STEREO_FIXED")!=nullptr;
            std::ofstream metrics;
            if(const char* path=std::getenv("FRAME_CINEMA_STEREO_METRICS")){metrics.open(path);metrics<<"sequence,presented,captured,completed,infer_ms,total_ms,missed,depth_width,pixel_id,expected_id,pts,expected,capture_lag_ms,post_ms,capture_ms,submit_ms\n";}
            const int fixture_fps=std::getenv("FRAME_CINEMA_FIXTURE_ID_FPS")?std::atoi(std::getenv("FRAME_CINEMA_FIXTURE_ID_FPS")):0;
            std::vector<unsigned char> previous_rgb;
            while(!stop_requested){
                auto began=std::chrono::steady_clock::now();Request r;{std::lock_guard<std::mutex> lock(mutex);r=requested;}
                if(!r.enabled||!r.window){
                    suspended=true;
                    {std::lock_guard<std::mutex> lock(mutex);result.ready=false;}
                    std::this_thread::sleep_for(std::chrono::milliseconds(5));continue;
                }
                if(suspended){
                    suspended=false;budget_limited=false;budget.reset();
                    if(width!=preferred_width){
                        vr::VROverlay()->ClearOverlayTexture(stereo);gpu.reset();width=preferred_width;height=preferred_height;
                        depth=std::make_unique<DepthEstimator>(directory(width),width,height);revision=0;
                    }
                }
                if(!capture||capture->window!=r.window){
                    vr::VROverlay()->ClearOverlayTexture(stereo);gpu.reset();capture.reset();
                    capture=std::make_unique<TextureCapture>();capture->start(r.window);gpu=std::make_unique<StereoGL>(width,height);revision=0;
                }
                if(!gpu)gpu=std::make_unique<StereoGL>(width,height);
                if(revision!=r.revision){revision=r.revision;generation.clear();sequence=0;prior_presented=0;local_cut=0;previous_rgb.clear();state.ready=false;budget.reset();}
                // A 2D fallback must actually free GPU time. Retry only after
                // leaving/re-entering Focus (or toggling conversion), not by
                // continuing expensive inference behind the mono picture.
                if(budget_limited){
                    state.ready=false;state.budget_limited=true;state.updated=wall();
                    {std::lock_guard<std::mutex> lock(mutex);result=state;}
                    std::this_thread::sleep_for(std::chrono::milliseconds(5));continue;
                }
                auto clock=frame_clock();
                if(!clock.sequence||clock.seeking){state.ready=false;state.updated=wall();{std::lock_guard<std::mutex> lock(mutex);result=state;}std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
                if(generation!=clock.generation){generation=clock.generation;sequence=0;prior_presented=0;prior_pts=0;++local_cut;previous_rgb.clear();state.ready=false;}
                state.paused=clock.paused;
                if(clock.sequence==sequence){
                    state.updated=wall();if(!clock.paused&&!fresh(state.captured,wall(),max_depth_age))state.ready=false;
                    {std::lock_guard<std::mutex> lock(mutex);result=state;}
                    std::this_thread::sleep_for(std::chrono::milliseconds(clock.paused?4:1));continue;
                }
                // Notification can precede presentation. Wait for its predicted
                // display time, then retain the actual window pixels atomically.
                if(clock.expected>wall()){std::this_thread::sleep_for(std::chrono::microseconds(int64_t(std::min(.005,clock.expected-wall())*1e6)));continue;}
                if(prior_pts>0&&(clock.pts<prior_pts||clock.pts-prior_pts>.3)){++local_cut;previous_rgb.clear();prior_presented=0;}
                if(prior_pts>0&&clock.pts>prior_pts){double dt=(clock.pts-prior_pts)/std::max<uint64_t>(1,clock.presented>prior_presented?clock.presented-prior_presented:1);if(dt>=1./65&&dt<=.1)interval=dt;}
                uint64_t gap=prior_presented&&clock.presented>prior_presented+1?clock.presented-prior_presented-1:0;
                missed+=gap;prior_presented=clock.presented;prior_pts=clock.pts;sequence=clock.sequence;
                auto* o=vr::VROverlay();uint32_t flags=0;
                if(o->GetOverlayFlags(mono,&flags)||flags&vr::VROverlayFlags_ProtectedContent||!vr::VROverlayView()->IsViewingPermitted(mono))throw std::runtime_error("source_not_viewable");
                auto capture_begin=std::chrono::steady_clock::now();
                if(!capture->update())throw std::runtime_error("capture_failed");
                const double captured=wall();const auto& frozen=gpu->snapshot(*capture,r.crop);
                gpu->queue_sample(frozen,revision,sequence,captured);glFinish();auto rgb=gpu->sample();
                if(rgb.empty())throw std::runtime_error("sample_unavailable");
                // Test-only optical identity encoded INSIDE the H.264 source.
                // Production never reads frame IDs or assumes a particular image.
                int pixel_id=-1,expected_id=-1;
                if(fixture_fps){
                    pixel_id=0;expected_id=int(std::round(clock.pts*fixture_fps))%(10*fixture_fps);
                    int y=std::clamp(int(((32./1080-.5)*gpu->sy+.5)*height),0,height-1);
                    for(int bit=0;bit<12;++bit){int x=std::clamp(int((((64.*bit+32)/1920-.5)*gpu->sx+.5)*width),0,width-1);if(rgb[(y*width+x)*4]>128)pixel_id|=1<<bit;}
                }
                double capture_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-capture_begin).count();
                if(frame_difference(previous_rgb,rgb)>.19)++local_cut;previous_rgb=rgb;
                auto map=depth->infer(rgb,(revision<<20)|local_cut,sequence,captured,gpu->sx,gpu->sy,r.mode);
                if(map.sequence!=sequence||map.captured!=captured)throw std::runtime_error("frame_pair_mismatch");
                gpu->upload_depth(map.values);gpu->refine();GLuint texture=gpu->render(frozen,r.amount,true,true);glFinish();
                Request current;{std::lock_guard<std::mutex> lock(mutex);current=requested;}
                bool valid=current.enabled&&current.revision==revision&&current.window==r.window&&fresh(captured,wall(),max_depth_age);
                double submit_ms=0;
                if(valid){
                    auto submitted=std::chrono::steady_clock::now();
                    vr::Texture_t image{reinterpret_cast<void*>(uintptr_t(texture)),vr::TextureType_OpenGL,vr::ColorSpace_Gamma};
                    if(o->SetOverlayTexture(stereo,&image))throw std::runtime_error("stereo_submit");
                    if(cinema_reflection::wanted(ipc,scene,wall()))
                        cinema_reflection::publish(ipc,"reflection-stereo.bin",scene,source,wall(),sequence,r.window,
                            frozen.width,frozen.height,rgb,width,height,gpu->sx,gpu->sy,r.crop);
                    submit_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-submitted).count();++frames;
                }
                double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count();
                const bool late=!clock.paused&&(gap||elapsed>interval*1000*.90);
                double steady=std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
                auto budget_action=budget.update(late,clock.paused,fixed,width,steady);
                if(budget_action==BudgetAction::Stop)budget_limited=true;
                state={r.window,r.revision,frames,captured,wall(),map.cost_ms,elapsed,valid&&!budget_limited,false,capture_ms,submit_ms,sequence,map.sequence,missed,width,clock.paused,budget_limited};
                {std::lock_guard<std::mutex> lock(mutex);result=state;}
                if(metrics){metrics<<std::setprecision(17)<<sequence<<','<<clock.presented<<','<<captured<<','<<wall()<<','<<map.cost_ms<<','<<elapsed<<','<<missed<<','<<width<<','<<pixel_id<<','<<expected_id<<','<<clock.pts<<','<<clock.expected<<','<<1000*(captured-clock.expected)<<','<<map.post_ms<<','<<capture_ms<<','<<submit_ms<<'\n';metrics.flush();}
                // Preserve inference on every frame; reduce spatial work only.
                if(budget_action==BudgetAction::Lower){
                    {std::lock_guard<std::mutex> lock(mutex);result.ready=false;}
                    o->ClearOverlayTexture(stereo);gpu.reset();width=256;height=160;
                    depth=std::make_unique<DepthEstimator>(directory(width),width,height);gpu=std::make_unique<StereoGL>(width,height);
                    previous_rgb.clear();++local_cut;budget.reset();
                }
            }
        }catch(const std::exception& e){std::fprintf(stderr,"cinema stereo: %s\n",e.what());std::lock_guard<std::mutex> lock(mutex);result.ready=false;result.failed=true;}
        vr::VROverlay()->ClearOverlayTexture(stereo);gpu.reset();capture.reset();
    }
public:
    bool active=false;
    Bridge(vr::VROverlayHandle_t output,vr::VROverlayHandle_t input,const std::string& directory,const std::string& session,const std::string& source_session,const std::string& model_directory)
        :stereo(output),mono(input),ipc(directory),scene(session),source(source_session),model(model_directory){
        auto* o=vr::VROverlay();
        if(o->SetOverlayFlag(stereo,vr::VROverlayFlags_SideBySide_Parallel,true)||o->SetOverlayInputMethod(stereo,vr::VROverlayInputMethod_None)
            ||o->SetOverlayFlag(stereo,vr::VROverlayFlags_IgnoreTextureAlpha,true)||o->SetOverlaySortOrder(stereo,10))throw std::runtime_error("stereo_properties");
        worker=std::thread([this]{run();});
    }
    void tick(Window window,bool placed,bool show,bool interactive,bool dashboard,const vr::HmdMatrix34_t& pose,float width,float crop){
        double now=wall();std::ifstream input(ipc+"/stereo-control.txt");auto c=Control::read(input,scene,source,now);
        if(now-status_at>.25)ipd=vr::VRSystem()->GetFloatTrackedDeviceProperty(vr::k_unTrackedDeviceIndex_Hmd,vr::Prop_UserIpdMeters_Float);
        const float amount=safe_disparity(c.mode,width,ipd);
        bool enabled=c.mode>0&&c.eligible&&placed&&show&&!interactive&&!dashboard&&window;
        if(previous_window!=window||control_revision!=c.revision||enabled!=was_enabled||previous_mode!=c.mode||previous_crop!=crop||previous_amount!=amount){++epoch;previous_window=window;control_revision=c.revision;was_enabled=enabled;previous_mode=c.mode;previous_crop=crop;previous_amount=amount;}
        Result state;{std::lock_guard<std::mutex> lock(mutex);requested={window,enabled,epoch,c.mode,crop,amount};state=result;}
        auto* o=vr::VROverlay();bool wanted=enabled&&state.ready&&!state.failed&&state.window==window&&state.revision==epoch&&fresh(state.updated,now,.15)
            &&(state.paused||fresh(state.captured,now,max_depth_age))&&state.color_sequence==state.depth_sequence;
        if(wanted){vr::VRTextureBounds_t bounds{0,crop,1,1-crop};wanted=!o->SetOverlayWidthInMeters(stereo,width)&&!o->SetOverlayTransformAbsolute(stereo,vr::TrackingUniverseStanding,&pose)&&!o->SetOverlayTextureBounds(stereo,&bounds)&&!o->ShowOverlay(stereo);}
        if(wanted)o->HideOverlay(mono);else{o->HideOverlay(stereo);if(placed&&show)o->ShowOverlay(mono);}active=wanted;
        // The lake selects the picture belonging to the overlay actually shown,
        // not whichever independently sampled picture happened to arrive last.
        if(reflection_active!=wanted||reflection_sequence!=state.color_sequence||now-reflection_at>.05){
            reflection_active=wanted;reflection_sequence=state.color_sequence;reflection_at=now;
            std::ofstream f(ipc+"/reflection-presented.tmp");
            f<<std::setprecision(17)<<"FCRP1 "<<scene<<' '<<source<<' '<<now<<' '<<wanted<<' '<<state.color_sequence<<' '<<state.paused<<'\n';
            f.close();if(f)std::rename((ipc+"/reflection-presented.tmp").c_str(),(ipc+"/reflection-presented.txt").c_str());
        }
        if(now-status_at>.25){
            status_at=now;std::ofstream f(ipc+"/stereo-status.tmp");
            f<<std::setprecision(17)<<"{\"scene_session\":\""<<scene<<"\",\"source_session\":\""<<source<<"\",\"updated\":"<<now
              <<",\"active\":"<<(active?"true":"false")<<",\"eligible\":"<<(enabled?"true":"false")<<",\"failed\":"<<(state.failed?"true":"false")
              <<",\"frames\":"<<state.frames<<",\"depth_ms\":"<<state.infer_ms<<",\"render_ms\":"<<state.render_ms<<",\"capture_ms\":"<<state.capture_ms<<",\"submit_ms\":"<<state.submit_ms
              <<",\"depth_age_ms\":"<<(state.captured?1000*(now-state.captured):0)<<",\"color_sequence\":"<<state.color_sequence<<",\"depth_sequence\":"<<state.depth_sequence
              <<",\"missed_source_frames\":"<<state.missed<<",\"depth_width\":"<<state.depth_width<<",\"frame_matched\":"<<(state.frames&&state.color_sequence==state.depth_sequence?"true":"false")<<",\"budget_limited\":"<<(state.budget_limited?"true":"false")<<"}";
            f.close();std::rename((ipc+"/stereo-status.tmp").c_str(),(ipc+"/stereo-status.json").c_str());
        }
    }
    ~Bridge(){stop_requested=true;if(worker.joinable())worker.join();vr::VROverlay()->HideOverlay(stereo);vr::VROverlay()->ClearOverlayTexture(stereo);}
};
}
