#pragma once
#include "scene_placement.h"
#include "overlay_projection.h"
namespace cinema_layout {
inline float pointer_reach(float requested) { return std::clamp(requested,.01f,5600.f); }
// Alpine's cinema plane is distant; its keyboard retains the standard seated
// position (0, 1.05, -1.7) in the same room frame, independent of head motion.
inline cinema_placement::Matrix keyboard_pose(const cinema_placement::Matrix& screen,float width) {
    auto local=cinema_placement::identity();
    local.m[1][3]=width>6.f?1.05f-(1.65f+cinema_projection::center_height()):-1.05f;
    local.m[2][3]=width>6.f?3598.3f:2.8f;
    return cinema_placement::multiply(screen,local);
}
}
