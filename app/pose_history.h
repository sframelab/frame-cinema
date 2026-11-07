#pragma once
#include "scene_placement.h"
#include <deque>

namespace cinema_placement {
// Bracket a past target with actual samples. Never extrapolate across a stall or reset.
class PoseHistory {
    struct Sample { int64_t ns;vr::TrackedDevicePose_t pose; };
    std::deque<Sample> samples;
    static bool valid(const vr::TrackedDevicePose_t& p) {
        return p.bPoseIsValid && p.bDeviceIsConnected && p.eTrackingResult==vr::TrackingResult_Running_OK && rigid(p.mDeviceToAbsoluteTracking);
    }
public:
    void clear() { samples.clear(); }
    void add(int64_t ns,const vr::TrackedDevicePose_t& p) {
        if (!valid(p) || (!samples.empty() && ns<=samples.back().ns)) {clear();return;}
        samples.push_back({ns,p});
        while (samples.size()>1 && samples.front().ns<ns-250000000) samples.pop_front();
    }
    bool at(int64_t ns,vr::TrackedDevicePose_t& result) const {
        if (samples.empty() || ns<samples.front().ns || ns>samples.back().ns) return false;
        for (size_t i=0;i<samples.size();++i) {
            if (samples[i].ns==ns) {result=samples[i].pose;return true;}
            if (samples[i].ns<ns) continue;
            const auto& a=samples[i-1];const auto& b=samples[i];
            if (b.ns-a.ns>30000000) return false;
            const double t=double(ns-a.ns)/double(b.ns-a.ns);
            const auto& am=a.pose.mDeviceToAbsoluteTracking;const auto& bm=b.pose.mDeviceToAbsoluteTracking;
            const auto relative=multiply(inverse(am),bm);
            double axis[3]={(relative.m[2][1]-relative.m[1][2])*.5,
                (relative.m[0][2]-relative.m[2][0])*.5,(relative.m[1][0]-relative.m[0][1])*.5};
            double sine=0;for(double x:axis)sine+=x*x;
            sine=std::sqrt(sine);
            const double cosine=std::clamp((relative.m[0][0]+relative.m[1][1]+relative.m[2][2]-1)*.5,-1.,1.);
            const double theta=std::atan2(sine,cosine);
            // A large change within 30 ms indicates a discontinuity, not a head movement.
            if (theta>.3 || distance(am,bm)>.15) return false;
            Matrix rotation=identity();
            if (sine>1e-8) {
                for(double& x:axis)x/=sine;
                const double c=std::cos(theta*t),s=std::sin(theta*t);
                const double cross[3][3]={{0,-axis[2],axis[1]},{axis[2],0,-axis[0]},{-axis[1],axis[0],0}};
                for(int r=0;r<3;++r)for(int col=0;col<3;++col)
                    rotation.m[r][col]=(r==col?c:0)+(1-c)*axis[r]*axis[col]+s*cross[r][col];
            }
            result=a.pose;result.mDeviceToAbsoluteTracking=multiply(am,rotation);
            for(int r=0;r<3;++r)result.mDeviceToAbsoluteTracking.m[r][3]=am.m[r][3]*(1-t)+bm.m[r][3]*t;
            return rigid(result.mDeviceToAbsoluteTracking);
        }
        return false;
    }
};
}
