#pragma once
#include "openvr.h"

namespace cinema_controller {
// OpenVR's raw fTop is the lower Y tangent, fBottom the upper tangent.
// NDC increases upwards. Do not treat these names as image-row coordinates.
inline vr::VROverlayProjection_t crop_projection(
    const vr::VROverlayProjection_t& full, float x0, float y0, float x1, float y1) {
    vr::VROverlayProjection_t crop{};
    crop.fLeft = full.fLeft + (full.fRight - full.fLeft) * (x0 + 1.f) * .5f;
    crop.fRight = full.fLeft + (full.fRight - full.fLeft) * (x1 + 1.f) * .5f;
    crop.fTop = full.fTop + (full.fBottom - full.fTop) * (y0 + 1.f) * .5f;
    crop.fBottom = full.fTop + (full.fBottom - full.fTop) * (y1 + 1.f) * .5f;
    return crop;
}
}
