#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <istream>
#include <limits>
#include <ostream>
#include <string>

// Experimental scene-created overlay broker. This describes ownership and
// process lifetimes; a renderer permission is not treated as creator ownership.
namespace cinema_scene_owner {
enum class Role:unsigned { Screen, Keyboard, KeyboardUpper, KeyboardHighlight, Return, Stereo, Count };
constexpr unsigned role_count=unsigned(Role::Count);
inline const char* role_name(Role role){
    static constexpr const char* names[]={"screen","keyboard","keyboard_upper","keyboard_highlight","return","stereo"};
    return unsigned(role)<role_count?names[unsigned(role)]:"invalid";
}
enum Capability:uint32_t {
    ForeignProperties=1, ForeignEvents=2, WorkerRawTexture=4,
    ExternalScreenTexture=8, ForeignHideAndInputRelease=16
};
constexpr uint32_t required_direct=ForeignProperties|ForeignEvents|WorkerRawTexture|ExternalScreenTexture|ForeignHideAndInputRelease;
inline bool token(const std::string& value){
    if(value.empty()||value.size()>96)return false;
    for(unsigned char c:value)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'||c=='_'))return false;
    return true;
}
template<class T> inline bool decimal(std::istream& input,T& out){
    std::string text;if(!(input>>text)||text.empty()||text.size()>20)return false;
    uint64_t value=0;const auto limit=uint64_t(std::numeric_limits<T>::max());
    for(unsigned char c:text){if(c<'0'||c>'9'||value>(limit-(c-'0'))/10)return false;value=value*10+(c-'0');}
    out=T(value);return true;
}
struct Process {uint32_t pid=0;uint64_t start=0;};
inline bool operator==(Process a,Process b){return a.pid==b.pid&&a.start==b.start;}
inline bool operator!=(Process a,Process b){return !(a==b);}
inline bool valid(Process value){return value.pid>0&&value.pid<=INT32_MAX&&value.start>0;}
// 2 s: a loaded headset CPU (player start-up, DRM, decode) can stall either
// process for a few hundred ms; 0.35 s revoked live video (0.4.39 evidence).
inline bool fresh(double stamp,double now,double lifetime=2.0){return std::isfinite(stamp)&&std::isfinite(now)&&stamp<=now&&now-stamp<=lifetime;}
struct Request {
    std::string session,nonce;
    Process worker,renderer;
    double created=0;
};
inline bool valid(const Request& r){return token(r.session)&&token(r.nonce)&&valid(r.worker)&&valid(r.renderer)&&std::isfinite(r.created)&&r.created>0;}
inline bool read_request(std::istream& input,Request& out){
    std::string magic,extra;Request value;
    if(!(input>>magic>>value.session>>value.nonce)||!decimal(input,value.worker.pid)||!decimal(input,value.worker.start)
       ||!decimal(input,value.renderer.pid)||!decimal(input,value.renderer.start)||!(input>>value.created)
       ||(input>>extra)||magic!="FCSOQ1"||!valid(value))return false;
    out=value;return true;
}
inline void write_request(std::ostream& output,const Request& value){
    output.precision(17);output<<"FCSOQ1 "<<value.session<<' '<<value.nonce<<' '<<value.worker.pid<<' '<<value.worker.start
        <<' '<<value.renderer.pid<<' '<<value.renderer.start<<' '<<value.created<<'\n';
}
struct Handle {uint64_t value=0;uint32_t renderer=0;};
struct Lease {
    Request request;
    Process creator;
    uint64_t epoch=0;
    double updated=0;
    uint32_t capabilities=0;
    std::array<Handle,role_count> handles{};
};
inline std::string key(const Request& request,Role role){return "frame-lab.cinema.scene."+request.nonce+"."+role_name(role);}
inline bool same_request(const Request& a,const Request& b){return a.session==b.session&&a.nonce==b.nonce&&a.worker==b.worker&&a.renderer==b.renderer&&a.created==b.created;}
inline bool shape(const Lease& value){
    if(!valid(value.request)||!valid(value.creator)||!value.epoch||!std::isfinite(value.updated)||value.updated<=0
       ||value.creator.pid==value.request.worker.pid)return false;
    for(unsigned i=0;i<role_count;++i){
        const auto& handle=value.handles[i];
        if(!handle.value||handle.renderer!=(i==unsigned(Role::Screen)?value.request.renderer.pid:value.request.worker.pid))return false;
        for(unsigned j=0;j<i;++j)if(value.handles[j].value==handle.value)return false;
    }
    return true;
}
inline bool read_lease(std::istream& input,Lease& out){
    std::string magic,extra;Lease value;
    if(!(input>>magic>>value.request.session>>value.request.nonce)||!decimal(input,value.creator.pid)||!decimal(input,value.creator.start)
       ||!decimal(input,value.request.worker.pid)||!decimal(input,value.request.worker.start)||!decimal(input,value.request.renderer.pid)
       ||!decimal(input,value.request.renderer.start)||!(input>>value.request.created)||!decimal(input,value.epoch)||!(input>>value.updated)
       ||!decimal(input,value.capabilities)||magic!="FCSOL2")return false;
    for(unsigned i=0;i<role_count;++i){std::string name;if(!(input>>name)||!decimal(input,value.handles[i].value)||!decimal(input,value.handles[i].renderer)||name!=role_name(Role(i)))return false;}
    if((input>>extra)||!shape(value))return false;
    out=value;return true;
}
inline void write_lease(std::ostream& output,const Lease& value){
    output.precision(17);output<<"FCSOL2 "<<value.request.session<<' '<<value.request.nonce<<' '<<value.creator.pid<<' '<<value.creator.start
        <<' '<<value.request.worker.pid<<' '<<value.request.worker.start<<' '<<value.request.renderer.pid<<' '<<value.request.renderer.start
        <<' '<<value.request.created<<' '<<value.epoch<<' '<<value.updated<<' '<<value.capabilities<<'\n';
    for(unsigned i=0;i<role_count;++i)output<<role_name(Role(i))<<' '<<value.handles[i].value<<' '<<value.handles[i].renderer<<'\n';
}
inline bool accepts(const Lease& lease,const Request& requested,Process scene,double now){
    return shape(lease)&&same_request(lease.request,requested)&&lease.creator==scene&&fresh(lease.updated,now)
        &&(lease.capabilities&required_direct)==required_direct;
}
inline bool continues(const Lease& prior,const Lease& next,const Request& requested,Process scene,double now){
    if(!accepts(next,requested,scene,now)||next.epoch!=prior.epoch||next.creator!=prior.creator)return false;
    for(unsigned i=0;i<role_count;++i)if(next.handles[i].value!=prior.handles[i].value||next.handles[i].renderer!=prior.handles[i].renderer)return false;
    return next.updated>=prior.updated;
}
// The worker never owns these handles. Creator destruction is driven by an
// explicit release or a missing/expired worker heartbeat, not VR_Shutdown in B.
struct Heartbeat {std::string nonce;Process worker;uint64_t epoch=0,sequence=0;double updated=0;bool release=false;};
inline bool read_heartbeat(std::istream& input,Heartbeat& out){
    std::string magic,extra;Heartbeat value;unsigned release=2;
    if(!(input>>magic>>value.nonce)||!decimal(input,value.worker.pid)||!decimal(input,value.worker.start)||!decimal(input,value.epoch)
       ||!decimal(input,value.sequence)||!(input>>value.updated)||!decimal(input,release)
       ||(input>>extra)||magic!="FCSOH1"||!token(value.nonce)||!valid(value.worker)||!value.epoch||!value.sequence
       ||!std::isfinite(value.updated)||value.updated<=0||(release!=0&&release!=1))return false;
    value.release=release!=0;out=value;return true;
}
inline void write_heartbeat(std::ostream& output,const Heartbeat& value){
    output.precision(17);output<<"FCSOH1 "<<value.nonce<<' '<<value.worker.pid<<' '<<value.worker.start<<' '
        <<value.epoch<<' '<<value.sequence<<' '<<value.updated<<' '<<int(value.release)<<'\n';
}
inline bool heartbeat_matches(const Heartbeat& h,const Lease& lease,double now,uint64_t previous_sequence){
    return h.nonce==lease.request.nonce&&h.worker==lease.request.worker&&h.epoch==lease.epoch
        &&h.sequence>previous_sequence&&fresh(h.updated,now);
}
}
