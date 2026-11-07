#pragma once
#include "scene_placement.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unistd.h>

namespace cinema_projection {
// The landscape/reflection retain the authored kilometre-scale coordinates.
// Submit the browser quad at `distance` metres, preserving its direction and
// angular size from the seated reference, after recentering.
// Headset evidence: SteamVR drew the overlay at ~100-104 m (0.4.30, 0.4.38) but
// not at 250 m (0.4.33) or 3,600 m (0.4.32, 0.4.34). alpine/overlay-distance.txt
// sets the release default. For the far-limit search, the scene's debug row
// writes "<distance> <size>" to $FRAME_CINEMA_IPC/overlay-debug.txt; size < 1
// shrinks the screen at that distance, separating a distance cap from a width cap.
constexpr float authored=3600.f;
constexpr float nearest=50.f;
constexpr float default_height=.45f*authored/104.f;
struct Tuning { float distance; float size; float height=default_height; };
inline float range_from(const char* path) {
    float range=authored;
    if (std::FILE* file=std::fopen(path,"r")) {
        float value=0.f;
        if (std::fscanf(file,"%f",&value)==1 && value>=nearest && value<=authored) range=value;
        std::fclose(file);
    }
    return range;
}
inline bool debug_from(const char* path, Tuning& out) {
    std::FILE* file=std::fopen(path,"r");
    if(!file) return false;
    float distance=0.f,size=1.f,height=default_height;
    const int read=std::fscanf(file,"%f %f %f",&distance,&size,&height);
    const bool ok=read>=2 && distance>=nearest && distance<=authored && size>=.1f && size<=1.f && height>-authored && height<authored;
    std::fclose(file);
    if(ok) out={distance,size,read==3?height:default_height};
    return ok;
}
inline const std::string& release_file() {
    // Resolve beside panel_host: the supervisor does not set a working directory.
    static const std::string path=[]{
        char exe[4096];
        const ssize_t length=readlink("/proc/self/exe",exe,sizeof exe-1);
        if(length<=0) return std::string();
        std::string self(exe,length);
        return self.substr(0,self.rfind('/')+1)+"alpine/overlay-distance.txt";
    }();
    return path;
}
inline Tuning tuning() {
    static Tuning value{authored,1.f,default_height};
    static std::chrono::steady_clock::time_point next{};
    const auto now=std::chrono::steady_clock::now();
    if(now>=next){
        next=now+std::chrono::seconds(1);
        Tuning debug{};
        const char* ipc=std::getenv("FRAME_CINEMA_IPC");
        if(ipc && *ipc && debug_from((std::string(ipc)+"/overlay-debug.txt").c_str(),debug)) value=debug;
        else value={release_file().empty()?authored:range_from(release_file().c_str()),1.f,default_height};
    }
    return value;
}
inline float range() { return tuning().distance; }
inline float center_height() { return tuning().height; }
struct Overlay { cinema_placement::Matrix pose; float width; bool projected; };
inline Overlay browser(const cinema_placement::Matrix& screen,float width,float distance,float size=1.f,float height=default_height) {
    if(width<=6.f) return {screen,width,false};
    const float scale=distance/authored;
    auto offset=cinema_placement::identity();
    offset.m[1][3]=height*(scale-1.f);
    offset.m[2][3]=authored*(1.f-scale);
    return {cinema_placement::multiply(screen,offset),width*scale*size,true};
}
inline Overlay browser(const cinema_placement::Matrix& screen,float width) {
    const Tuning t=tuning();
    return browser(screen,width,t.distance,t.size,t.height);
}
}
