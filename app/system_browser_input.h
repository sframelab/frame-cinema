#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <istream>
#include <string>
#include <array>

namespace cinema_system_browser {
enum class Target { Empty, Browser, Keyboard, Return };
// Native button events may omit their source. Attribute only a fresh move on
// that same surface, including the event's runtime queue age.
class HoverSources {
    struct Entry {uint32_t source=UINT32_MAX;double stamp=-1;};
    std::array<Entry,4> entries{};
public:
    void clear(){entries={};}
    void leave(Target target,uint32_t source=UINT32_MAX){
        auto& e=entries.at(unsigned(target));
        if(source==UINT32_MAX||e.source==source)e={};
    }
    void move(Target target,uint32_t source,double now,double event_age){
        if(target==Target::Empty||source==UINT32_MAX||!std::isfinite(now)||now<0
           ||!std::isfinite(event_age)||event_age<0||event_age>.25)return;
        auto& e=entries.at(unsigned(target));const double stamp=now-event_age;
        if(stamp<0||stamp<e.stamp)return;
        e={source,stamp};
    }
    uint32_t resolve(Target target,uint32_t source,double now)const{
        if(source!=UINT32_MAX)return source;
        const auto& e=entries.at(unsigned(target));const double age=now-e.stamp;
        return target!=Target::Empty&&std::isfinite(now)&&age>=0&&age<=.25?e.source:UINT32_MAX;
    }
};
struct Lease {bool valid=false,focused=false;uint32_t scene=0;};
inline Lease read_lease(std::istream& input,const std::string& expected,double now){
    std::string magic,session,extra;uint64_t pid=0;double stamp=0;int focused=-1;
    if(!(input>>magic>>session>>pid>>stamp>>focused)||(input>>extra)||magic!="FCCF1"||session!=expected
       ||pid==0||pid>UINT32_MAX||!std::isfinite(now)||!std::isfinite(stamp)||now<stamp||now-stamp>.25
       ||(focused!=0&&focused!=1))return {};
    return {true,focused==1,uint32_t(pid)};
}
struct Guard {
    bool browser=false,window=false,placement=false,show=false,interactive=false,dashboard=true,same_scene=false,lease=false;
    double crop=0;
    bool allowed()const{return browser&&window&&placement&&show&&interactive&&!dashboard&&same_scene&&lease&&std::isfinite(crop)&&std::abs(crop)<.0001;}
};
struct Pixel {int x=0,y=0;bool valid=false;};
// OpenVR Mouse coordinates are bottom-left GL pixels at SetOverlayMouseScale.
// This prototype only accepts the complete, uncropped browser image.
inline Pixel pixels(double x,double y,int width,int height,double crop=0){
    if(width<1||height<1||!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(crop)||std::abs(crop)>=.0001
       ||x<0||y<0||x>width||y>height)return {};
    return {std::clamp(int(x),0,width-1),std::clamp(height-1-int(y),0,height-1),true};
}
struct State {
    bool enabled=false,active=false,scene_latched=false,enter_requested=false,require_up=true;
    Target held=Target::Empty;uint32_t held_device=UINT32_MAX;
    uint64_t generation=0,revision=0;uint32_t scene=0;
    void cancel(){held=Target::Empty;held_device=UINT32_MAX;require_up=true;}
    void released(bool all_known_up){if(all_known_up)require_up=false;}
    bool can_enter(const Guard& guard,const Lease& lease)const{return enabled&&!active&&guard.allowed()&&lease.focused&&(!scene_latched||enter_requested);}
    void enter(uint64_t gen,uint64_t rev,uint32_t pid){active=true;scene_latched=false;enter_requested=false;generation=gen;revision=rev;scene=pid;cancel();}
    void leave(bool user){active=false;scene_latched=user;enter_requested=false;cancel();}
    bool continues(const Guard& guard,uint64_t gen,uint64_t rev,uint32_t pid)const{return active&&guard.allowed()&&gen==generation&&rev==revision&&pid==scene;}
    bool down(Target target,uint32_t device){if(!active||require_up||held!=Target::Empty||target==Target::Empty||device==UINT32_MAX)return false;held=target;held_device=device;return true;}
    bool native_down(Target target,uint32_t device){
        if(!active||held!=Target::Empty||target==Target::Empty||device==UINT32_MAX)return false;
        require_up=false;held=target;held_device=device;return true;
    }
    bool native_up(Target target,uint32_t device){
        if(!active||device==UINT32_MAX)return false;
        if(held!=Target::Empty&&!owns(target,device))return false;
        require_up=false;return up(target,device);
    }
    bool owns(Target target,uint32_t device)const{return held==target&&held_device==device;}
    bool focus_leave(Target target,uint32_t device=UINT32_MAX){
        if(held!=target||held==Target::Empty||(device!=UINT32_MAX&&held_device!=device))return false;
        cancel();return true;
    }
    bool held_tracking(bool tracked){if(held==Target::Empty||tracked)return false;cancel();return true;}
    bool up(Target target,uint32_t device){if(!owns(target,device))return false;const bool match=active&&!require_up;held=Target::Empty;held_device=UINT32_MAX;return match;}
};
// A foreign hand's release is a complete no-op, including visual key capture.
// Keeping this event-routing boundary shared makes queue-order tests exercise
// the same decision that precedes keyboard_input in the live panel.
template<class Commit> inline bool finish_key_release(State& state,uint32_t device,bool& captured,int& pressed,Commit commit){
    if(!state.owns(Target::Keyboard,device))return false;
    if(state.up(Target::Keyboard,device)&&captured){commit();return true;}
    captured=false;pressed=-1;return false;
}
}
