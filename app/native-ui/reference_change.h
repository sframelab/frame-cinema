#pragma once
#include "scene_placement.h"

// Compare a reference with its previous value, not with perfect orthogonality.
// acos(trace(A^T A)) can report motion for an unchanged float32 rotation.
inline bool cinema_reference_changed(const cinema_placement::Matrix& next,
                                     const cinema_placement::Matrix& previous) {
    if(cinema_placement::distance(next,previous)>0.00001)return true;
    double squared=0;
    for(int row=0;row<3;++row)for(int column=0;column<3;++column){
        const double delta=double(next.m[row][column])-double(previous.m[row][column]);
        squared+=delta*delta;
    }
    // For rotations, ||A-B||_F^2 = 8 sin^2(angle/2). Preserve the existing
    // 1e-5-radian threshold without the unstable near-zero acos operation.
    constexpr double threshold=1e-5;
    const double sine=std::sin(threshold*.5);
    return squared>8*sine*sine;
}
