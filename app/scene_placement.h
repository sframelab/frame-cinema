#pragma once
#include "openvr.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>

namespace cinema_placement {
using Matrix = vr::HmdMatrix34_t;
inline Matrix identity() { return {{{1,0,0,0},{0,1,0,0},{0,0,1,0}}}; }
inline Matrix multiply(const Matrix& a, const Matrix& b) {
    Matrix c{};
    for (int i=0;i<3;++i) {
        c.m[i][3]=a.m[i][3];
        for (int j=0;j<3;++j) {
            c.m[i][3]+=a.m[i][j]*b.m[j][3];
            for (int k=0;k<3;++k) c.m[i][j]+=a.m[i][k]*b.m[k][j];
        }
    }
    return c;
}
inline Matrix inverse(const Matrix& a) {
    Matrix b{};
    for (int i=0;i<3;++i) for (int j=0;j<3;++j) {
        b.m[i][j]=a.m[j][i]; b.m[i][3]-=a.m[j][i]*a.m[j][3];
    }
    return b;
}
inline double distance(const Matrix& a,const Matrix& b) {
    double value=0;
    for (int i=0;i<3;++i) value+=std::pow(a.m[i][3]-b.m[i][3],2);
    return std::sqrt(value);
}
inline double angle(const Matrix& a,const Matrix& b) {
    double trace=0;
    for (int i=0;i<3;++i) for (int j=0;j<3;++j) trace+=a.m[i][j]*b.m[i][j];
    return std::acos(std::clamp((trace-1)*.5,-1.,1.));
}
inline bool rigid(const Matrix& a) {
    for (const auto& row:a.m) for (float value:row) if (!std::isfinite(value)) return false;
    for (int i=0;i<3;++i) {
        if (std::abs(a.m[i][3])>10000) return false;
        for (int j=0;j<3;++j) {
            double dot=0;
            for (int k=0;k<3;++k) dot+=a.m[k][i]*a.m[k][j];
            if (std::abs(dot-(i==j?1.:0.))>.002) return false;
        }
    }
    const double det=a.m[0][0]*(a.m[1][1]*a.m[2][2]-a.m[1][2]*a.m[2][1])
        -a.m[0][1]*(a.m[1][0]*a.m[2][2]-a.m[1][2]*a.m[2][0])
        +a.m[0][2]*(a.m[1][0]*a.m[2][1]-a.m[1][1]*a.m[2][0]);
    return std::abs(det-1)<.002;
}
inline bool read_matrix(std::istream& in,Matrix& m) {
    for (auto& row:m.m) for (float& value:row) if (!(in>>value)) return false;
    return rigid(m);
}
inline void write_matrix(std::ostream& out,const Matrix& m) {
    for (const auto& row:m.m) for (float value:row) out << ' ' << value;
}
struct Packet {
    std::string session;
    uint64_t generation=0, revision=0, sequence=0;
    double created=0, linear_speed=0, angular_speed=0;
    int64_t pose_time_ns=0;
    int tracked=0;
    float width=0;
    Matrix head{}, screen{};
};
inline bool read(std::istream& in,Packet& p) {
    std::string magic, extra;
    if (!(in>>magic>>p.session>>p.generation>>p.revision>>p.sequence>>p.created>>p.tracked
          >>p.width>>p.linear_speed>>p.angular_speed) || (magic!="FCPL1" && magic!="FCPL2") || p.session.size()>100) return false;
    p.pose_time_ns=0;
    if (magic=="FCPL2" && (!(in>>p.pose_time_ns) || p.pose_time_ns<0)) return false;
    if (!read_matrix(in,p.head) || !read_matrix(in,p.screen) || (in>>extra)) return false;
    return p.generation>0 && p.revision>0 && p.sequence>0 && (p.tracked==0 || p.tracked==1)
        && std::isfinite(p.created) && std::isfinite(p.width) && p.width>=2 && p.width<=5000
        && std::isfinite(p.linear_speed) && p.linear_speed>=0
        && std::isfinite(p.angular_speed) && p.angular_speed>=0;
}

// The scene owns the anchor. Calibration changes coordinate systems only;
// it never chooses a new screen location from the current viewing direction.
class Bridge {
    std::string expected, cache_path;
    uint64_t generation=0, last_sequence=0, revision=0;
    Matrix conversion{}, candidate{}, cached{}, accepted_screen{};
    bool calibrated=false, cache_available=false;
    unsigned samples=0;
    double first_sample=0, previous_sample=0, reset_after=0, last_verified=0;
    void load_cache() {
        cache_available=false;
        std::ifstream in(cache_path);std::string magic,session,extra;uint64_t gen=0;
        if ((in>>magic>>session>>gen) && magic=="FCMAP1" && session==expected && gen==generation
            && read_matrix(in,cached) && !(in>>extra)) cache_available=true;
    }
    void save_cache() const {
        if (cache_path.empty()) return;
        std::ofstream out(cache_path+".tmp");out << std::setprecision(10);
        out << "FCMAP1 " << expected << ' ' << generation;write_matrix(out,conversion);out.close();
        if (out) std::rename((cache_path+".tmp").c_str(),cache_path.c_str());
    }
public:
    static constexpr double fresh_pose_seconds=.08;
    static constexpr double anchor_grace_seconds=1.0;
    bool ready=false;
    Matrix screen{};
    float width=4.2f;
    const char* reason="waiting for scene placement";
    Bridge(std::string session,std::string cache=""):expected(std::move(session)),cache_path(std::move(cache)) {}
    uint64_t anchor_revision() const { return revision; }
    uint64_t reference_generation() const { return generation; }
    bool rebase(const Matrix& delta) {
        if (!rigid(delta)) return false;
        samples=0;
        if (cache_available) cached=multiply(delta,cached);
        if (!calibrated) return false;
        conversion=multiply(delta,conversion);
        screen=multiply(delta,screen);
        save_cache();return true;
    }
    void invalidate(double now) {
        ready=false;calibrated=false;cache_available=false;samples=0;last_sequence=0;revision=0;
        last_verified=0;
        reset_after=now;reason="reference space changed";
        if (!cache_path.empty()) std::remove(cache_path.c_str());
    }
    bool update(const Packet& p,const vr::TrackedDevicePose_t& hmd,double now,bool synchronized=false) {
        ready=false;
        const auto fail=[&](const char* message) {reason=message;return false;};
        if (expected.empty() || p.session!=expected) return fail("different scene session");
        if (!std::isfinite(now) || !std::isfinite(p.created) || now-p.created < -.01 || now-p.created>anchor_grace_seconds)
            return fail("waiting for fresh scene pose");
        if (p.generation<generation || p.created<=reset_after) return fail("old reference space");
        if (!rigid(p.screen)) return fail("invalid transform");
        if (p.generation!=generation) {
            generation=p.generation;calibrated=false;samples=0;last_sequence=0;revision=0;
            last_verified=0;
            load_cache();
        }
        if (p.sequence<last_sequence || p.revision<revision) return fail("old placement packet");
        const bool tracked=p.tracked && hmd.bPoseIsValid && hmd.bDeviceIsConnected
            && hmd.eTrackingResult==vr::TrackingResult_Running_OK;
        const bool valid_head=rigid(p.head) && rigid(hmd.mDeviceToAbsoluteTracking);
        const bool fresh=now-p.created<=fresh_pose_seconds;
        if (!tracked || !valid_head || !fresh) {
            // The accepted transform is fixed in standing space and does not
            // depend on the next head sample. Keep it through brief tracking or
            // scheduling gaps, without using an uncertain pose to move it.
            // New invalid samples must never renew this grace period.
            if (calibrated && revision==p.revision && p.sequence>=last_sequence
                && distance(p.screen,accepted_screen)<.0001 && angle(p.screen,accepted_screen)<.001
                && now>=last_verified && now-last_verified<=anchor_grace_seconds) {
                ready=true;
                // A width request does not invalidate the already placed
                // screen. Defer it together with any uncertain pose; do not
                // blank a valid screen merely because Size was pressed.
                reason=p.width!=width ? "deferring resize until fresh tracking"
                    : (tracked && valid_head ? "retaining anchor during scene hitch" : "retaining anchor during tracking gap");
                return true;
            }
            samples=0;
            return fail(!tracked ? "waiting for tracking" : (!valid_head ? "invalid transform" : "waiting for fresh scene pose"));
        }
        if (!calibrated) {
            double linear=0,angular=0;
            for (int i=0;i<3;++i) {
                linear+=std::pow(hmd.vVelocity.v[i],2);angular+=std::pow(hmd.vAngularVelocity.v[i],2);
            }
            if (!synchronized && (p.linear_speed>.025 || p.angular_speed>.025 || std::sqrt(linear)>.025 || std::sqrt(angular)>.025)) {
                samples=0;return fail("waiting for steady tracking");
            }
            if (p.sequence==last_sequence) return fail("collecting alignment samples");
            last_sequence=p.sequence;
            const auto next=multiply(hmd.mDeviceToAbsoluteTracking,inverse(p.head));
            const double max_distance=synchronized ? .005 : .003;
            const double max_angle=synchronized ? .0025 : .0015;
            if (!samples || now-previous_sample>.2 || distance(next,candidate)>max_distance || angle(next,candidate)>max_angle) {
                candidate=next;first_sample=now;samples=0;
            }
            previous_sample=now;++samples;
            if (samples<6 || now-first_sample<.15) return fail("collecting alignment samples");
            // Reuse the exact map across source restarts when revalidation agrees.
            conversion=cache_available && distance(next,cached)<.005 && angle(next,cached)<.002 ? cached : candidate;
            calibrated=true;save_cache();
        }
        if (revision==p.revision && (distance(p.screen,accepted_screen)>.0001 || angle(p.screen,accepted_screen)>.001))
            return fail("anchor changed without a revision");
        if (revision!=p.revision) {
            revision=p.revision;accepted_screen=p.screen;
            screen=multiply(conversion,accepted_screen);
        }
        last_sequence=std::max(last_sequence,p.sequence);
        last_verified=p.created;
        width=p.width;ready=true;reason="aligned";return true;
    }
};
}
