#pragma once
#include <cmath>
#include "openvr.h"

struct PointerVector {
    float x, y, z;
    PointerVector operator+(PointerVector v) const { return {x+v.x,y+v.y,z+v.z}; }
    PointerVector operator-(PointerVector v) const { return {x-v.x,y-v.y,z-v.z}; }
    PointerVector operator*(float s) const { return {x*s,y*s,z*s}; }
    float dot(PointerVector v) const { return x*v.x+y*v.y+z*v.z; }
    PointerVector cross(PointerVector v) const { return {y*v.z-z*v.y,z*v.x-x*v.z,x*v.y-y*v.x}; }
    float length() const { return std::sqrt(dot(*this)); }
};

// The quad's long axis follows the ray; its face turns toward the viewer.
// It lives in the compositor with the video, so video cannot mask the beam.
static vr::HmdMatrix34_t beam_transform(PointerVector start, PointerVector direction,
                                       float length, PointerVector viewer) {
    const auto x = direction * (1.0f / direction.length());
    const auto midpoint = start + x * (length * .5f);
    const auto to_viewer = viewer - midpoint;
    auto z = to_viewer - x * to_viewer.dot(x);
    if (z.length() < .0001f) {
        const PointerVector fallback = std::abs(x.y) < .9f ? PointerVector{0,1,0} : PointerVector{1,0,0};
        z = fallback - x * fallback.dot(x);
    }
    z = z * (1.0f/z.length());
    const auto y = z.cross(x);
    return {{{x.x,y.x,z.x,midpoint.x},{x.y,y.y,z.y,midpoint.y},{x.z,y.z,z.z,midpoint.z}}};
}
