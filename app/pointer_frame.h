#pragma once
#include "openvr.h"
#include <istream>
#include <string>
#include <cstdint>

// Pose-frame identity changes on recenter/reference reset. Never apply an old
// press to a newly placed screen. The caller cancels a held press on rejection.
inline bool pointer_frame_matches(std::istream& input,const std::string& session,
                                  uint64_t generation,uint64_t revision) {
    std::string tag,received,extra;uint64_t gen=0,rev=0;
    return (input>>tag>>received>>gen>>rev) && !(input>>extra) && tag=="S2" &&
           !session.empty() && received==session && gen==generation && rev==revision;
}
inline void pointer_to_world(const vr::HmdMatrix34_t& screen,const float local_origin[3],
                             const float local_direction[3],float origin[3],float direction[3]) {
    for(int i=0;i<3;++i) {
        origin[i]=screen.m[i][3];direction[i]=0;
        for(int j=0;j<3;++j) {
            origin[i]+=screen.m[i][j]*local_origin[j];
            direction[i]+=screen.m[i][j]*local_direction[j];
        }
    }
}
