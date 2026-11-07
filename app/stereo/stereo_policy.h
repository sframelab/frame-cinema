#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <istream>
#include <string>
namespace cinema_stereo {
constexpr double max_depth_age=.22;
inline bool fresh(double stamp,double now,double limit){return std::isfinite(stamp)&&std::isfinite(now)&&stamp>0&&now>=stamp-.01&&now-stamp<=limit;}
struct Control {
    int mode=0;uint64_t revision=0;bool eligible=false;double updated=0;
    static Control read(std::istream& in,const std::string& scene,const std::string& source,double now){
        Control c;std::string magic,s,t,extra;int allowed=0;
        if(!(in>>magic>>s>>t>>c.updated>>c.mode>>allowed>>c.revision)||(in>>extra)||magic!="FCST1"||s!=scene||t!=source
            ||c.mode<0||c.mode>3||(allowed!=0&&allowed!=1)||!fresh(c.updated,now,.4))return {};
        c.eligible=allowed==1&&c.mode>0;return c;
    }
};
struct VideoFrame {
    std::string generation;uint64_t sequence=0,presented=0;double updated=0,pts=0,expected=0;bool paused=false,seeking=false;
    static VideoFrame read(std::istream& in,const std::string& scene,const std::string& source,double now){
        VideoFrame f;std::string magic,s,t,extra;int pause=0,seek=0;
        if(!(in>>magic>>s>>t>>f.updated>>f.generation>>f.sequence>>f.presented>>f.pts>>f.expected>>pause>>seek)||(in>>extra)
          ||magic!="FCVF1"||s!=scene||t!=source||!fresh(f.updated,now,1.)||!f.sequence||!f.presented||f.generation.size()>80
          ||f.generation.find_first_not_of("0123456789.:")!=std::string::npos||!std::isfinite(f.pts)||f.pts<0
          ||!std::isfinite(f.expected)||f.expected<=0||(pause!=0&&pause!=1)||(seek!=0&&seek!=1))return {};
        f.paused=pause;f.seeking=seek;return f;
    }
};
inline float disparity(int mode){return mode==1?.006f:mode==2?.012f:mode==3?.018f:0.f;}
inline float safe_disparity(int mode,float screen_width,float ipd){
    if(!std::isfinite(screen_width)||screen_width<=0)return 0;
    if(!std::isfinite(ipd)||ipd<.05f||ipd>.085f)ipd=.05f;
    // The farthest plane must not demand eye separation beyond parallel.
    // Keep margin below the runtime's physical IPD, including Large screens.
    return std::min(disparity(mode),.85f*ipd/screen_width);
}
inline bool present(const Control& c,bool placed,bool visible,bool interactive,bool dashboard,
                    uint64_t current_revision,uint64_t depth_revision,double depth_stamp,double now){
    return c.eligible&&placed&&visible&&!interactive&&!dashboard&&current_revision==depth_revision&&fresh(depth_stamp,now,max_depth_age);
}
}
