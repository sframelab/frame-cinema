// Separate worker: reduces the owned private X window on the X server, reads
// a 384x216 thumbnail plus narrow source strips for precise movie-bar edges,
// and publishes palette/crop metadata. Alpine Night may also request this
// existing thumbnail for a live reflection in private, volatile /run IPC.
#include "ambient_palette.h"
#include "picture_analysis.h"
#include "reflection_frame.h"
#include "reflection_gl.h"
#include <memory>
#include "stereo/stereo_policy.h"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrender.h>
#include <chrono>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <string>
#include <thread>
#include <sys/prctl.h>
#include <unistd.h>
static volatile std::sig_atomic_t active=1;
static void stop(int){active=0;}
static bool x_failed=false;
static int x_error(Display*,XErrorEvent*){x_failed=true;return 0;}
static double now(){return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();}
static std::string env(const char* key){const char* p=std::getenv(key);return p?p:"";}
static double channel(unsigned long value,unsigned long mask) {
    if(!mask)return 0;
    while((mask&1)==0){mask>>=1;value>>=1;}
    return double(value&mask)/double(mask);
}
struct Reduction {
    Pixmap pixels=0; Picture picture=0; int width=0,height=0;
};
int main(int argc,char** argv) {
    if(argc!=3)return 2;
    const auto ipc=env("FRAME_CINEMA_IPC"),session=env("FRAME_CINEMA_SESSION"),source=env("FRAME_CINEMA_SOURCE_SESSION");
    if(ipc.empty() || session.empty() || source.empty())return 2;
    const pid_t parent=std::strtol(argv[2],nullptr,10);prctl(PR_SET_PDEATHSIG,SIGKILL);if(parent<2 || getppid()!=parent)return 0;
    std::signal(SIGTERM,stop);std::signal(SIGINT,stop);XSetErrorHandler(x_error);
    Display* d=XOpenDisplay(nullptr);if(!d)return 3;
    const Window window=std::strtoul(argv[1],nullptr,10);
    XWindowAttributes a{};if(!window || !XGetWindowAttributes(d,window,&a))return 4;
    auto* format=XRenderFindVisualFormat(d,a.visual);if(!format)return 5;
    constexpr int W=384,H=216;
    const Picture src=XRenderCreatePicture(d,window,format,0,nullptr);
    XRenderSetPictureFilter(d,src,FilterBilinear,nullptr,0);
    std::vector<Reduction> levels;int source_width=0,source_height=0;
    cinema_ambient::ContentTracker content_tracker;
    uint64_t reflected_sequence=0;std::string reflected_generation;double last_reflection=0;
    // GPU reflection path (0.4.50); the XRender path below remains the fallback.
    std::unique_ptr<ReflectionGL> gpu;double gpu_retry=0,last_queue=0,last_analysis=0;uint64_t queued_sequence=0;
    std::vector<unsigned char> gpu_pixels;
    auto release=[&](){for(const auto& level:levels){XRenderFreePicture(d,level.picture);XFreePixmap(d,level.pixels);}levels.clear();};
    while(active && getppid()==parent) {
        const auto began=std::chrono::steady_clock::now();bool enabled=false;double updated=0;int on=0;std::string magic,owner;
        std::ifstream control(ipc+"/ambient-control.txt");
        if(control>>magic>>owner>>updated>>on)enabled=magic=="FCAC1" && owner==session && on==1 && now()-updated>=-.01 && now()-updated<2;
        int reflect=0;control>>reflect;
        const bool reflection=enabled && reflect==1 && ipc.rfind("/run/user/",0)==0;
        std::ifstream clock_file(ipc+"/video-frame.txt");
        auto clock=cinema_stereo::VideoFrame::read(clock_file,session,source,now());
        // Video callbacks are the cadence. Wait for actual presentation, and
        // never busy-capture duplicate images on a 20 Hz wall-clock loop.
        // The lake shows a soft glow, cross-faded in the scene: at most 15 captures a
        // second keep the X server and this worker out of the scene's frame budget.
        bool reflection_gpu=false;
        if(reflection && now()>=gpu_retry){
            try{
                if(!gpu){gpu=std::make_unique<ReflectionGL>();gpu->start(window);}
                reflection_gpu=true;
                uint64_t done=0;double done_expected=0;
                if(gpu->collect(gpu_pixels,done,done_expected) &&
                   cinema_reflection::publish(ipc,"reflection-frame.bin",session,source,now(),done,window,a.width,a.height,gpu_pixels,ReflectionGL::W,ReflectionGL::H,1,1,0,done_expected)){
                    reflected_sequence=done;last_reflection=now();
                }
                // Every newly presented video frame; a paused picture is refreshed
                // often enough to stay fresh for the scene (< 250 ms).
                const bool fresh_frame=clock.sequence && !clock.seeking && clock.expected<=now() && clock.sequence!=queued_sequence;
                if(clock.sequence && (fresh_frame || now()-last_queue>.15) && gpu->queue(clock.sequence,clock.expected)){
                    queued_sequence=clock.sequence;last_queue=now();
                }
            }catch(const std::exception&){
                gpu.reset();reflection_gpu=false;gpu_retry=now()+2;
            }
        }else if(!reflection && gpu){gpu.reset();}
        if(reflection_gpu){
            // Palette and Fit analysis through XRender at 5 Hz only.
            if(now()-last_analysis<.2){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
        }else if(reflection && clock.sequence && !clock.seeking && !clock.paused &&
            (clock.expected>now() || now()-last_reflection<1.0/15 || (clock.sequence==reflected_sequence && clock.generation==reflected_generation && now()-last_reflection<.09))){
            std::this_thread::sleep_for(std::chrono::milliseconds(1));continue;
        }
        last_analysis=now();
        std::vector<unsigned char> reflection_pixels;bool published=false;
        cinema_ambient::GradientPalette colors{};cinema_ambient::Rect crop{};cinema_picture::Analysis fit{};bool available=false;
        x_failed=false;
        if(enabled && XGetWindowAttributes(d,window,&a) && a.map_state==IsViewable && a.width>=W && a.height>=H) {
            if(source_width!=a.width || source_height!=a.height) {
                release();content_tracker.reset();source_width=a.width;source_height=a.height;
                int width=a.width,height=a.height;
                do {
                    width=std::max(W,(width+1)/2);height=std::max(H,(height+1)/2);
                    Reduction level;level.width=width;level.height=height;
                    level.pixels=XCreatePixmap(d,window,width,height,a.depth);
                    level.picture=XRenderCreatePicture(d,level.pixels,format,0,nullptr);
                    XRenderSetPictureFilter(d,level.picture,FilterBilinear,nullptr,0);levels.push_back(level);
                } while(width>W || height>H);
            }
            Picture input=src;int width=a.width,height=a.height;
            // Each pass reduces by at most two; a single 20x bilinear reduction
            // aliases fine stripes instead of averaging their color.
            for(const auto& level:levels) {
                XTransform transform={{{XDoubleToFixed(double(width)/level.width),0,0},{0,XDoubleToFixed(double(height)/level.height),0},{0,0,XDoubleToFixed(1)}}};
                XRenderSetPictureTransform(d,input,&transform);
                XRenderComposite(d,PictOpSrc,input,None,level.picture,0,0,0,0,0,0,level.width,level.height);
                input=level.picture;width=level.width;height=level.height;
            }
            XImage* picture=XGetImage(d,levels.back().pixels,0,0,W,H,AllPlanes,ZPixmap);
            XSync(d,False);
            if(picture && !x_failed) {
                std::vector<cinema_ambient::RGB> pixels(W*H);
                // Common 24/32-bit BGRX visual: read the rows directly
                // (XGetPixel per pixel cost several ms per video frame).
                const bool direct=picture->bits_per_pixel==32 && picture->byte_order==LSBFirst &&
                    a.visual->red_mask==0xff0000 && a.visual->green_mask==0xff00 && a.visual->blue_mask==0xff;
                for(int y=0;y<H;++y) {
                    const auto* row=reinterpret_cast<const unsigned char*>(picture->data)+size_t(y)*picture->bytes_per_line;
                    for(int x=0;x<W;++x) {
                        if(direct) {pixels[y*W+x]={row[x*4+2]/255.0,row[x*4+1]/255.0,row[x*4]/255.0};continue;}
                        const auto p=XGetPixel(picture,x,y);
                        pixels[y*W+x]={channel(p,a.visual->red_mask),channel(p,a.visual->green_mask),channel(p,a.visual->blue_mask)};
                    }
                }
                if(reflection && !reflection_gpu){
                    // Fallback: a 64x36 glow map (6x6 box average of the thumbnail): water
                    // reflects light, not detail, and the transfer stays ~9 KB.
                    constexpr int GW=W/6,GH=H/6;
                    reflection_pixels.resize(GW*GH*4);
                    for(int gy=0;gy<GH;++gy)for(int gx=0;gx<GW;++gx){
                        double r=0,g=0,b=0;
                        for(int y=gy*6;y<gy*6+6;++y)for(int x=gx*6;x<gx*6+6;++x){const auto& p=pixels[y*W+x];r+=p.r;g+=p.g;b+=p.b;}
                        const size_t o=(size_t(gy)*GW+gx)*4;
                        reflection_pixels[o]=std::clamp(int(r/36*255+.5),0,255);
                        reflection_pixels[o+1]=std::clamp(int(g/36*255+.5),0,255);
                        reflection_pixels[o+2]=std::clamp(int(b/36*255+.5),0,255);
                        reflection_pixels[o+3]=255;
                    }
                    // Publish before the palette/Fit analysis and full-width bar strips:
                    // the lake shows this frame while the overlay shows it too.
                    if(clock.sequence && !clock.seeking &&
                       cinema_reflection::publish(ipc,"reflection-frame.bin",session,source,now(),clock.sequence,window,a.width,a.height,reflection_pixels,GW,GH,1,1,0,clock.expected)){
                        published=true;reflected_sequence=clock.sequence;reflected_generation=clock.generation;last_reflection=now();
                    }
                }
                crop=content_tracker.update(pixels,W,H);colors=cinema_ambient::sample_gradient(pixels,W,H,crop);fit=cinema_picture::analyze(pixels,W,H);available=true;
                const auto band=cinema_picture::boundary_band(fit,a.height,H);
                if(band.rows>0) {
                    XImage* strips[2]={XGetImage(d,window,0,band.start,a.width,band.rows,AllPlanes,ZPixmap),
                        XGetImage(d,window,0,a.height-band.start-band.rows,a.width,band.rows,AllPlanes,ZPixmap)};
                    XSync(d,False);
                    if(strips[0] && strips[1] && !x_failed) {
                        fit=cinema_picture::refine(fit,a.width,a.height,band,[&](int side,int x,int y){
                            const auto value=XGetPixel(strips[side],x,side==0?y:band.rows-1-y);
                            return cinema_ambient::RGB{channel(value,a.visual->red_mask),channel(value,a.visual->green_mask),channel(value,a.visual->blue_mask)};
                        });
                    // Optional full-resolution bar refinement must not discard
                    // the valid thumbnail palette. Fail Fit closed separately.
                    } else {fit={};}
                    for(auto* strip:strips)if(strip)XDestroyImage(strip);
                }
            }
            if(picture)XDestroyImage(picture);
        }
        const auto cost=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count();
        // One monotonic clock across replacements of this source's worker.
        const auto sequence=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
        const std::string reflection_path=ipc+"/reflection-frame.bin";
        if(!published && !reflection_gpu)std::remove(reflection_path.c_str());

        // Epoch seconds require full double precision: ten significant digits
        // round to whole seconds and fail the receiver's freshness checks.
        std::ofstream out(ipc+"/ambient-status.tmp");out<<std::setprecision(std::numeric_limits<double>::max_digits10);
        out<<"{\"session\":\""<<session<<"\",\"source_session\":\""<<source<<"\",\"updated\":"<<now()<<",\"sequence\":"<<sequence
           <<",\"available\":"<<(available?"true":"false")<<",\"analysis\":\"edge-gradient-v4\",\"edge_fraction\":"<<cinema_ambient::edge_fraction<<",\"sample_ms\":"<<cost<<",\"crop\":["<<crop.x<<','<<crop.y<<','<<crop.w<<','<<crop.h<<"],\"colors\":[";
        for(size_t i=0;i<colors.size();++i){if(i)out<<',';const auto& p=colors[i];out<<'['<<p.r<<','<<p.g<<','<<p.b<<']';}out<<"],\"fit_top\":"<<fit.top<<",\"fit_dark\":"<<(fit.dark?"true":"false")<<",\"fit_known\":"<<(fit.known?"true":"false")<<",\"fit_safe_top\":"<<fit.safe_top<<",\"window\":"<<window<<",\"viewport\":["<<source_width<<','<<source_height<<"]}";out.close();
        if(out)std::rename((ipc+"/ambient-status.tmp").c_str(),(ipc+"/ambient-status.json").c_str());
        std::this_thread::sleep_until(began+std::chrono::milliseconds(reflection&&!clock.paused?1:enabled?50:250));
    }
    std::remove((ipc+"/reflection-frame.bin").c_str());
    std::remove((ipc+"/reflection-frame.bin.tmp").c_str());
    release();XRenderFreePicture(d,src);XCloseDisplay(d);return 0;
}
